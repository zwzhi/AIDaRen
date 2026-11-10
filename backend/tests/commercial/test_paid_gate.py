# -*- coding: utf-8 -*-
"""P1-6｜付费门禁回归：真实模式三层门（API / handler 执行前 / 占位模型 ID）。

修复目标：
- 付费总开关关闭、模型 ID 缺失、能力未验证 → 报价/生成/解析一律阻断；
- 不回落占位 model ID；
- 排队后配置降级，执行前重新检查（不提交上游）；
- 已有上游任务号的恢复路径（查询/下载）不受新任务门影响；
- 保存密钥等配置不自动开启付费。
外部 HTTP 全部指向本地 Fake Atlas（回环），零真实调用。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from tests.conftest import make_user
from tests.commercial.fake_atlas import fake_atlas  # noqa: F401


@pytest_asyncio.fixture
async def admin(db_session):
    user = await make_user(db_session)
    user.role = "admin"
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def client(db_session, admin):
    app = FastAPI()
    app.include_router(commercial_router, prefix="/api/commercial")

    async def override_db():
        yield db_session

    async def override_user():
        return await db_session.get(User, admin.id, populate_existing=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def _set_commercial(monkeypatch, *, mock=False, enabled=True, paid=False,
                    key="atlas-test-key", gemini="", h3="", verified=""):
    """以环境变量覆盖商业域配置并刷新 settings 缓存。"""
    for name, value in {
        "COMMERCIAL_MOCK_MODE": "true" if mock else "false",
        "COMMERCIAL_ENABLED": "true" if enabled else "false",
        "COMMERCIAL_PAID_EXECUTION_ENABLED": "true" if paid else "false",
        "ATLAS_API_KEY": key,
        "GEMINI_ANALYSIS_MODEL_ID": gemini,
        "H3_DEVELOPER_REFERENCE_MODEL_ID": h3,
        "COMMERCIAL_VERIFIED_MODELS": verified,
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    config.get_settings.cache_clear()


async def _seed_quoteable_production(db: AsyncSession, admin: User) -> int:
    """直接落库：一个含单单元计划的作品（足够触发 /quote 全链）。"""
    from app.models_commercial import (
        CvActor, CvActorVersion, CvMediaAsset, CvProduct, CvProductVersion,
        CvProduction, CvTemplate, CvTemplateVersion, CvVoiceProfile,
    )

    asset = CvMediaAsset(kind="image", object_key="gate/a.png", sha256="g" * 64,
                         mime="image/png", size_bytes=4, source_role="owned_actor_image",
                         uploaded_by=admin.id)
    voice_asset = CvMediaAsset(kind="audio", object_key="gate/v.mp3", sha256="h" * 64,
                               mime="audio/mpeg", size_bytes=4, source_role="owned_voice_reference",
                               uploaded_by=admin.id)
    db.add_all([asset, voice_asset])
    await db.flush()
    tpl = CvTemplate(name="gate-t", created_by=admin.id)
    db.add(tpl)
    await db.flush()
    tpl_ver = CvTemplateVersion(template_id=tpl.id, version=1, published_by=admin.id)
    db.add(tpl_ver)
    actor = CvActor(name="gate-a", created_by=admin.id)
    db.add(actor)
    await db.flush()
    actor_ver = CvActorVersion(actor_id=actor.id, version=1,
                               image_asset_ids=[asset.id], published_by=admin.id)
    db.add(actor_ver)
    voice = CvVoiceProfile(actor_id=actor.id, audio_asset_id=voice_asset.id)
    db.add(voice)
    product = CvProduct(name="gate-p", created_by=admin.id)
    db.add(product)
    await db.flush()
    prod_ver = CvProductVersion(product_id=product.id, version=1,
                                image_asset_ids=[asset.id], published_by=admin.id)
    db.add(prod_ver)
    await db.flush()
    production = CvProduction(
        template_version_id=tpl_ver.id, actor_version_id=actor_ver.id,
        voice_profile_id=voice.id, product_version_id=prod_ver.id,
        status="planned", created_by=admin.id,
        plan_json={"shots": [{"shot_key": "S01", "dialogue": "d", "target_duration_ms": 5000}],
                   "units": [{"unit_key": "U001", "request_duration_ms": 5000,
                              "covered_shot_keys": ["S01"],
                              "adopt_ranges": [["S01", 0, 5000]],
                              "params_version": 1, "notes": []}]},
    )
    db.add(production)
    await db.commit()
    return production.id


# ---------------------------------------------------------------- API 层门禁

@pytest.mark.asyncio
async def test_quote_blocked_when_paid_execution_disabled(
        client, db_session, admin, monkeypatch, fake_atlas):
    """付费总开关关闭（即使模型已验证）→ 报价必须阻断，不得触达上游。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=False,
                    gemini="gemini-x", h3="h3-y", verified="gemini-x,h3-y")
    import app.services.providers.atlas.pricing as pricing
    called = {"n": 0}
    orig = pricing.quote_generation

    async def spy(*a, **k):
        called["n"] += 1
        return await orig(*a, **k)

    monkeypatch.setattr(pricing, "quote_generation", spy)
    pid = await _seed_quoteable_production(db_session, admin)
    resp = await client.post(f"/api/commercial/productions/{pid}/quote", json={"unit_key": "U001"})
    assert resp.status_code == 400, resp.text
    assert called["n"] == 0, "付费开关关闭时不应发起真实报价请求"


