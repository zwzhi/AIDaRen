# -*- coding: utf-8 -*-
"""P1-2/P1-5｜幂等入账与预算生命周期（J01/C03/C04 修复回归）。

核心断言：
- 重放返回原 attempt 且复用原任务：不建新 TaskRun、不重复驱动、账本不重复；
- 未提交的失败/取消释放预留；SUBMIT_UNKNOWN/上游失败/费用不明不释放；
- 上游返回可核实费用 → 预留转结算、账本行转 SETTLED（金额=实收）；
- 无可核实费用 → 保持 SETTLEMENT_PENDING（金额=估算，绝不写 0）；
- 同一 attempt 重复轮询不重复入账（账本事件唯一）；
- 并发同 ID 请求只产生一份 attempt/预留；
- 提交 200 无 ID → SUBMIT_UNKNOWN（P2-3，不得当明确失败）。
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import config
from tests.conftest import make_user
from tests.commercial.fake_atlas import fake_atlas, complete_prediction_body  # noqa: F401

_TEST_DB = "postgresql+asyncpg://printfilm:printfilm-local-dev@127.0.0.1:15432/printfilm_test"


# ---------------------------------------------------------------- 夹具（隔离引擎 + 真实提交行）

@pytest_asyncio.fixture
async def env(fake_atlas, tmp_path, monkeypatch):
    from app.database import Base
    import app.models  # noqa: F401
    import app.models_commercial  # noqa: F401
    import app.models_tasks  # noqa: F401
    import app.models_teams  # noqa: F401
    import app.services.providers.atlas.media as atlas_media

    for name, value in {
        "COMMERCIAL_MOCK_MODE": "false",
        "COMMERCIAL_ENABLED": "true",
        "COMMERCIAL_PAID_EXECUTION_ENABLED": "true",
        "ATLAS_API_KEY": "atlas-test-key-do-not-leak",
        "GEMINI_ANALYSIS_MODEL_ID": "gemini-3-flash-preview",
        "H3_DEVELOPER_REFERENCE_MODEL_ID": "minimax-h3-developer-reference",
        "COMMERCIAL_VERIFIED_MODELS": "gemini-3-flash-preview,minimax-h3-developer-reference",
        "ATLAS_BASE_URL": fake_atlas.state.base_url,
        "COMMERCIAL_STORAGE_ROOT": str(tmp_path / "commercial"),
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()

    async def _direct_fetch(url: str, dest, *, transport=None):
        from urllib.parse import urlparse

        path = urlparse(url).path or "/files/fake-output.mp4"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{fake_atlas.state.base_url}{path}")
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest

    monkeypatch.setattr(atlas_media, "fetch_url_to_file", _direct_fetch)

    engine = create_async_engine(_TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from app.commercial_schema import apply_commercial_schema_patches
        await apply_commercial_schema_patches(conn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = uuid.uuid4().hex[:8]

    # poller / generation 内部会话工厂也指向隔离引擎（否则连到业务库）
    import app.database as database_mod
    from app.services.tasks import poller as poller_mod

    monkeypatch.setattr(database_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(poller_mod, "AsyncSessionLocal", factory)

    yield {"factory": factory, "marker": marker}

    async with factory() as db:
        await db.execute(text(
            "DELETE FROM cv_usage_ledger WHERE attempt_ref IN "
            "(SELECT CAST(id AS TEXT) FROM cv_generation_attempts WHERE client_request_id LIKE :p)"),
            {"p": f"bl-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_provider_media_handles WHERE asset_id IN "
            "(SELECT id FROM cv_media_assets WHERE object_key LIKE :p)"), {"p": f"bl/{marker}%"})
        await db.execute(text(
            "DELETE FROM task_runs WHERE payload->>'attempt_id' IN "
            "(SELECT CAST(id AS TEXT) FROM cv_generation_attempts WHERE client_request_id LIKE :p)"),
            {"p": f"bl-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_generation_attempts WHERE client_request_id LIKE :p"), {"p": f"bl-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_budget_reservations WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"bl-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_budget_pools WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"bl-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_media_assets WHERE object_key LIKE :p"), {"p": f"bl/{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_cost_quotes WHERE quote_key LIKE :p"), {"p": f"bl-{marker}%"})
        await db.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"bl-{marker}%"})
        await db.commit()
    await engine.dispose()
    config.get_settings.cache_clear()


async def _mk_user(env) -> int:
    from app.models import User

    async with env["factory"]() as db:
        user = User(email=f"bl-{env['marker']}-{secrets.token_hex(3)}@test.local",
                    hashed_password="x")
        db.add(user)
        await db.commit()
        return user.id


_PARAMS = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [], "product_image_asset_ids": [],
    "voice_reference_asset_ids": [], "scene_image_asset_ids": [],
    "prompt": "p", "approved_dialogue": "d",
    "resolution_id": "768p", "duration_ms": 5000, "aspect_ratio": "9:16",
    "audio_required": False, "unit_key": "U001", "params_version": 1,
}


async def _mk_quote_attempt(env, user_id: int, *, amount=Decimal("0.10")):
    """独立会话内提交一套 池/预留/报价/attempt（复用 approve_and_reserve 真路径）。"""
    from app.models_commercial import (
        CvBudgetPool, CvCostQuote, CvGenerationAttempt,
    )
    from app.services.commercial.budget_service import approve_and_reserve, compute_request_fingerprint

    async with env["factory"]() as db:
        pool = CvBudgetPool(name="default", scope="real",
                            total_amount=Decimal("10"), created_by=user_id)
        db.add(pool)
        await db.flush()
        quote = CvCostQuote(quote_key=f"bl-{env['marker']}-q{secrets.token_hex(3)}",
                            model_id="m", request_fingerprint=compute_request_fingerprint(_PARAMS),
                            resolution_id="768p", requested_duration_ms=5000,
                            currency="USD", estimated_amount=amount)
        db.add(quote)
        await db.flush()
        request_id = f"bl-{env['marker']}-{secrets.token_hex(4)}"
        approval = await approve_and_reserve(
            db, quote=quote, params=_PARAMS, client_request_id=request_id,
            created_by=user_id, production_id=None,
        )
        await db.commit()
        return {"attempt_id": approval.attempt_id, "reservation_id": approval.reservation_id,
                "pool_id": pool.id, "request_id": request_id, "quote_id": quote.id}


async def _pool_state(env, pool_id: int) -> dict:
    from app.models_commercial import CvBudgetPool

    async with env["factory"]() as db:
        pool = await db.get(CvBudgetPool, pool_id)
        return {"reserved": pool.reserved_amount, "settled": pool.settled_amount,
                "paused": pool.paused}


async def _ledger(env, attempt_id: int) -> list[dict]:
    async with env["factory"]() as db:
        rows = (await db.execute(text(
            "SELECT amount, currency, settlement_status, event_key FROM cv_usage_ledger "
            "WHERE attempt_ref = :a ORDER BY id"), {"a": str(attempt_id)})).mappings().all()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- 幂等重放（P1-2）

@pytest.mark.asyncio
async def test_replay_returns_same_attempt_and_task_no_double_charge(env):
    """同 client_request_id 重放：同一 attempt、同一 TaskRun、账本恰好一行。"""
    from app.models_tasks import TaskRun
    from app.services.commercial.budget_service import approve_and_reserve
    from app.models_commercial import CvCostQuote

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    async with env["factory"]() as db:
        task = TaskRun(domain="commercial", task_type="video_generate", queue_type="video",
                       status="succeeded", requested_by=user_id,
                       payload={"attempt_id": seeded["attempt_id"]},
                       next_action_at=datetime.now(UTC))
        db.add(task)
        await db.commit()
        task_id = task.id
        quote = await db.get(CvCostQuote, seeded["quote_id"])

        replay = await approve_and_reserve(
            db, quote=quote, params=_PARAMS, client_request_id=seeded["request_id"],
            created_by=user_id, production_id=None,
        )
        await db.commit()
        assert replay.idempotent_replay is True
        assert replay.attempt_id == seeded["attempt_id"]
    # API 层语义（productions.generate_unit）在 e2e 文件锁定；此处锁定服务层

    from app.services.commercial.generation import poll_attempt
    from app.models_commercial import CvGenerationAttempt

    async with env["factory"]() as db:
        attempt = await db.get(CvGenerationAttempt, seeded["attempt_id"])
        attempt.provider_prediction_id = f"MOCK-pred-{secrets.token_hex(4)}"
        attempt.params_json = dict(_PARAMS)
        await db.commit()
        # 同一 attempt 连续两次轮询（重放驱动场景）：账本不得重复
        await poll_attempt(attempt, db=db, base_url="x", api_key="")
        await poll_attempt(attempt, db=db, base_url="x", api_key="")
    rows = await _ledger(env, seeded["attempt_id"])
    keys = [r["event_key"] for r in rows]
    assert keys.count("generation.pending") <= 1, f"重复入账: {rows}"


@pytest.mark.asyncio
async def test_concurrent_same_request_single_attempt(env):
    """并发同 ID：唯一约束 + 冲突回收 → 只有一份 attempt/预留。"""
    import asyncio

    from app.models_commercial import CvCostQuote
    from app.services.commercial.budget_service import approve_and_reserve

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)  # 已有一份（含独立池）
    async with env["factory"]() as db:
        quote = await db.get(CvCostQuote, seeded["quote_id"])
        results = await asyncio.gather(
            approve_and_reserve(db, quote=quote, params=_PARAMS,
                                client_request_id=seeded["request_id"],
                                created_by=user_id, production_id=None),
            approve_and_reserve(db, quote=quote, params=_PARAMS,
                                client_request_id=seeded["request_id"],
                                created_by=user_id, production_id=None),
            return_exceptions=True,
        )
        await db.commit()
    async with env["factory"]() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM cv_generation_attempts WHERE client_request_id = :c"),
            {"c": seeded["request_id"]})).scalar_one()
        assert n == 1, f"并发重放产生了 {n} 份 attempt"
        ok = [r for r in results if not isinstance(r, Exception)]
        assert len(ok) == 2 and all(r.attempt_id == seeded["attempt_id"] for r in ok)


# ---------------------------------------------------------------- 释放/结算语义（P1-5）

@pytest.mark.asyncio
async def test_unsubmitted_failure_releases_reservation(env):
    """明确失败（未送达上游）：预留释放，池可用额度恢复。"""
    from app.models_commercial import CvGenerationAttempt
    from app.services.commercial import generation as gen

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    before = await _pool_state(env, seeded["pool_id"])
    assert before["reserved"] == Decimal("0.10")
    async with env["factory"]() as db:
        attempt = await db.get(CvGenerationAttempt, seeded["attempt_id"])
        attempt.params_json = {"bad": "params"}  # 触发 PLAN 快照校验失败（未提交）
        await db.commit()

        class _T:
            id = 0
            payload = {"attempt_id": seeded["attempt_id"]}
            cancel_requested = False
            provider_task_id = None

        result = await gen.execute_generation_task(_T(), db=db, base_url="x", api_key="k")
        assert result and result.get("failed")
    after = await _pool_state(env, seeded["pool_id"])
    assert after["reserved"] == Decimal("0"), "未提交的失败必须释放预留"


@pytest.mark.asyncio
async def test_cancel_before_submit_releases_reservation(env):
    from app.models_commercial import CvGenerationAttempt
    from app.services.commercial import generation as gen

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    async with env["factory"]() as db:
        class _T:
            id = 0
            payload = {"attempt_id": seeded["attempt_id"]}
            cancel_requested = True
            provider_task_id = None

        result = await gen.execute_generation_task(_T(), db=db, base_url="x", api_key="k")
        assert result.get("cancelled")
    after = await _pool_state(env, seeded["pool_id"])
    assert after["reserved"] == Decimal("0"), "提交前取消必须释放预留"


@pytest.mark.asyncio
async def test_submit_unknown_keeps_reservation(env, monkeypatch):
    import app.services.commercial.generation as gen

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    async with env["factory"]() as db:
        from app.models_commercial import CvGenerationAttempt

        attempt = await db.get(CvGenerationAttempt, seeded["attempt_id"])
        attempt.params_json = dict(_PARAMS)
        attempt.params_json["voice_reference_asset_ids"] = []
        await db.commit()

        async def _broken(*a, **k):
            raise httpx.ConnectError("network gone")

        monkeypatch.setattr(gen, "submit_generation", _broken)

        class _T:
            id = 0
            payload = {"attempt_id": seeded["attempt_id"]}
            cancel_requested = False
            provider_task_id = None

        result = await gen.execute_generation_task(_T(), db=db, base_url="x", api_key="k")
        assert result.get("failed")
        await db.refresh(attempt)
        assert attempt.status == "SUBMIT_UNKNOWN"
    after = await _pool_state(env, seeded["pool_id"])
    assert after["reserved"] == Decimal("0.10"), "结果不明不得当作免费释放"


@pytest.mark.asyncio
async def test_http200_without_id_is_submit_unknown(env, fake_atlas):
    """200 但无任务 ID：结果不明（上游可能已建任务），不得判明确失败（P2-3）。"""
    from app.services.providers.atlas.h3_reference import submit_generation

    fake_atlas.state.generate_response = {"data": {"ok": True}}  # 无 id
    try:
        with pytest.raises(Exception) as ei:
            await submit_generation({"model": "m"}, base_url=fake_atlas.state.base_url,
                                    api_key="k")
        assert type(ei.value).__name__ == "SubmitOutcomeUnknownError", \
            f"应为 SubmitOutcomeUnknownError，实际 {type(ei.value).__name__}"
    finally:
        fake_atlas.state.generate_response = None


@pytest.mark.asyncio
async def test_success_with_cost_settles(env, fake_atlas):
    """上游返回可核实费用：预留转结算，账本行 SETTLED 且金额=实收。"""
    from app.models_commercial import CvGenerationAttempt
    from app.services.tasks.poller import _select_and_poll_due
    from app.models_tasks import TaskRun

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    pred = f"pred-{secrets.token_hex(4)}"
    async with env["factory"]() as db:
        attempt = await db.get(CvGenerationAttempt, seeded["attempt_id"])
        attempt.provider_prediction_id = pred
        attempt.status = "PROVIDER_RUNNING"
        await db.flush()
        task = TaskRun(domain="commercial", task_type="video_generate", queue_type="video",
                       status="awaiting_poll", requested_by=user_id,
                       payload={"attempt_id": seeded["attempt_id"]},
                       provider_task_id=pred,
                       next_action_at=datetime.now(UTC) - timedelta(seconds=1))
        db.add(task)
        await db.commit()
    fake_atlas.state.prediction_script[pred] = [
        complete_prediction_body(amount=0.12),  # 实收 $0.12 ≠ 估算 $0.10
    ]
    await _select_and_poll_due()
    state = await _pool_state(env, seeded["pool_id"])
    assert state["reserved"] == Decimal("0"), "结算后预留应清零"
    assert state["settled"] == Decimal("0.12"), "结算金额应为上游实收"
    rows = await _ledger(env, seeded["attempt_id"])
    assert any(r["settlement_status"] == "SETTLED" and r["amount"] == Decimal("0.12")
               for r in rows), rows


@pytest.mark.asyncio
async def test_success_without_cost_stays_pending(env, fake_atlas):
    """上游无费用信息：账本保持 SETTLEMENT_PENDING（估算金额），预留保留。"""
    from app.models_commercial import CvGenerationAttempt
    from app.models_tasks import TaskRun
    from app.services.tasks.poller import _select_and_poll_due

    user_id = await _mk_user(env)
    seeded = await _mk_quote_attempt(env, user_id)
    pred = f"pred-{secrets.token_hex(4)}"
    async with env["factory"]() as db:
        attempt = await db.get(CvGenerationAttempt, seeded["attempt_id"])
        attempt.provider_prediction_id = pred
        attempt.status = "PROVIDER_RUNNING"
        await db.flush()
        db.add(TaskRun(domain="commercial", task_type="video_generate", queue_type="video",
                       status="awaiting_poll", requested_by=user_id,
                       payload={"attempt_id": seeded["attempt_id"]},
                       provider_task_id=pred,
                       next_action_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    fake_atlas.state.prediction_script[pred] = [
        complete_prediction_body(amount=None),  # 无费用字段
    ]
    await _select_and_poll_due()
    rows = await _ledger(env, seeded["attempt_id"])
    assert len(rows) == 1 and rows[0]["settlement_status"] == "SETTLEMENT_PENDING"
    assert rows[0]["amount"] == Decimal("0.10"), "无账单时保持估算金额，不写 0"
    state = await _pool_state(env, seeded["pool_id"])
    assert state["reserved"] == Decimal("0.10"), "费用未核实前预留保留"
