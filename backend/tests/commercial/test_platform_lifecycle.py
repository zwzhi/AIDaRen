# -*- coding: utf-8 -*-
"""P1-4｜commercial 任务平台生命周期（真实调度/执行/轮询链，离线）。

覆盖（§三）：
- API 建任务即带到期 next_action_at（调度器可认领）；
- executor 真实执行 → 提交 Fake Atlas → 任务行进入 awaiting_poll 且带
  provider_task_id / 到期时间 / 清租约（修复前卡 running、永不轮询）；
- 轮询 → 下载 → GENERATED → 任务 succeeded；
- 重启恢复（已有上游 ID）只查询不重新提交；
- SUBMIT_UNKNOWN 冻结：重跑不二次提交；
- 查询 429 / 下载失败：退避重试，不重新生成。

外部 HTTP 全部指向本地 Fake Atlas（回环）；数据库为隔离测试库。
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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import config
from tests.conftest import make_user
from tests.commercial.fake_atlas import fake_atlas, complete_prediction_body  # noqa: F401

_TEST_DB = "postgresql+asyncpg://printfilm:printfilm-local-dev@127.0.0.1:15432/printfilm_test"


@pytest_asyncio.fixture
async def platform(fake_atlas, tmp_path, monkeypatch):
    """隔离引擎 + 替换 executor/poller/scheduler/handler 的会话工厂。

    下载边界说明：生产 SSRF 策略禁止回环地址，属正确行为（有独立测试锁定）。
    本文件聚焦调度/持久化生命周期，下载经依赖注入直连 Fake Atlas，
    不绕过任何调度与账务逻辑。
    """
    from app.database import Base
    import app.models  # noqa: F401
    import app.models_commercial  # noqa: F401
    import app.models_tasks  # noqa: F401
    import app.models_teams  # noqa: F401
    import app.services.providers.atlas.media as atlas_media
    from app.services.tasks import executor as executor_mod
    from app.services.tasks import poller as poller_mod
    from app.services.tasks import scheduler as scheduler_mod

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
        # 历史残留任务不占满本文件的调度容量（共享测试库可能有余留行）
        "TASK_QUEUE_VIDEO_CONCURRENCY": "16",
        "TASK_USER_MAX_CONCURRENCY": "16",
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()

    async def _direct_fetch(url: str, dest, *, transport=None):
        """下载垫片：上游声明的 https 输出地址 → 本地 Fake Atlas。

        生产的 SSRF 策略禁止回环/私网下载（正确行为，另有单测锁定），
        此处仅在测试内做地址映射，不触及任何调度与账务逻辑。
        """
        from urllib.parse import urlparse

        path = urlparse(url).path or "/files/fake-output.mp4"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(f"{fake_atlas.state.base_url}{path}")
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest

    monkeypatch.setattr(atlas_media, "fetch_url_to_file", _direct_fetch)

    engine = create_async_engine(_TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.database as database_mod
    monkeypatch.setattr(database_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(executor_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(poller_mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(scheduler_mod, "AsyncSessionLocal", factory)

    marker = uuid.uuid4().hex[:8]
    yield {"factory": factory, "marker": marker, "tmp": tmp_path}

    async with factory() as db:
        await db.execute(text(
            "DELETE FROM cv_usage_ledger WHERE attempt_ref IN "
            "(SELECT CAST(id AS TEXT) FROM cv_generation_attempts WHERE client_request_id LIKE :p)"),
            {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_provider_media_handles WHERE asset_id IN "
            "(SELECT id FROM cv_media_assets WHERE object_key LIKE :p)"), {"p": f"plc/{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_generation_attempts WHERE client_request_id LIKE :p"), {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM task_runs WHERE requested_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_productions WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"plc-{marker}%"})
        for child, col, parent in (
            ("cv_template_versions", "template_id", "cv_templates"),
            ("cv_actor_versions", "actor_id", "cv_actors"),
            ("cv_voice_profiles", "actor_id", "cv_actors"),
            ("cv_product_versions", "product_id", "cv_products"),
        ):
            await db.execute(text(
                f"DELETE FROM {child} WHERE {col} IN "
                f"(SELECT id FROM {parent} WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p))"),
                {"p": f"plc-{marker}%"})
        for table in ("cv_templates", "cv_actors", "cv_products"):
            await db.execute(text(
                f"DELETE FROM {table} WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
                {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_cost_quotes WHERE quote_key LIKE :p"), {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_media_assets WHERE object_key LIKE :p"), {"p": f"plc/{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_budget_reservations WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM cv_budget_pools WHERE created_by IN (SELECT id FROM users WHERE email LIKE :p)"),
            {"p": f"plc-{marker}%"})
        await db.execute(text(
            "DELETE FROM users WHERE email LIKE :p"), {"p": f"plc-{marker}%"})
        await db.commit()
    await engine.dispose()
    config.get_settings.cache_clear()


async def _seed(platform, *, with_prediction: str | None = None,
                task_status: str = "pending", next_action_at: datetime | None = None):
    """落库一套 attempt+task（真实提交参数；素材文件写入隔离存储根）。"""
    from app.models import User
    from app.models_commercial import CvCostQuote, CvGenerationAttempt, CvMediaAsset
    from app.models_tasks import TaskRun
    from app.services.commercial.storage import asset_disk_path

    marker = platform["marker"]
    async with platform["factory"]() as db:
        user = User(email=f"plc-{marker}-{secrets.token_hex(3)}@test.local",
                    hashed_password="x")
        db.add(user)
        await db.flush()

        def _asset(role: str, mime: str, kind: str) -> CvMediaAsset:
            key = f"plc/{marker}/{role}/{secrets.token_hex(6)}.bin"
            row = CvMediaAsset(kind=kind, object_key=key, sha256=secrets.token_hex(16),
                               mime=mime, size_bytes=16, source_role=role, uploaded_by=user.id)
            db.add(row)
            return row

        actor, product, voice = (_asset("owned_actor_image", "image/png", "image"),
                                 _asset("owned_product_image", "image/png", "image"),
                                 _asset("owned_voice_reference", "audio/mpeg", "audio"))
        await db.flush()
        for row in (actor, product, voice):
            path = asset_disk_path(row.object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"TESTBYTES-0123456789")

        quote = CvCostQuote(quote_key=f"plc-{marker}-q{secrets.token_hex(3)}",
                            model_id="minimax-h3-developer-reference",
                            request_fingerprint="f" * 64, resolution_id="768p",
                            requested_duration_ms=5000, currency="USD",
                            estimated_amount=Decimal("0.075"))
        db.add(quote)
        await db.flush()
        attempt = CvGenerationAttempt(
            production_id=None, attempt_no=1,
            client_request_id=f"plc-{marker}-{secrets.token_hex(4)}",
            payload_hash="f" * 64,
            params_json={
                "model_id": "minimax-h3-developer-reference",
                "actor_image_asset_ids": [actor.id], "product_image_asset_ids": [product.id],
                "voice_reference_asset_ids": [voice.id],
                "prompt": "达人手持商品讲解", "approved_dialogue": "测试台词",
                "resolution_id": "768p", "duration_ms": 5000, "aspect_ratio": "9:16",
                "audio_required": True, "unit_key": "U001", "params_version": 1,
            },
            quote_id=quote.id, status="APPROVED",
            provider_prediction_id=with_prediction,
            created_by=user.id,
        )
        db.add(attempt)
        await db.flush()
        task = TaskRun(
            domain="commercial", task_type="video_generate", queue_type="video",
            status=task_status, requested_by=user.id,
            payload={"attempt_id": attempt.id},
            provider_task_id=with_prediction, next_action_at=next_action_at,
        )
        db.add(task)
        await db.commit()
        return {"user_id": user.id, "attempt_id": attempt.id, "task_id": task.id}


async def _due(platform, task_id: int) -> None:
    """把任务 next_action_at 拨到过去（模拟退避到期）。"""
    from app.models_tasks import TaskRun

    async with platform["factory"]() as db:
        row = await db.get(TaskRun, task_id)
        row.next_action_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()


async def _rows(platform, task_id: int, attempt_id: int) -> dict:
    from app.models_tasks import TaskRun
    from app.models_commercial import CvGenerationAttempt

    async with platform["factory"]() as db:
        task = await db.get(TaskRun, task_id)
        attempt = await db.get(CvGenerationAttempt, attempt_id)
        return {"task": task, "attempt": attempt}


def _generate_calls(app) -> int:
    return len([r for r in app.state.requests if r[0] == "generateVideo"])


# ---------------------------------------------------------------- 生命周期主线

@pytest.mark.asyncio
async def test_executor_sets_awaiting_poll_and_poller_completes(platform, fake_atlas):
    """排队→执行→提交→awaiting_poll（带到期时间/上游ID/清租约）→轮询→下载→完成。"""
    from app.services.tasks.executor import execute_task_run
    from app.services.tasks.poller import _select_and_poll_due

    seeded = await _seed(platform, next_action_at=datetime.now(UTC))
    await execute_task_run(seeded["task_id"])
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    task, attempt = rows["task"], rows["attempt"]

    # 修复点 1：任务行必须进入 awaiting_poll（而非停留 running）
    assert task.status == "awaiting_poll", f"任务卡在 {task.status}，轮询器永远无法接管"
    # 修复点 2：上游任务号落到任务行 + 安排下一次轮询 + 释放租约
    assert task.provider_task_id == attempt.provider_prediction_id
    assert task.provider_task_id and task.provider_task_id.startswith("pred-")
    assert task.next_action_at is not None, "next_action_at 为空不会被 _select_and_poll_due 选中"
    assert task.lease_until is None and task.lease_token is None
    assert attempt.status == "PROVIDER_RUNNING"
    pred_id = task.provider_task_id

    # 轮询收尾：processing →（退避到期）→ completed(带输出与费用)
    fake_atlas.state.prediction_script[pred_id] = [
        {"status": "processing"},
        complete_prediction_body(amount=0.075),
    ]
    await _due(platform, seeded["task_id"])
    await _select_and_poll_due()
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["task"].status == "awaiting_poll", "processing 应退避续查而非终态"
    await _due(platform, seeded["task_id"])
    await _select_and_poll_due()
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    task, attempt = rows["task"], rows["attempt"]
    assert attempt.status == "GENERATED"
    assert attempt.output_asset_key, "输出应已下载归档"
    assert task.status == "succeeded" and task.finished_at is not None

    # 幂等：任务已终态，再次轮询不产生新的上游查询
    before = len([r for r in fake_atlas.state.requests if r[0] == "prediction"])
    await _select_and_poll_due()
    after = len([r for r in fake_atlas.state.requests if r[0] == "prediction"])
    assert after == before


@pytest.mark.asyncio
async def test_scheduler_claims_pending_commercial_task(platform, fake_atlas):
    """真实调度器认领链：pending（next_action_at 到期）→ 认领执行 → awaiting_poll。"""
    from app.services.tasks import scheduler as scheduler_mod

    seeded = await _seed(platform, next_action_at=datetime.now(UTC))
    await scheduler_mod._claim_queue("video", datetime.now(UTC))
    jobs = [j for j in scheduler_mod._running_jobs.values() if not j.done()]
    if jobs:
        import asyncio

        await asyncio.wait(jobs, timeout=60)
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["task"].status == "awaiting_poll", \
        f"调度器执行后任务应进入 awaiting_poll，实际 {rows['task'].status}"
    assert _generate_calls(fake_atlas) == 1


@pytest.mark.asyncio
async def test_api_created_task_has_due_next_action(platform, fake_atlas, monkeypatch):
    """API 建的 TaskRun 必须带到期 next_action_at（否则调度器永不认领）。"""
    monkeypatch.setenv("COMMERCIAL_MOCK_MODE", "true")  # 走 Mock 驱动路径建任务即可验证
    config.get_settings.cache_clear()
    from app.database import get_db
    from app.deps import get_current_user
    from app.api.commercial import router as commercial_router
    from app.models import User
    from app.models_commercial import CvBudgetPool
    from app.models_tasks import TaskRun
    from sqlalchemy import select

    marker = platform["marker"]

    async def _pool_snapshot():
        from sqlalchemy import text as _text

        async with platform["factory"]() as s:
            return (await s.execute(_text(
                "SELECT id, total_amount, reserved_amount, settled_amount, paused "
                "FROM cv_budget_pools WHERE name='default' AND scope='mock'"
            ))).mappings().first()

    snapshot = await _pool_snapshot()
    try:
        async with platform["factory"]() as db:
            admin = User(email=f"plc-{marker}-api@test.local", hashed_password="x", role="admin")
            db.add(admin)
            await db.flush()
            await CvBudgetPool.ensure_default(db, total=Decimal("50"), created_by=admin.id)
            production = await _mock_production(db, admin.id, key_prefix=f"{marker}-api")
            await db.commit()
            admin_id, pid = admin.id, production.id

            app = FastAPI()
            app.include_router(commercial_router, prefix="/api/commercial")

            async def override_db():
                yield db

            async def override_user():
                return await db.get(User, admin_id, populate_existing=True)

            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_user] = override_user
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                quote = (await c.post(f"/api/commercial/productions/{pid}/quote",
                                      json={"unit_key": "U001"})).json()
                resp = await c.post(f"/api/commercial/productions/{pid}/generate", json={
                    "unit_key": "U001", "quote_id": quote["quote_id"],
                    "client_request_id": f"plc-{marker}-api1", "drive": False,
                })
                assert resp.status_code == 202, resp.text
            task_id = resp.json()["task_id"]
            row = await db.get(TaskRun, task_id)
            assert row.next_action_at is not None, \
                "generate 建任务未设置 next_action_at，调度器（要求非空且到期）永不认领"
    finally:
        # 共享 default mock 池快照恢复：先删本测试的 attempt/预留，再还原池
        from sqlalchemy import text as _text

        async with platform["factory"]() as s:
            await s.execute(_text(
                "DELETE FROM cv_generation_attempts WHERE client_request_id LIKE :p"),
                {"p": f"plc-{marker}%"})
            await s.execute(_text(
                "DELETE FROM cv_budget_reservations WHERE created_by IN "
                "(SELECT id FROM users WHERE email LIKE :p)"), {"p": f"plc-{marker}%"})
            if snapshot is None:
                await s.execute(_text(
                    "DELETE FROM cv_budget_pools WHERE name='default' AND scope='mock'"))
            else:
                await s.execute(_text(
                    "UPDATE cv_budget_pools SET total_amount=:t, reserved_amount=:r, "
                    "settled_amount=:st, paused=:p WHERE id=:id"),
                    {"t": snapshot["total_amount"], "r": snapshot["reserved_amount"],
                     "st": snapshot["settled_amount"], "p": snapshot["paused"],
                     "id": snapshot["id"]})
            await s.commit()


async def _mock_production(db, user_id: int, *, key_prefix: str | None = None):
    """创建带完整父链的作品（单单元计划），返回 CvProduction。"""
    from app.models_commercial import (
        CvActor, CvActorVersion, CvMediaAsset, CvProduct, CvProductVersion,
        CvProduction, CvTemplate, CvTemplateVersion, CvVoiceProfile,
    )

    token = key_prefix or uuid.uuid4().hex[:8]
    image = CvMediaAsset(kind="image", object_key=f"plc/{token}-img.png",
                         sha256="a" * 64, mime="image/png", size_bytes=4,
                         source_role="owned_actor_image", uploaded_by=user_id)
    voice_asset = CvMediaAsset(kind="audio", object_key=f"plc/{token}-voi.mp3",
                               sha256="b" * 64, mime="audio/mpeg", size_bytes=4,
                               source_role="owned_voice_reference", uploaded_by=user_id)
    db.add_all([image, voice_asset])
    await db.flush()
    tpl = CvTemplate(name=f"plc-{token}", created_by=user_id)
    db.add(tpl)
    await db.flush()
    tpl_ver = CvTemplateVersion(template_id=tpl.id, version=1, published_by=user_id)
    db.add(tpl_ver)
    actor = CvActor(name=f"plc-{token}", created_by=user_id)
    db.add(actor)
    await db.flush()
    actor_ver = CvActorVersion(actor_id=actor.id, version=1,
                               image_asset_ids=[image.id], published_by=user_id)
    db.add(actor_ver)
    voice = CvVoiceProfile(actor_id=actor.id, audio_asset_id=voice_asset.id)
    db.add(voice)
    product = CvProduct(name=f"plc-{token}", created_by=user_id)
    db.add(product)
    await db.flush()
    prod_ver = CvProductVersion(product_id=product.id, version=1,
                                image_asset_ids=[image.id], published_by=user_id)
    db.add(prod_ver)
    await db.flush()
    production = CvProduction(
        template_version_id=tpl_ver.id, actor_version_id=actor_ver.id,
        voice_profile_id=voice.id, product_version_id=prod_ver.id,
        status="planned", created_by=user_id,
        plan_json={"shots": [{"shot_key": "S01", "dialogue": "d", "target_duration_ms": 5000}],
                   "units": [{"unit_key": "U001", "request_duration_ms": 5000,
                              "covered_shot_keys": ["S01"],
                              "adopt_ranges": [["S01", 0, 5000]],
                              "params_version": 1, "notes": []}]},
    )
    db.add(production)
    await db.flush()
    return production


# ---------------------------------------------------------------- 恢复与失败语义

@pytest.mark.asyncio
async def test_restart_recovery_only_queries_never_resubmits(platform, fake_atlas):
    """已有上游 ID 的 awaiting_poll 任务：重启后只查询/下载，不新增提交。"""
    from app.services.tasks.poller import _select_and_poll_due

    seeded = await _seed(platform, with_prediction="pred-restart-1",
                         task_status="awaiting_poll",
                         next_action_at=datetime.now(UTC) - timedelta(seconds=1))
    fake_atlas.state.prediction_script["pred-restart-1"] = [
        complete_prediction_body(),
    ]
    submits_before = _generate_calls(fake_atlas)
    await _select_and_poll_due()
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["attempt"].status == "GENERATED"
    assert rows["task"].status == "succeeded"
    assert _generate_calls(fake_atlas) == submits_before, "恢复路径不得重新提交"


@pytest.mark.asyncio
async def test_submit_unknown_freezes_no_resubmit(platform, fake_atlas, monkeypatch):
    """提交传输中断（结果不明）→ SUBMIT_UNKNOWN；重跑执行器不再二次提交。

    网络故障在适配器边界注入（submit_generation 抛 TransportError）；
    适配器自身的错误映射语义由 test_unknown_submission 以 httpx.MockTransport 锁定。
    """
    import app.services.commercial.generation as gen
    from app.services.tasks.executor import execute_task_run

    seeded = await _seed(platform, next_action_at=datetime.now(UTC))

    async def _transport_broken(*a, **k):
        raise httpx.ConnectError("simulated upstream network failure")

    monkeypatch.setattr(gen, "submit_generation", _transport_broken)
    await execute_task_run(seeded["task_id"])
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["attempt"].status == "SUBMIT_UNKNOWN"

    monkeypatch.setattr(gen, "submit_generation", fake_atlas_submit_ok)
    from app.models_tasks import TaskRun

    async with platform["factory"]() as db:  # 模拟孤儿回收重新排队
        row = await db.get(TaskRun, seeded["task_id"])
        row.status = "pending"
        row.lease_token = None
        row.lease_until = None
        row.next_action_at = datetime.now(UTC)
        await db.commit()
    await execute_task_run(seeded["task_id"])
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["attempt"].status == "SUBMIT_UNKNOWN", "SUBMIT_UNKNOWN 必须冻结，不得自动重发"
    assert _generate_calls(fake_atlas) == 0


async def fake_atlas_submit_ok(body, *, base_url, api_key, transport=None):
    """恢复真实提交（走 Fake Atlas）。"""
    from app.services.providers.atlas.h3_reference import submit_generation

    return await submit_generation(body, base_url=base_url, api_key=api_key)


@pytest.mark.asyncio
async def test_poll_429_backs_off_without_download(platform, fake_atlas):
    """查询 429：退避续查，不判死、不下载。"""
    from app.services.tasks.poller import _select_and_poll_due

    seeded = await _seed(platform, with_prediction="pred-429",
                         task_status="awaiting_poll",
                         next_action_at=datetime.now(UTC) - timedelta(seconds=1))
    fake_atlas.state.prediction_status = 429
    try:
        await _select_and_poll_due()
        rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
        assert rows["task"].status == "awaiting_poll", "429 应退避而非失败"
        assert rows["task"].next_action_at > datetime.now(UTC)
        assert rows["attempt"].provider_prediction_id == "pred-429", "不得重建任务号"
    finally:
        fake_atlas.state.prediction_status = 200


@pytest.mark.asyncio
async def test_download_failure_retries_download_only(platform, fake_atlas):
    """下载失败：仅重试下载（OUTPUT_PENDING_DOWNLOAD），恢复后完成。"""
    from app.services.tasks.poller import _select_and_poll_due

    seeded = await _seed(platform, with_prediction="pred-dl",
                         task_status="awaiting_poll",
                         next_action_at=datetime.now(UTC) - timedelta(seconds=1))
    fake_atlas.state.prediction_script["pred-dl"] = [
        complete_prediction_body(name="missing.mp4"),
    ]
    await _select_and_poll_due()
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["attempt"].status == "OUTPUT_PENDING_DOWNLOAD"
    assert rows["task"].status == "awaiting_poll"
    assert _generate_calls(fake_atlas) == 0

    fake_atlas.state.prediction_script["pred-dl"] = [
        complete_prediction_body(),
    ]
    await _due(platform, seeded["task_id"])
    await _select_and_poll_due()
    rows = await _rows(platform, seeded["task_id"], seeded["attempt_id"])
    assert rows["attempt"].status == "GENERATED"
    assert rows["task"].status == "succeeded"