@pytest.mark.asyncio
async def test_quote_blocked_when_model_ids_missing(
        client, db_session, admin, monkeypatch, fake_atlas):
    """两个精确 model ID 均留空 → 阻断；不允许回落占位模型。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=True, gemini="", h3="")
    pid = await _seed_quoteable_production(db_session, admin)
    resp = await client.post(f"/api/commercial/productions/{pid}/quote", json={"unit_key": "U001"})
    assert resp.status_code == 400, resp.text
    assert "模型" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_quote_blocked_when_model_unverified(
        client, db_session, admin, monkeypatch, fake_atlas):
    """模型 ID 已配置但未进入已验证清单 → MODEL_CAPABILITY_UNVERIFIED。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=True,
                    gemini="gemini-x", h3="h3-y", verified="")
    pid = await _seed_quoteable_production(db_session, admin)
    resp = await client.post(f"/api/commercial/productions/{pid}/quote", json={"unit_key": "U001"})
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_real_analyze_blocked_without_paid_gate(
        client, db_session, admin, monkeypatch, fake_atlas):
    """真实解析（Gemini）同样受三层门约束：付费开关关闭即阻断。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=False,
                    gemini="gemini-x", h3="h3-y", verified="gemini-x,h3-y")
    from app.models_commercial import CvMediaAsset, CvReferenceSource

    asset = CvMediaAsset(kind="video", object_key="gate/src.mp4", sha256="i" * 64,
                         mime="video/mp4", size_bytes=4, duration_ms=8000, has_audio=True,
                         source_role="reference_source_video", uploaded_by=admin.id)
    db_session.add(asset)
    await db_session.flush()
    source = CvReferenceSource(media_asset_id=asset.id, duration_ms=8000,
                               uploaded_by=admin.id)
    db_session.add(source)
    await db_session.commit()
    resp = await client.post(f"/api/commercial/sources/{source.id}/analyze")
    assert resp.status_code == 400, resp.text
    assert not [r for r in fake_atlas.state.requests if r[0] == "calculate"], \
        "解析门禁未生效会继续触达上游"


# ---------------------------------------------------------------- handler 执行前重检

class _GateTask:
    """executor 传入形态的最小 task 替身（脱管对象模拟）。"""

    def __init__(self, attempt_id: int):
        self.id = 990077
        self.payload = {"attempt_id": attempt_id}
        self.provider_task_id = None
        self.cancel_requested = False


@pytest.mark.asyncio
async def test_handler_rechecks_gate_before_first_submit(
        db_session, admin, monkeypatch):
    """任务排队后配置降级（付费开关关闭）→ 执行前重检并失败，不提交上游。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=False,
                    gemini="gemini-x", h3="h3-y", verified="gemini-x,h3-y")
    from app.models_commercial import CvGenerationAttempt

    attempt = CvGenerationAttempt(
        production_id=None, attempt_no=1, client_request_id="gate-handler-1",
        payload_hash="f" * 64,
        params_json={"model_id": "h3-y", "prompt": "p", "approved_dialogue": "d",
                     "actor_image_asset_ids": [], "product_image_asset_ids": [],
                     "voice_reference_asset_ids": [9], "resolution_id": "768p",
                     "duration_ms": 5000, "aspect_ratio": "9:16", "audio_required": True,
                     "unit_key": "U001"},
        status="APPROVED", created_by=admin.id,
    )
    db_session.add(attempt)
    await db_session.commit()

    import app.services.commercial.generation as gen

    async def _no_submit(*a, **k):  # 上游提交必须不可达
        raise AssertionError("付费门禁未生效：不应提交上游")

    monkeypatch.setattr(gen, "submit_generation", _no_submit)
    result = await gen.execute_generation_task(
        _GateTask(attempt.id), db=db_session, base_url="http://127.0.0.1:1", api_key="k")
    await db_session.refresh(attempt)
    assert result and result.get("failed"), result
    assert attempt.status == "PROVIDER_FAILED"
    assert attempt.error_code in ("MODEL_CAPABILITY_UNVERIFIED", "PROVIDER_NOT_CONFIGURED"), \
        attempt.error_code


