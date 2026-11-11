"""报价、预算预留与提交幂等（任务书 §10 / §9.3）。

- 报价绑定完整参数指纹：素材/台词/时长/分辨率/音频/参数版本全量参与；
- 参数改变或过期 → 旧批准失效（QUOTE_CHANGED / QUOTE_EXPIRED）；
- 预算并发：池行条件更新（总额 - 已结算 - 有效预留 ≥ 本次），绝不超额；
- 幂等：client_request_id + payload_hash 相同 → 返回原 attempt（不重复扣预算），
  相同 ID 不同参数 → 冲突（409 语义）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import (
    CvBudgetPool,
    CvBudgetReservation,
    CvCostQuote,
    CvGenerationAttempt,
    CvUsageLedger,
)

_FINGERPRINT_IGNORED_KEYS = frozenset()


class BudgetError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class IdempotencyConflict(Exception):
    """同 client_request_id 不同参数：409 语义。"""


@dataclass(frozen=True)
class ApprovalResult:
    attempt_id: int
    reservation_id: int | None
    idempotent_replay: bool = False


def compute_request_fingerprint(params: dict[str, Any]) -> str:
    """完整参数指纹：排序后规范化 JSON 的 sha256（素材列表内部排序）。"""
    normalized: dict[str, Any] = {}
    for key in sorted(params):
        value = params[key]
        if isinstance(value, (list, tuple)):
            normalized[key] = sorted(str(v) for v in value)
        else:
            normalized[key] = value
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def request_quote(
    db: AsyncSession, *, params: dict[str, Any], api_key: str, base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CvCostQuote:
    """按已确认计划参数取得报价并存快照。

    请求体与生成共用同一构造器（generation_request.build_request_body），
    确保报价与提交的能力/费用条件完全一致；Mock 模式返回明确标记的
    模拟价（历史展示价 $0.015/s），不代表真实报价。
    """
    from datetime import UTC, datetime, timedelta

    from app.schemas_commercial import CostQuote as QuoteObj
    from app.services.commercial import mock_provider
    from app.services.commercial.generation_request import build_request_body
    from app.services.providers.atlas.h3_reference import DRAFT_H3_CAPABILITIES

    fingerprint = compute_request_fingerprint(params)
    body = build_request_body(params, DRAFT_H3_CAPABILITIES)  # 能力校验在此前置

    if mock_provider.mock_enabled():
        now = datetime.now(UTC)
        quote = QuoteObj(
            # 含微秒：同一秒内相同参数指纹的多次报价也不得撞唯一键
            quote_id=f"MOCK-q-{now.strftime('%H%M%S%f')}-{fingerprint[:8]}",
            provider_id="atlas",
            model_id=str(params.get("model_id") or ""),
            request_fingerprint=fingerprint,
            requested_duration_ms=int(params.get("duration_ms") or 0),
            resolution_id=str(params.get("resolution_id") or ""),
            currency="USD",
            estimated_amount=mock_provider.mock_quote_amount(body),
            is_estimated=True,
            price_source="mock:$0.015/s（历史展示价·仅开发模拟，非真实报价）",
            created_at=now,
            expires_at=now + timedelta(seconds=600),
            provider_payload_redacted={"mock": True},
        )
    else:
        from app.services.providers.atlas.pricing import quote_generation

        quote = await quote_generation(
            body,
            base_url=base_url, api_key=api_key,
            request_fingerprint=fingerprint,
            model_id=str(params.get("model_id") or ""),
            requested_duration_ms=int(params.get("duration_ms") or 0),
            resolution_id=str(params.get("resolution_id") or ""),
            transport=transport,
        )
    row = CvCostQuote(
        quote_key=quote.quote_id,
        provider_id="atlas",
        model_id=quote.model_id,
        request_fingerprint=fingerprint,
        resolution_id=quote.resolution_id,
        requested_duration_ms=quote.requested_duration_ms,
        currency=quote.currency,
        estimated_amount=quote.estimated_amount,
        is_estimated=quote.is_estimated,
        price_source=quote.price_source,
        provider_payload_redacted=quote.provider_payload_redacted,
        expires_at=quote.expires_at,
    )
    db.add(row)
    await db.flush()
    return row


def _ensure_not_expired(quote: CvCostQuote, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    expires = quote.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            raise BudgetError("QUOTE_EXPIRED", "报价已过期，请重新报价后再确认")


async def _reserve_with_pool_row(
    db: AsyncSession, *, quote: CvCostQuote, created_by: int
) -> CvBudgetReservation:
    """池行 FOR UPDATE + 条件判断：可用额度不足即拒绝。

    池按当前模式选择：Mock 走 scope=mock 演示池，真实模式走 scope=real 池；
    两池互不继承（模拟预算批准不算真实付费授权）。
    """
    from app.services.commercial import mock_provider

    scope = "mock" if mock_provider.mock_enabled() else "real"
    pool = (await db.execute(
        select(CvBudgetPool).where(
            CvBudgetPool.name == "default", CvBudgetPool.scope == scope,
        ).order_by(CvBudgetPool.id.desc()).limit(1).with_for_update()
    )).scalar_one_or_none()
    if pool is None:
        raise BudgetError(
            "BUDGET_NOT_CONFIGURED",
            f"{'演示' if scope == 'mock' else '真实'}预算池未初始化，请管理员配置对应模式的总预算",
        )
    if pool.paused:
        raise BudgetError("BUDGET_PAUSED", "预算池已暂停（可能因真实费用超预留），请补充预算后恢复")
    available = pool.total_amount - pool.settled_amount - pool.reserved_amount
    if quote.estimated_amount > available:
        raise BudgetError(
            "BUDGET_EXCEEDED",
            f"可用预算 {available} {pool.currency} 不足以覆盖本次报价 {quote.estimated_amount} {quote.currency}",
        )
    pool.reserved_amount = (pool.reserved_amount or Decimal(0)) + quote.estimated_amount
    reservation = CvBudgetReservation(
        pool_id=pool.id, quote_id=quote.id,
        amount=quote.estimated_amount, currency=quote.currency,
        created_by=created_by,
    )
    db.add(reservation)
    await db.flush()
    return reservation


async def reserve_budget_atomic(
    engine, *, amount: Decimal, owner_id: int, tag: str, pool_name: str = "default",
) -> dict[str, Any]:
    """独立连接上的原子条件预留（多请求并发路径；条件 UPDATE 不超发）。"""
    async with engine.begin() as conn:
        updated = (await conn.execute(
            text(
                "UPDATE cv_budget_pools SET reserved_amount = reserved_amount + :amt "
                "WHERE name = :pname AND paused = false "
                "AND (total_amount - settled_amount - reserved_amount) >= :amt "
                "RETURNING id"
            ),
            {"amt": amount, "pname": pool_name},
        )).scalar_one_or_none()
        if updated is None:
            raise BudgetError("BUDGET_EXCEEDED", "并发预留失败：可用预算不足")
        reservation_id = (await conn.execute(
            text(
                "INSERT INTO cv_budget_reservations (pool_id, amount, currency, status, created_by) "
                "VALUES (:pool, :amt, 'USD', 'reserved', :owner) RETURNING id"
            ),
            {"pool": int(updated), "amt": amount, "owner": int(owner_id)},
        )).scalar_one()
        return {"ok": True, "reservation_id": int(reservation_id), "tag": tag}


async def approve_and_reserve(
    db: AsyncSession, *, quote: CvCostQuote, params: dict[str, Any],
    client_request_id: str, created_by: int,
    production_id: int | None = None, generation_unit_id: int | None = None,
) -> ApprovalResult:
    """批准报价并预留预算、落提交意图（同一事务；§9.3-5）。

    幂等规则（J01）：
    - 相同 client_request_id + 相同 payload_hash → 返回原 attempt（idempotent_replay）；
    - 相同 ID + 不同参数 → IdempotencyConflict；
    - 报价过期 / 指纹不匹配 → QUOTE_EXPIRED / QUOTE_CHANGED。
    """
    payload_hash = compute_request_fingerprint(params)

    def _replay(existing: CvGenerationAttempt) -> ApprovalResult:
        return ApprovalResult(
            attempt_id=existing.id,
            reservation_id=existing.reservation_id,
            idempotent_replay=True,
        )

    existing = (await db.execute(
        select(CvGenerationAttempt).where(
            CvGenerationAttempt.client_request_id == client_request_id
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise IdempotencyConflict(
                f"client_request_id={client_request_id} 已绑定其他参数（J01），请使用新的请求 ID"
            )
        return _replay(existing)

    _ensure_not_expired(quote)
    if quote.request_fingerprint != payload_hash:
        raise BudgetError(
            "QUOTE_CHANGED",
            "报价后参数发生变化（素材/台词/时长/分辨率/音频），原确认已失效，请重新报价",
        )
    reservation = await _reserve_with_pool_row(db, quote=quote, created_by=created_by)
    from sqlalchemy import func as _func

    # 同作品同单元的尝试次数递增（重做=第N次；不影响全局 ID/上游ID/费用引用）
    unit_key = str(params.get("unit_key") or "")
    stmt = select(_func.max(CvGenerationAttempt.attempt_no)).where(
        CvGenerationAttempt.production_id == production_id,
    )
    if unit_key:
        stmt = stmt.where(CvGenerationAttempt.params_json["unit_key"].as_string() == unit_key)
    else:
        stmt = stmt.where(CvGenerationAttempt.client_request_id == client_request_id)
    max_no = (await db.execute(stmt)).scalar_one_or_none()
    attempt = CvGenerationAttempt(
        production_id=production_id, generation_unit_id=generation_unit_id,
        attempt_no=int(max_no or 0) + 1, client_request_id=client_request_id, payload_hash=payload_hash,
        params_json=dict(params),  # 计划参数快照：报价与生成同源
        quote_id=quote.id, reservation_id=reservation.id,
        status="APPROVED", created_by=created_by,
    )
    db.add(attempt)
    try:
        await db.flush()
    except IntegrityError:
        # 并发同 client_request_id：唯一约束使后到者失败 → 回滚为重放语义
        await db.rollback()
        winner = (await db.execute(
            select(CvGenerationAttempt).where(
                CvGenerationAttempt.client_request_id == client_request_id
            )
        )).scalar_one_or_none()
        if winner is None:
            raise
        if winner.payload_hash != payload_hash:
            raise IdempotencyConflict(
                f"client_request_id={client_request_id} 已绑定其他参数（J01），请使用新的请求 ID"
            ) from None
        return _replay(winner)
    return ApprovalResult(attempt_id=attempt.id, reservation_id=reservation.id)


async def settle_reservation(
    db: AsyncSession, *, reservation_id: int, actual_amount: Decimal,
) -> None:
    """结算：预留转实扣；真实费用如实入账（可超预留，不截断）。

    只做状态与金额流转，不内部 commit（由调用方事务边界统一提交）；
    池行 FOR UPDATE 防并发结算丢失更新。
    """
    reservation = (await db.execute(
        select(CvBudgetReservation).where(CvBudgetReservation.id == reservation_id)
        .with_for_update()
    )).scalar_one_or_none()
    if reservation is None:
        raise BudgetError("RESERVATION_NOT_FOUND", "预留记录不存在")
    if reservation.status == "settled":
        return  # 幂等：重复结算通知不二次生效
    pool = (await db.execute(
        select(CvBudgetPool).where(CvBudgetPool.id == reservation.pool_id).with_for_update()
    )).scalar_one()
    delta = actual_amount - reservation.amount
    pool.reserved_amount = pool.reserved_amount - reservation.amount
    pool.settled_amount = pool.settled_amount + actual_amount
    reservation.status = "settled"
    if delta > 0:
        # 真实费用超过预留：记录并暂停新任务（§10.3）
        pool.paused = True
    await db.flush()


async def release_reservation(db: AsyncSession, *, reservation_id: int) -> None:
    """取消/失败释放预留（仅未产生上游费用时；结果不明绝不调用）。

    幂等：已 released/settled 的预留直接跳过；池行 FOR UPDATE。
    """
    reservation = (await db.execute(
        select(CvBudgetReservation).where(CvBudgetReservation.id == reservation_id)
        .with_for_update()
    )).scalar_one_or_none()
    if reservation is None or reservation.status != "reserved":
        return
    pool = (await db.execute(
        select(CvBudgetPool).where(CvBudgetPool.id == reservation.pool_id).with_for_update()
    )).scalar_one()
    pool.reserved_amount = pool.reserved_amount - reservation.amount
    reservation.status = "released"
    reservation.released_at = datetime.now(UTC)
    await db.flush()


async def record_usage(
    db: AsyncSession, *, attempt_ref: str, provider: str, model: str,
    amount: Decimal, currency: str, fx_rate: Decimal | None,
    settlement_status: str, provider_task_id: str | None = None,
    usage_meta: dict | None = None, event_key: str = "",
) -> CvUsageLedger:
    """原币账本入账：Decimal 精确存储；人民币折算仅展示（§10.4）。

    event_key 非空时按 (attempt_ref, event_key) 幂等：同一业务事件
    已有行则直接返回既有行，不重复累计（重放/重复轮询安全）。
    """
    if event_key:
        existing = (await db.execute(
            select(CvUsageLedger).where(
                CvUsageLedger.attempt_ref == attempt_ref,
                CvUsageLedger.event_key == event_key,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return existing
    amount_cny = None
    if fx_rate is not None:
        amount_cny = (amount * fx_rate).quantize(Decimal("0.00000001"))
    entry = CvUsageLedger(
        attempt_ref=attempt_ref, provider_id=provider, model_id=model,
        provider_task_id=provider_task_id,
        currency=currency, amount=amount, amount_cny=amount_cny,
        fx_rate=fx_rate, settlement_status=settlement_status,
        event_key=event_key, usage_meta=usage_meta,
    )
    db.add(entry)
    await db.flush()
    return entry
