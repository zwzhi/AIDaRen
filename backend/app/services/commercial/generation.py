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
    ProviderRequestError,
    poll_prediction,
    submit_generation,
)

logger = logging.getLogger("app.commercial.generation")

_POLL_BACKOFF_SEC = 8.0


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
        await db.commit()
        return {"cancelled": True}

    # SUBMIT_UNKNOWN：冻结自动重试（人工对账前不重发，INV-04）
    if attempt.status == "SUBMIT_UNKNOWN":
        return {"failed": True, "error": "SUBMIT_RESULT_UNKNOWN：上游结果未明，等待人工对账"}

    # 恢复路径：已有上游任务号 → 只查询
    if attempt.provider_prediction_id:
        attempt.status = "PROVIDER_RUNNING"
        task.provider_task_id = attempt.provider_prediction_id
        await db.commit()
        return {"awaiting_poll": True}

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
        await db.commit()
        return {"failed": True, "error": attempt.error_message}
    try:
        body = build_request_body(dict(attempt.params_json), DRAFT_H3_CAPABILITIES)
    except RequestBuildError as exc:
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = exc.code
        attempt.error_message = exc.message
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
    except ProviderRequestError as exc:
        # 明确失败（4xx/5xx 响应）：未送达或明确拒绝，可安全置失败
        attempt.status = "PROVIDER_FAILED"
        attempt.error_code = f"HTTP_{exc.status_code}"
        attempt.error_message = exc.message[:500]
        await db.commit()
        return {"failed": True, "error": attempt.error_message}

    # 上游 ID 立即落库（下载中断后只拉成片，不重新生成）
    attempt.provider_prediction_id = prediction_id
    attempt.status = "PROVIDER_RUNNING"
    task.provider_task_id = prediction_id
    await db.commit()
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

    # Mock 预测：本机测试片段直接归档（零网络），行为与真实轮询一致
    from app.services.commercial import mock_provider

    if prediction_id.startswith("MOCK-"):
        clip = mock_provider.mock_clip_path(prediction_id)
        attempt.output_asset_key = clip.name
        attempt.status = "GENERATED"
        await _record_pending_usage(db, attempt)
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
                                 api_key=api_key, transport=transport)


async def _download_phase(
    attempt: CvGenerationAttempt, *, db: AsyncSession, base_url: str,
    api_key: str, transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """下载并归档输出；失败仅标记待下载，保留上游任务号（J05）。"""
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
    # C04：真实账单未知 → 待结算（金额来自报价快照，绝不写 0 也不虚报实结）
    await _record_pending_usage(db, attempt)
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
    )


async def poll_commercial_task(task_id: int) -> None:
    """poller 分派入口：查 TaskRun → 找 attempt → poll_attempt。

    恢复语义与执行器约定一致：重试仅针对查询与下载，绝不重新提交。
    """
    from app.config import get_settings
    from app.database import AsyncSessionLocal
    from app.models_tasks import TaskRun
    from app.services.providers.atlas.client import (
        ProviderNotConfigured,
        resolve_provider_for_commercial_task,
    )

    settings = get_settings()
    async with AsyncSessionLocal() as db:
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
        if result.get("retry_poll"):
            task.next_action_at = datetime.now(UTC) + timedelta(seconds=_POLL_BACKOFF_SEC)
            await db.commit()
            return
        if result.get("retry_download"):
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
