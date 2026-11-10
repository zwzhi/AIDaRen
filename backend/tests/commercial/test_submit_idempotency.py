# -*- coding: utf-8 -*-
"""T06｜提交幂等（J01）：同 ID 同参返回原任务，异参 409。"""
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.models_commercial import CvBudgetPool
from app.services.commercial.budget_service import (
    IdempotencyConflict,
    approve_and_reserve,
    request_quote,
)
from tests.conftest import make_user

_PARAMS = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [101], "product_image_asset_ids": [201],
    "voice_reference_asset_ids": [301],
    "approved_dialogue": "台词内容保持一致",
    "resolution_id": "720p", "duration_ms": 6000, "aspect_ratio": "9:16",
    "audio_required": True, "params_version": 1,
}


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


async def _quote(db, transport):
    return await request_quote(
        db, params=_PARAMS, transport=transport, api_key="k",
        base_url="https://api.atlascloud.ai",
    )


def _transport():
    import httpx

    return httpx.MockTransport(
        lambda req: httpx.Response(200, json={"amount": "0.05", "currency": "USD"})
    )


@pytest.mark.asyncio
async def test_same_request_returns_same_attempt(db_session, owner) -> None:
    """双击/重复 POST：同 client_request_id + 同参数 → 同一 attempt。"""
    await CvBudgetPool.ensure_default(db_session, total=Decimal("10.00"), created_by=owner.id)
    quote = await _quote(db_session, _transport())

    first = await approve_and_reserve(
        db_session, quote=quote, params=_PARAMS,
        client_request_id="click-001", created_by=owner.id,
    )
    second = await approve_and_reserve(
        db_session, quote=quote, params=_PARAMS,
        client_request_id="click-001", created_by=owner.id,
    )
    assert first.attempt_id == second.attempt_id
    assert second.idempotent_replay is True  # 标识：没有新扣预算


@pytest.mark.asyncio
async def test_same_id_different_params_conflict(db_session, owner) -> None:
    """同 ID 不同参数 → 409 语义冲突，不创建新任务。"""
    await CvBudgetPool.ensure_default(db_session, total=Decimal("10.00"), created_by=owner.id)
    quote = await _quote(db_session, _transport())
    await approve_and_reserve(
        db_session, quote=quote, params=_PARAMS,
        client_request_id="click-002", created_by=owner.id,
    )
    changed = dict(_PARAMS, duration_ms=8000)
    with pytest.raises(IdempotencyConflict):
        await approve_and_reserve(
            db_session, quote=quote, params=changed,
            client_request_id="click-002", created_by=owner.id,
        )


@pytest.mark.asyncio
async def test_budget_reserved_once_on_replay(db_session, owner) -> None:
    """重放不重复占用预算：预留总额不变。"""
    from sqlalchemy import func, select

    from app.models_commercial import CvBudgetReservation

    await CvBudgetPool.ensure_default(db_session, total=Decimal("10.00"), created_by=owner.id)
    quote = await _quote(db_session, _transport())
    await approve_and_reserve(
        db_session, quote=quote, params=_PARAMS,
        client_request_id="click-003", created_by=owner.id,
    )
    await approve_and_reserve(
        db_session, quote=quote, params=_PARAMS,
        client_request_id="click-003", created_by=owner.id,
    )
    reserved = (await db_session.execute(
        select(func.count()).select_from(CvBudgetReservation)
    )).scalar_one()
    assert reserved == 1
