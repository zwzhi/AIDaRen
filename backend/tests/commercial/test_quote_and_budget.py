# -*- coding: utf-8 -*-
"""T06｜报价快照绑定、参数变更失效与预算并发（C01/C02）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models_commercial import CvBudgetPool
from app.services.commercial.budget_service import (
    BudgetError,
    approve_and_reserve,
    compute_request_fingerprint,
    request_quote,
)
from tests.conftest import make_user

_PARAMS_A = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [101],
    "product_image_asset_ids": [201],
    "voice_reference_asset_ids": [301],
    "prompt": "达人手持商品讲解",
    "approved_dialogue": "这款精华质地清爽",
    "resolution_id": "720p",
    "duration_ms": 6000,
    "aspect_ratio": "9:16",
    "audio_required": True,
    "params_version": 1,
}


def _quote_response(request):
    import httpx

    return httpx.MockTransport(
        lambda req: httpx.Response(200, json={"amount": "0.09", "currency": "USD", "is_estimate": False})
    )


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


@pytest.mark.asyncio
async def test_quote_binds_full_param_snapshot(db_session, owner) -> None:
    """报价保存完整参数指纹：素材、台词、时长、分辨率、音频全量参与。"""
    quote = await request_quote(
        db_session, params=_PARAMS_A, transport=_quote_response(None), api_key="k",
        base_url="https://api.atlascloud.ai",
    )
    fp = compute_request_fingerprint(_PARAMS_A)
    assert quote.request_fingerprint == fp
    assert quote.estimated_amount == Decimal("0.09")
    # 指纹对关键字段敏感：换任一素材/台词/时长/分辨率都变
    for mutation in (
        {"voice_reference_asset_ids": [302]},
        {"actor_image_asset_ids": [102]},
        {"approved_dialogue": "改过的台词"},
        {"duration_ms": 8000},
        {"resolution_id": "1080p"},
        {"audio_required": False},
    ):
        changed = dict(_PARAMS_A, **mutation)
        assert compute_request_fingerprint(changed) != fp


@pytest.mark.asyncio
async def test_param_change_invalidates_approval(db_session, owner) -> None:
    """C01：报价后更换音色/图片/时长 → 旧确认失效，必须重新报价。"""
    await CvBudgetPool.ensure_default(db_session, total=Decimal("100.00"), created_by=owner.id)
    quote = await request_quote(
        db_session, params=_PARAMS_A, transport=_quote_response(None), api_key="k",
        base_url="https://api.atlascloud.ai",
    )
    changed = dict(_PARAMS_A, voice_reference_asset_ids=[309])
    with pytest.raises(BudgetError) as exc:
        await approve_and_reserve(
            db_session, quote=quote, params=changed,
            client_request_id="req-1", created_by=owner.id,
        )
    assert exc.value.code in {"QUOTE_CHANGED", "QUOTE_EXPIRED"}


@pytest.mark.asyncio
async def test_expired_quote_rejected(db_session, owner) -> None:
    """报价过期（TTL 10 分钟）后批准 → QUOTE_EXPIRED。"""
    await CvBudgetPool.ensure_default(db_session, total=Decimal("100.00"), created_by=owner.id)
    quote = await request_quote(
        db_session, params=_PARAMS_A, transport=_quote_response(None), api_key="k",
        base_url="https://api.atlascloud.ai",
    )
    quote.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(BudgetError) as exc:
        await approve_and_reserve(
            db_session, quote=quote, params=_PARAMS_A,
            client_request_id="req-2", created_by=owner.id,
        )
    assert exc.value.code == "QUOTE_EXPIRED"


@pytest.mark.asyncio
async def test_budget_cannot_oversubscribe_sequential(db_session, owner) -> None:
    """预算不足直接拒绝：可用预算 = 总额 - 已结算 - 有效预留。"""
    await CvBudgetPool.ensure_default(db_session, total=Decimal("0.05"), created_by=owner.id)
    quote = await request_quote(
        db_session, params=_PARAMS_A, transport=_quote_response(None), api_key="k",
        base_url="https://api.atlascloud.ai",
    )
    with pytest.raises(BudgetError) as exc:
        await approve_and_reserve(
            db_session, quote=quote, params=_PARAMS_A,
            client_request_id="req-3", created_by=owner.id,
        )
    assert exc.value.code == "BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_concurrent_reservations_never_oversubscribe(db_session, owner) -> None:
    """C02：两个并发请求争同一预算 → 条件更新保证总额不被突破。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text as sql_text

    from app.config import get_settings
    from app.database import Base
    import app.models_commercial  # noqa: F401
    from sqlalchemy.engine import make_url
    from app.services.commercial.budget_service import reserve_budget_atomic

    raw = get_settings().database_url
    test_url = make_url(raw).set(database=(make_url(raw).database or "x") + "_test").render_as_string(hide_password=False)
    engine = create_async_engine(test_url)
    import uuid as _uuid

    temp_email = f"budget-conc-{_uuid.uuid4().hex[:10]}@test.local"
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from app.models import User as _User

    async with engine.begin() as conn:
        # 持久测试库旧结构的 quote_id NOT NULL 约束随模型放宽（幂等执行）
        await conn.execute(sql_text(
            "ALTER TABLE cv_budget_reservations ALTER COLUMN quote_id DROP NOT NULL"
        ))
        await conn.run_sync(Base.metadata.create_all)
    async with _AsyncSession(engine) as s:
        temp_user = _User(email=temp_email, hashed_password="test")
        s.add(temp_user)
        await s.flush()
        conc_owner = int(temp_user.id)
        await s.execute(sql_text("DELETE FROM cv_budget_reservations WHERE pool_id IN (SELECT id FROM cv_budget_pools WHERE name='concurrency-test')"))
        await s.execute(sql_text("DELETE FROM cv_budget_pools WHERE name='concurrency-test'"))
        await s.execute(sql_text(
            "INSERT INTO cv_budget_pools (name, currency, total_amount, reserved_amount, settled_amount, paused, created_by) "
            "VALUES ('concurrency-test', 'USD', 1.00, 0, 0, false, :owner)"
        ), {"owner": conc_owner})
        await s.commit()

    amount = Decimal("0.80")  # 两个 0.80 只能成功一个
    import asyncio

    async def _try_reserve(tag: str):
        return await reserve_budget_atomic(
            engine, amount=amount, owner_id=int(conc_owner), tag=tag, pool_name="concurrency-test",
        )

    results = await asyncio.gather(_try_reserve("a"), _try_reserve("b"), return_exceptions=True)
    successes = [r for r in results if isinstance(r, dict) and r.get("ok")]
    failures = [r for r in results if isinstance(r, BudgetError)]
    assert len(successes) == 1, f"并发预留应有且仅有一个成功：{results}"
    assert len(failures) == 1 and failures[0].code == "BUDGET_EXCEEDED"
    async with engine.begin() as conn:  # 清理本次测试数据
        await conn.execute(sql_text("DELETE FROM cv_budget_reservations WHERE pool_id IN (SELECT id FROM cv_budget_pools WHERE name='concurrency-test')"))
        await conn.execute(sql_text("DELETE FROM cv_budget_pools WHERE name='concurrency-test'"))
        await conn.execute(sql_text("DELETE FROM users WHERE email = :email"), {"email": temp_email})
    await engine.dispose()
