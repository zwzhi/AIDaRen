"""commercial/video_generate 执行与恢复（任务书 §9 / INV-04）。

铁律：
- 上游任务号一创建立即落库；恢复路径有号只查询/下载，绝不重新提交；
- SUBMIT_UNKNOWN 之后冻结自动重试，人工对账前不发起第二次收费请求；
- 下载失败只重试下载（OUTPUT_PENDING_DOWNLOAD）；
- 查询失败按退避续查，不判死、不重建。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import CvGenerationAttempt
from app.services.providers.atlas.h3_reference import (
    H3VideoAdapter,
    PreviewTask,
    ProviderRequestError,
    SubmitOutcomeUnknownError,
    poll_prediction,
    submit_generation,
)

logger = logging.getLogger("app.commercial.generation")

# 账本业务事件键：(attempt_ref, event_key) 唯一 → 幂等入账
EVENT_PENDING = "generation.pending"
EVENT_SETTLED = "generation.settled"


async def _release_reservation_safe(db: AsyncSession, attempt: CvGenerationAttempt) -> None:
    """释放 attempt 的预留（仅用于确未产生上游费用的失败/取消）。

    结果不明（SUBMIT_UNKNOWN）与上游已执行失败绝不调用——费用未核实
    不得当作免费释放。预留缺失时静默跳过（历史数据/测试替身）。
    """
    if not attempt.reservation_id:
        return
    from app.services.commercial.budget_service import release_reservation

    try:
        await release_reservation(db, reservation_id=attempt.reservation_id)
    except Exception:  # noqa: BLE001 —— 释放失败不掩盖主错误
        logger.exception("release reservation failed attempt=%s", attempt.id)

_POLL_BACKOFF_SEC = 8.0


async def submit_preview_generation(
    frozen_revision: dict[str, Any],
    *,
    adapter: H3VideoAdapter | None = None,
) -> PreviewTask:
    """提交可恢复的 Mock/沙箱预览任务。

    该入口不经过真实提交函数，除非调用方显式传入已验证的生产适配器。
    同一冻结版本由适配器按 hash 幂等复用任务。
    """
    selected = adapter or H3VideoAdapter(mode="mock")
    result = selected.submit_preview(frozen_revision)
    if hasattr(result, "__await__"):
        result = await result
    return result


async def _transition_task_to_poll(db: AsyncSession, task: Any, prediction_id: str) -> None:
    """把任务行推进到 awaiting_poll：上游 ID 落行、安排轮询、释放租约（P1-4）。

    executor 传入的 task 可能是已脱管实例（其会话在读事务关闭后结束），
    因此一律按 id 在当前会话重载任务行再写，保证状态真正持久化；
    单元测试传入的不存在替身 id 自动跳过（不视为错误）。
    """
    from app.models_tasks import TaskRun

    row = await db.get(TaskRun, int(task.id))
    if row is not None:
        row.status = "awaiting_poll"
        row.provider_task_id = prediction_id
        row.next_action_at = datetime.now(UTC) + timedelta(seconds=_POLL_BACKOFF_SEC)
        row.lease_token = None
        row.lease_until = None
    await db.commit()


async def execute_generation_task(
    task: Any,
    *,
    db: AsyncSession,
    base_url: str,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """平台 handler 主体：提交或恢复。取消前置检查，不碰上游。"""
    attempt_id = int((task.payload or {}).get("attempt_id") or 0)
    attempt = await db.get(CvGenerationAttempt, attempt_id)
    if attempt is None:
        return {"failed": True, "error": f"attempt {attempt_id} 不存在"}

    # 用户取消（未提交）：不调用上游，释放预留
    if getattr(task, "cancel_requested", False) and not attempt.provider_prediction_id:
        attempt.status = "CANCELLED"
        await _release_reservation_safe(db, attempt)
        await db.commit()
        return {"cancelled": True}

    # SUBMIT_UNKNOWN：冻结自动重试（人工对账前不重发，INV-04）
    if attempt.status == "SUBMIT_UNKNOWN":
        return {"failed": True, "error": "SUBMIT_RESULT_UNKNOWN：上游结果未明，等待人工对账"}

    # 恢复路径：已有上游任务号 → 只查询（查询/下载不受新任务付费门影响）
    if attempt.provider_prediction_id:
        attempt.status = "PROVIDER_RUNNING"
        await _transition_task_to_poll(db, task, attempt.provider_prediction_id)
        return {"awaiting_poll": True}

    # 首次提交前的门禁重检（P1-6）：任务可能在排队期间配置降级——
    # 付费总开关关闭/模型 ID 缺失/能力未验证时拒绝提交，绝不回落占位模型。
    from app.services.commercial import mock_provider as _mock_provider

    if not _mock_provider.mock_enabled():
        from app.services.providers.atlas.client import (
            CapabilityUnverified,
            ProviderNotConfigured,
            resolve_provider_for_commercial_task,
        )

        try:
            resolve_provider_for_commercial_task(require_verified=True)
        except (ProviderNotConfigured, CapabilityUnverified) as exc:
            attempt.status = "PROVIDER_FAILED"
            attempt.error_code = type(exc).__name__ == "CapabilityUnverified" \
                and "MODEL_CAPABILITY_UNVERIFIED" or "PROVIDER_NOT_CONFIGURED"
            attempt.error_message = f"执行前门禁阻断（未提交上游）: {exc}"[:500]
            await _release_reservation_safe(db, attempt)  # 未提交 → 释放预留
            await db.commit()
            return {"failed": True, "error": attempt.error_message}

    # 首次提交：从已确认计划参数快照构造完整请求（与报价同源）
    attempt.status = "SUBMITTING"
    await db.commit()
    from app.services.commercial import mock_provider
    from app.services.commercial.generation_request import (
        RequestBuildError,
        build_request_body,
    )
    from app.services.providers.atlas.h3_reference import DRAFT_H3_CAPABILITIES

    if not attempt.params_json:
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = "PLAN_SNAPSHOT_MISSING"
        attempt.error_message = "attempt 缺少计划参数快照，拒绝提交"
        await _release_reservation_safe(db, attempt)  # 未提交 → 释放预留
        await db.commit()
        return {"failed": True, "error": attempt.error_message}
    try:
        body = build_request_body(dict(attempt.params_json), DRAFT_H3_CAPABILITIES)
    except RequestBuildError as exc:
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = exc.code
        attempt.error_message = exc.message
        await _release_reservation_safe(db, attempt)  # 未提交 → 释放预留
        await db.commit()
        return {"failed": True, "error": exc.message}

    # 素材句柄：内部资产 ID → 上游句柄（含归属/授权/血缘校验；Mock 模式零网络）
    try:
        from app.services.commercial.media_delivery import ensure_generation_handles

        asset_ids: list[int] = sorted({
            *[int(i) for i in attempt.params_json.get("actor_image_asset_ids") or []],
            *[int(i) for i in attempt.params_json.get("product_image_asset_ids") or []],
            *[int(i) for i in attempt.params_json.get("scene_image_asset_ids") or []],
            *[int(i) for i in attempt.params_json.get("voice_reference_asset_ids") or []],
        })
        handles = await ensure_generation_handles(
            db, asset_ids, base_url=base_url, api_key=api_key, transport=transport,
            mock=mock_provider.mock_enabled(),
        )
        body = dict(body)
        for key in ("subject_image_asset_ids", "product_image_asset_ids",
                    "scene_image_asset_ids", "voice_reference_asset_ids"):
            if key in body and isinstance(body[key], list):
                body[key] = [handles.get(int(i), i) for i in body[key]]
    except Exception as exc:  # noqa: BLE001
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = "ASSET_DELIVERY_FAILED"
        attempt.error_message = f"素材交付失败：{exc}"[:500]
        await _release_reservation_safe(db, attempt)  # 未提交 → 释放预留
        await db.commit()
        return {"failed": True, "error": attempt.error_message}

    try:
        if mock_provider.mock_enabled():
            prediction_id = await mock_provider.mock_submit(body)
        else:
            prediction_id = await submit_generation(
                body, base_url=base_url, api_key=api_key, transport=transport,
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        # 请求可能已送达：结果不明，绝不自动重发
        attempt.status = "SUBMIT_UNKNOWN"
        attempt.error_code = "SUBMIT_RESULT_UNKNOWN"
        attempt.error_message = f"提交结果不明：{type(exc).__name__}: {exc}"
        await db.commit()
        return {"failed": True, "error": attempt.error_message}
    except SubmitOutcomeUnknownError as exc:
        # HTTP 成功但无任务 ID：上游可能已创建任务 → 结果不明，冻结不重发、
        # 不释放预留（费用未核实，不得当作免费），等待人工对账（P2-3）
        attempt.status = "SUBMIT_UNKNOWN"
        attempt.error_code = "SUBMIT_RESULT_UNKNOWN"
        attempt.error_message = f"提交结果不明：{exc}"[:500]
        await db.commit()
        return {"failed": True, "error": attempt.error_message}
    except ProviderRequestError as exc:
        # 明确失败（4xx/5xx 响应）：未送达或明确拒绝，可安全置失败并释放预留
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = f"HTTP_{exc.status_code}"
        attempt.error_message = exc.message[:500]
        await _release_reservation_safe(db, attempt)  # 明确未送达 → 释放预留
        await db.commit()
        return {"failed": True, "error": attempt.error_message}

    # 上游 ID 立即落库（下载中断后只拉成片，不重新生成）；
    # 任务行同步推进到 awaiting_poll（否则调度器视角永远停留在 running，
    # 租约到期被孤儿回收后无限重跑恢复路径——P1-4）
    attempt.provider_prediction_id = prediction_id
    attempt.status = "PROVIDER_RUNNING"
    await _transition_task_to_poll(db, task, prediction_id)
    return {"awaiting_poll": True}


def _output_disk_path(prediction_id: str) -> Path:
    from app.services.commercial.storage import commercial_storage_root

    root = commercial_storage_root() / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prediction_id}.mp4"


async def poll_attempt(
    attempt: CvGenerationAttempt,
    *,
    db: AsyncSession,
    base_url: str,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """轮询单个 attempt：退避续查 / 待下载重试 / 完成归档。"""
    prediction_id = attempt.provider_prediction_id or ""
    if not prediction_id:
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = "missing_provider_task_id"
        await db.commit()
        return {"failed": True}
    if attempt.status == "GENERATED":
        # 已完成短路（P1-2）：重放/多任务重复轮询不重复下载、不重复入账
        return {"generated": True, "output_key": attempt.output_asset_key, "already": True}

    # Mock 预测：本机测试片段直接归档（零网络），行为与真实轮询一致
    from app.services.commercial import mock_provider

    if prediction_id.startswith("MOCK-"):
        duration_ms = int((attempt.params_json or {}).get("duration_ms") or 0) or None
        clip = mock_provider.mock_clip_path(prediction_id, duration_ms)
        attempt.output_asset_key = clip.name
        attempt.status = "GENERATED"
        await _record_pending_usage(db, attempt)
        # Mock 价为确定性本地价（可核实）→ 生成即结算，池账目闭环
        await _settle_generation(db, attempt, mock_price=True)
        await db.commit()
        return {"generated": True, "output_key": attempt.output_asset_key, "mock": True}

    # 上一轮已生成只差下载：只做下载
    if attempt.status == "OUTPUT_PENDING_DOWNLOAD":
        return await _download_phase(attempt, db=db, base_url=base_url,
                                     api_key=api_key, transport=transport)

    try:
        result = await poll_prediction(
            prediction_id, base_url=base_url, api_key=api_key, transport=transport,
        )
    except (httpx.TimeoutException, httpx.TransportError, ProviderRequestError) as exc:
        # J04：查询失败 → 退避续查，不判死不重建
        logger.warning("commercial poll backoff pred=%s err=%s", prediction_id, exc)
        return {"retry_poll": True, "backoff_sec": _POLL_BACKOFF_SEC}

    if result.status == "failed":
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = "PROVIDER_FAILED"
        attempt.error_message = (result.error or "")[:500]
        await db.commit()
        return {"failed": True, "error": attempt.error_message}
    if result.status != "succeeded":
        return {"retry_poll": True, "backoff_sec": _POLL_BACKOFF_SEC}
    if not result.output_urls:
        # 成功但无输出地址：进入待下载（由管理端/下一轮补 URL）
        attempt.status = "OUTPUT_PENDING_DOWNLOAD"
        await db.commit()
        return {"retry_download": True}

    attempt.output_urls_snapshot = list(result.output_urls)  # type: ignore[attr-defined]
    await db.commit()
    return await _download_phase(attempt, db=db, base_url=base_url,
                                 api_key=api_key, transport=transport,
                                 cost_amount=result.cost_amount,
                                 cost_currency=result.cost_currency)


async def _download_phase(
    attempt: CvGenerationAttempt, *, db: AsyncSession, base_url: str,
    api_key: str, transport: httpx.AsyncBaseTransport | None,
    cost_amount=None, cost_currency: str | None = None,
) -> dict[str, Any]:
    """下载并归档输出；失败仅标记待下载，保留上游任务号（J05）。

    cost_amount 为上游随任务返回的可核实费用：有则结算（预留转实扣、
    账本行转 SETTLED 且金额=实收）；无则保持 SETTLEMENT_PENDING（估算金额）。
    """
    from app.services.providers.atlas.media import fetch_url_to_file

    urls = list(getattr(attempt, "output_urls_snapshot", None) or [])
    if not urls:
        # 待下载重试路径：重新查询一次拿 URL
        try:
            result = await poll_prediction(
                attempt.provider_prediction_id or "", base_url=base_url,
                api_key=api_key, transport=transport,
            )
        except (httpx.TimeoutException, httpx.TransportError, ProviderRequestError):
            return {"retry_download": True}
        urls = list(result.output_urls)
        if not urls:
            return {"retry_download": True}

    dest = _output_disk_path(attempt.provider_prediction_id or "unknown")
    try:
        await fetch_url_to_file(urls[0], dest, transport=transport)
    except Exception as exc:  # noqa: BLE001 —— 下载失败不重新生成
        logger.warning("commercial output download failed pred=%s err=%s",
                       attempt.provider_prediction_id, exc)
        attempt.status = "OUTPUT_PENDING_DOWNLOAD"
        await db.commit()
        return {"retry_download": True}

    attempt.output_asset_key = str(dest.name)
    attempt.status = "GENERATED"
    # C04：真实账单未知 → 待结算（金额来自报价快照，绝不写 0 也不虚报实结）；
    # 上游返回可核实费用则直接结算（P1-5）
    await _record_pending_usage(db, attempt)
    await _settle_generation(db, attempt, confirmed_amount=cost_amount,
                             cost_currency=cost_currency)
    await db.commit()
    return {"generated": True, "output_key": attempt.output_asset_key}


async def _record_pending_usage(db: AsyncSession, attempt: CvGenerationAttempt) -> None:
    from decimal import Decimal

    from app.models_commercial import CvCostQuote
    from app.services.commercial.budget_service import record_usage

    quote = await db.get(CvCostQuote, attempt.quote_id) if attempt.quote_id else None
    amount = quote.estimated_amount if quote else Decimal("0")
    await record_usage(
        db, attempt_ref=str(attempt.id), provider="atlas", model=quote.model_id if quote else "",
        amount=amount, currency=(quote.currency if quote else "USD"), fx_rate=None,
        settlement_status="SETTLEMENT_PENDING",
        provider_task_id=attempt.provider_prediction_id,
        usage_meta={"note": "生成完成，等待上游账单核对"},
        event_key=EVENT_PENDING,
    )


async def _settle_generation(
    db: AsyncSession, attempt: CvGenerationAttempt, *,
    confirmed_amount=None, cost_currency: str | None = None,
    mock_price: bool = False,
) -> None:
    """按可核实费用结算一次生成：预留转实扣 + 账本行转 SETTLED（幂等）。

    - mock_price=True：Mock 确定性本地价（报价快照金额）视作可核实费用；
    - confirmed_amount：上游随任务返回的实收金额；
    - 两者皆无：保持 SETTLEMENT_PENDING，预留保留（费用未核实不结算）。
    """
    from decimal import Decimal

    from sqlalchemy import select as _select

    from app.models_commercial import CvCostQuote, CvUsageLedger
    from app.services.commercial.budget_service import record_usage, settle_reservation

    quote = await db.get(CvCostQuote, attempt.quote_id) if attempt.quote_id else None
    if mock_price:
        actual = quote.estimated_amount if quote else Decimal("0")
        currency = (quote.currency if quote else "USD")
        note = "Mock 确定性本地价，生成即结算"
    elif confirmed_amount is not None:
        actual = Decimal(str(confirmed_amount))
        currency = cost_currency or "USD"
        note = "上游随任务返回可核实费用"
    else:
        return  # 无可核实账单 → 保持待结算
    if attempt.reservation_id:
        try:
            await settle_reservation(db, reservation_id=attempt.reservation_id,
                                     actual_amount=actual)
        except Exception:  # noqa: BLE001 —— 结算失败不阻断归档，留给对账
            logger.exception("settle reservation failed attempt=%s", attempt.id)
            return
    # 账本行 PENDING → SETTLED（金额=实收；无行则补记）
    row = (await db.execute(
        _select(CvUsageLedger).where(
            CvUsageLedger.attempt_ref == str(attempt.id),
            CvUsageLedger.event_key == EVENT_PENDING,
        )
    )).scalar_one_or_none()
    if row is not None:
        row.amount = actual
        row.currency = currency
        row.settlement_status = "SETTLED"
        row.event_key = EVENT_SETTLED
        row.usage_meta = {"note": note,
                          "estimated": str(quote.estimated_amount) if quote else None}
    else:
        await record_usage(
            db, attempt_ref=str(attempt.id), provider="atlas",
            model=quote.model_id if quote else "", amount=actual, currency=currency,
            fx_rate=None, settlement_status="SETTLED",
            provider_task_id=attempt.provider_prediction_id,
            usage_meta={"note": note}, event_key=EVENT_SETTLED,
        )


async def poll_commercial_task(task_id: int, db: AsyncSession | None = None) -> None:
    """poller 分派入口：查 TaskRun → 找 attempt → poll_attempt。

    恢复语义与执行器约定一致：重试仅针对查询与下载，绝不重新提交。
    db 参数供同步驱动路径/测试注入会话；生产轮询走 AsyncSessionLocal。
    """
    from app.config import get_settings
    from app.database import AsyncSessionLocal
    from app.models_tasks import TaskRun
    from app.services.providers.atlas.client import (
        ProviderNotConfigured,
        resolve_provider_for_commercial_task,
    )

    settings = get_settings()
    if db is not None:
        await _poll_task_with_session(db, task_id, settings)
        return
    async with AsyncSessionLocal() as session:
        await _poll_task_with_session(session, task_id, settings)


async def _poll_task_with_session(db: AsyncSession, task_id: int, settings) -> None:
    from app.models_tasks import TaskRun
    from app.services.providers.atlas.client import (
        ProviderNotConfigured,
        resolve_provider_for_commercial_task,
    )

    task = await db.get(TaskRun, task_id)
    if task is None or task.status != "awaiting_poll":
        return
    attempt_id = int((task.payload or {}).get("attempt_id") or 0)
    attempt = await db.get(CvGenerationAttempt, attempt_id)
    if attempt is None:
        task.status = "failed"
        task.error_code = "attempt_missing"
        await db.commit()
        return
    try:
        provider = resolve_provider_for_commercial_task()
        base_url, api_key = provider.base_url, provider.api_key
    except ProviderNotConfigured:
        base_url = settings.atlas_base_url
        api_key = (settings.atlas_api_key or "").strip()
    result = await poll_attempt(attempt, db=db, base_url=base_url, api_key=api_key)
    if result.get("retry_poll") or result.get("retry_download"):
        task.next_action_at = datetime.now(UTC) + timedelta(seconds=_POLL_BACKOFF_SEC)
        await db.commit()
        return
    if result.get("generated"):
        task.status = "succeeded"
        task.finished_at = datetime.now(UTC)
        task.result_payload = result
        await db.commit()
        return
    # failed
    task.status = "failed"
    task.error_code = attempt.error_code or "PROVIDER_FAILED"
    task.error_message = attempt.error_message
    task.finished_at = datetime.now(UTC)
    await db.commit()
