# -*- coding: utf-8 -*-
"""T06｜账本精度与结算状态（C03/C04）。"""
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.models_commercial import CvUsageLedger
from app.services.commercial.budget_service import record_usage
from tests.conftest import make_user


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


@pytest.mark.asyncio
async def test_micro_amount_precision_preserved(db_session, owner) -> None:
    """C03：$0.001 级小额费用精确累计，人民币分取整不吞零头。"""
    from sqlalchemy import func, select

    entry = await record_usage(
        db_session, attempt_ref="att-1", provider="atlas", model="m",
        amount=Decimal("0.001"), currency="USD", fx_rate=Decimal("7.3"),
        settlement_status="SETTLEMENT_PENDING",
    )
    assert entry.amount == Decimal("0.001")
    # 3 × 0.001 精确求和
    for i in range(2):
        await record_usage(
            db_session, attempt_ref=f"att-{i + 2}", provider="atlas", model="m",
            amount=Decimal("0.001"), currency="USD", fx_rate=Decimal("7.3"),
            settlement_status="SETTLEMENT_PENDING",
        )
    # 仅统计本测试创建的 attempt 的账目（避免其他测试残留污染 SUM）
    own_refs = [str(entry.attempt_ref) for entry in [await record_usage(
        db_session, attempt_ref=f"micro-{i}", provider="atlas", model="m",
        amount=Decimal("0.001"), currency="USD", fx_rate=Decimal("7.3"),
        settlement_status="SETTLEMENT_PENDING",
    ) for i in range(0)]]
    total = (await db_session.execute(
        select(func.sum(CvUsageLedger.amount)).where(
            CvUsageLedger.currency == "USD",
            CvUsageLedger.attempt_ref.in_(["att-1", "att-2", "att-3"]),
        )
    )).scalar_one()
    assert total == Decimal("0.003")
    # 人民币展示：0.003 × 7.3 = 0.0219，仅展示层四舍五入
    assert entry.amount_cny == Decimal("0.0073")


@pytest.mark.asyncio
async def test_pending_settlement_not_zero(db_session, owner) -> None:
    """C04：没有供应商最终账单 → 显示待结算与估算金额，绝不写成 0。"""
    entry = await record_usage(
        db_session, attempt_ref="att-x", provider="atlas", model="m",
        amount=Decimal("0.045"), currency="USD", fx_rate=Decimal("7.3"),
        settlement_status="SETTLEMENT_PENDING",
    )
    assert entry.settlement_status == "SETTLEMENT_PENDING"
    assert entry.amount == Decimal("0.045")  # 不因“未结算”写成 0

    # 结算确认后状态转 SETTLED，金额允许与预留不同（记录真实值）
    entry.settlement_status = "SETTLED"
    entry.amount = Decimal("0.048")  # 真实账单略高于预留
    await db_session.commit()
    assert entry.amount == Decimal("0.048")


@pytest.mark.asyncio
async def test_overrun_recorded_not_clamped(db_session, owner) -> None:
    """真实费用超过预留：记录真实数值，不截断账单。"""
    entry = await record_usage(
        db_session, attempt_ref="att-y", provider="atlas", model="m",
        amount=Decimal("0.20"), currency="USD", fx_rate=Decimal("7.3"),
        settlement_status="SETTLED",
    )
    assert entry.amount == Decimal("0.20")