@pytest.mark.asyncio
async def test_recovery_with_prediction_not_blocked_by_gate(
        db_session, admin, monkeypatch):
    """已有上游任务号（恢复/查询/下载）不受新任务门影响。"""
    _set_commercial(monkeypatch, mock=False, enabled=True, paid=False)
    from app.models_commercial import CvGenerationAttempt

    attempt = CvGenerationAttempt(
        production_id=None, attempt_no=1, client_request_id="gate-recover-1",
        payload_hash="f" * 64, params_json={"duration_ms": 5000, "unit_key": "U001"},
        status="PROVIDER_RUNNING", provider_prediction_id="pred-recover-1",
        created_by=admin.id,
    )
    db_session.add(attempt)
    await db_session.commit()
    import app.services.commercial.generation as gen

    result = await gen.execute_generation_task(
        _GateTask(attempt.id), db=db_session, base_url="http://127.0.0.1:1", api_key="k")
    assert result and result.get("awaiting_poll"), result


# ---------------------------------------------------------------- 占位与配置语义

@pytest.mark.asyncio
async def test_no_placeholder_model_id_in_plan_params(monkeypatch):
    """H3 model ID 未配置时参数快照为空串，不回落占位 ID。"""
    _set_commercial(monkeypatch, mock=True, h3="")
    from app.api.commercial import productions as prod_api
    from app.models_commercial import CvProduction

    production = CvProduction(
        template_version_id=1, actor_version_id=1, voice_profile_id=1, product_version_id=1,
        plan_json={"shots": [{"shot_key": "S01", "dialogue": "d"}],
                   "units": [{"unit_key": "U001", "request_duration_ms": 5000,
                              "covered_shot_keys": ["S01"]}]},
    )
    params = prod_api._build_unit_params(production, {"unit_key": "U001",
                                                      "request_duration_ms": 5000,
                                                      "covered_shot_keys": ["S01"]}, 1)
    assert params["model_id"] == "", "不得回落占位模型 ID"


@pytest.mark.asyncio
async def test_saving_key_does_not_enable_paid_execution(db_session, admin, monkeypatch):
    """保存 Atlas 密钥等配置不得自动开启付费执行或验证清单。"""
    from app.schemas_settings import AdminModelSettingsPatch
    from app.services import model_settings

    saved_overlay = dict(model_settings._overlay)
    saved_snapshot = model_settings._routing_snapshot
    try:
        await model_settings.patch_admin_model_settings(db_session, AdminModelSettingsPatch(
            commercial_enabled=True,
            atlas_api_key="atlas-test-key-only",
            gemini_analysis_model_id="gemini-x",
            h3_developer_reference_model_id="h3-y",
        ))
        config.get_settings.cache_clear()
        await model_settings.load_model_settings_cache(db_session)
        s = config.get_settings()
        assert s.commercial_paid_execution_enabled is False
        assert s.commercial_verified_models == ""
        assert s.atlas_api_key == "atlas-test-key-only"
    finally:
        model_settings._routing_snapshot = saved_snapshot
        model_settings._refresh_overlay({"flat": saved_overlay})
        config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mock_mode_quote_still_works(client, db_session, admin, monkeypatch):
    """Mock 模式不受真实门禁影响（回归保护）。"""
    _set_commercial(monkeypatch, mock=True)
    pid = await _seed_quoteable_production(db_session, admin)
    resp = await client.post(f"/api/commercial/productions/{pid}/quote", json={"unit_key": "U001"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mock"] is True


@pytest.mark.asyncio
async def test_capabilities_endpoint_drives_options(client, monkeypatch):
    """P1-1：能力档案端点返回当前档案（前端选项唯一来源，含 DRAFT 标注）。"""
    _set_commercial(monkeypatch, mock=True)
    resp = await client.get("/api/commercial/capabilities")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capability_verified"] is False, "DRAFT 档案不得声称已验证"
    assert "768p" in body["resolutions"] and "720p" not in body["resolutions"]
    assert body["duration_min_ms"] == 5000 and body["duration_max_ms"] == 15000
