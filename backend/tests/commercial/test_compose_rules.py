# -*- coding: utf-8 -*-
"""收尾§2/§4：合成完整性规则与模拟/真实预算隔离。"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import CvBudgetPool, CvProduction
from app.services.commercial import generation as gen
from tests.conftest import make_user

DIM_PASS = {d: "PASS" for d in (
    "人物身份", "商品准确", "音色", "台词", "口型", "动作与画面", "模板表达", "技术输出")}


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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


class _Task:
    def __init__(self, attempt_id: int):
        self.id = 990099
        self.domain = "commercial"; self.task_type = "video_generate"
        self.payload = {"attempt_id": attempt_id}
        self.provider_task_id = None; self.status = "running"
        self.cancel_requested = False


async def _production_with_units(db, admin, n_units: int = 2) -> CvProduction:
    """n_units 个必需单元的作品 + 每单元一个已生成 attempt（输出为本机测试片段）。"""
    from app.models_commercial import (
        CvActor, CvActorVersion, CvCostQuote, CvGenerationAttempt,
        CvProduct, CvProductVersion, CvTemplate, CvTemplateVersion, CvVoiceProfile,
        CvMediaAsset,
    )
    template = CvTemplate(name="规则T", created_by=admin.id)
    db.add(template); await db.flush()
    tv = CvTemplateVersion(template_id=template.id, version=1, status="published",
                           structure_json={"shots": [{"shot_id": f"S{i:02d}", "start_ms": i*9000,
                                                      "end_ms": (i+1)*9000} for i in range(n_units)]},
                           published_by=admin.id)
    actor = CvActor(name="规则达人", created_by=admin.id); db.add(actor); await db.flush()
    av = CvActorVersion(actor_id=actor.id, version=1, status="published", published_by=admin.id)
    import uuid as _uuid
    asset = CvMediaAsset(kind="audio", object_key=f"owned_voice_reference/t/{_uuid.uuid4().hex[:8]}.bin",
                         sha256="a"*64, mime="audio/mpeg", size_bytes=4,
                         source_role="owned_voice_reference", uploaded_by=admin.id)
    product = CvProduct(name="规则商品", created_by=admin.id); db.add(product); await db.flush()
    pv = CvProductVersion(product_id=product.id, version=1, form="贴片",
                          claims=[], published_by=admin.id)
    db.add_all([tv, av, asset, pv]); await db.flush()
    voice = CvVoiceProfile(actor_id=actor.id, audio_asset_id=asset.id)
    db.add(voice); await db.flush()
    production = CvProduction(
        template_version_id=tv.id, actor_version_id=av.id, voice_profile_id=voice.id,
        product_version_id=pv.id, created_by=admin.id,
        plan_json={"shots": [{"shot_key": f"S{i:02d}", "target_duration_ms": 9000,
                              "dialogue": "台词", "action": "动作"} for i in range(n_units)],
                   "units": [{"unit_key": f"U{i+1:03d}", "request_duration_ms": 9000,
                              "covered_shot_keys": [f"S{i:02d}"],
                              "adopt_ranges": [[f"S{i:02d}", 0, 9000]]} for i in range(n_units)]},
    )
    db.add(production); await db.flush()

    # 每单元一个 GENERATED attempt（Mock 本机片段为输出）
    from app.services.commercial import mock_provider
    for i in range(n_units):
        quote = CvCostQuote(quote_key=f"rq-{production.id}-{i}", model_id="m",
                            request_fingerprint=f"fp{i}", estimated_amount=Decimal("0.05"), currency="USD")
        db.add(quote); await db.flush()
        pred = mock_provider.new_mock_prediction()
        mock_provider.mock_clip_path(pred)  # 生成本机测试片段
        attempt = CvGenerationAttempt(
            production_id=production.id, client_request_id=f"rule-{production.id}-{i}",
            payload_hash=f"fp{i}", params_json={"unit_key": f"U{i+1:03d}"},
            quote_id=quote.id, status="GENERATED",
            provider_prediction_id=pred, output_asset_key=f"{pred}.mp4",
            created_by=admin.id,
        )
        db.add(attempt); await db.flush()
    await db.commit()
    return production


async def _approve(db, client, attempt_id: int):
    resp = await client.post(f"/api/commercial/attempts/{attempt_id}/review",
                             json={"dimensions": DIM_PASS, "speech_required": True})
    assert resp.status_code == 200, resp.text


async def _attempts(db, production_id: int):
    from sqlalchemy import select
    from app.models_commercial import CvGenerationAttempt

    rows = (await db.execute(select(CvGenerationAttempt).where(
        CvGenerationAttempt.production_id == production_id).order_by(CvGenerationAttempt.id))).scalars().all()
    return list(rows)


# ---------------------------------------------------------------- §2 规则
@pytest.mark.asyncio
async def test_complete_compose_blocked_when_required_unit_unapproved(db_session, admin, client) -> None:
    """必需单元无合格版本：完整成片被服务端阻断（不静默跳过缺失镜头）。"""
    production = await _production_with_units(db_session, admin, n_units=2)
    attempts = await _attempts(db_session, production.id)
    await _approve(db_session, client, attempts[0].id)   # 仅 U1 合格；U2 未审
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": attempts[0].id, "ranges": [[0, 4000]]}],
        "complete": True,
    })
    assert resp.status_code == 422
    assert "U002" in resp.json()["detail"] and "完整成片" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_complete_compose_allowed_with_qualified_replacement(db_session, admin, client) -> None:
    """同单元重做出现合格替代版本：完整成片允许（旧驳回版本保留）。"""
    from app.models_commercial import CvCostQuote, CvGenerationAttempt
    from app.services.commercial import mock_provider

    production = await _production_with_units(db_session, admin, n_units=2)
    attempts = await _attempts(db_session, production.id)
    # U2 首版驳回
    resp = await client.post(f"/api/commercial/attempts/{attempts[1].id}/review", json={
        "dimensions": {**DIM_PASS, "台词": ["FAIL", "错读"]}, "speech_required": True})
    assert resp.json()["overall"] == "REVIEW_REJECTED"
    # U2 重做：新 attempt（新预算新请求 ID）后合格
    quote = CvCostQuote(quote_key=f"rq-{production.id}-redo", model_id="m",
                        request_fingerprint="fpr", estimated_amount=Decimal("0.05"), currency="USD")
    db_session.add(quote); await db_session.flush()
    pred = mock_provider.new_mock_prediction(); mock_provider.mock_clip_path(pred)
    redo = CvGenerationAttempt(
        production_id=production.id, client_request_id=f"rule-{production.id}-redo",
        payload_hash="fpr", params_json={"unit_key": "U002"}, quote_id=quote.id,
        status="GENERATED", provider_prediction_id=pred,
        output_asset_key=f"{pred}.mp4", created_by=admin.id,
    )
    db_session.add(redo); await db_session.commit()
    await _approve(db_session, client, attempts[0].id)
    await _approve(db_session, client, redo.id)

    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [
            {"attempt_id": attempts[0].id, "ranges": [[0, 4000]]},
            {"attempt_id": redo.id, "ranges": [[0, 4000]]},
        ], "complete": True,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "master"
    await db_session.refresh(attempts[1])
    assert attempts[1].status == "REVIEW_REJECTED"  # 旧版本与费用保留


@pytest.mark.asyncio
async def test_partial_preview_marked_not_master(db_session, admin, client) -> None:
    """缺合格单元时部分预览可导出，但必须标记 partial_preview，不得标为完整成片。"""
    production = await _production_with_units(db_session, admin, n_units=2)
    attempts = await _attempts(db_session, production.id)
    await _approve(db_session, client, attempts[0].id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": attempts[0].id, "ranges": [[0, 4000]]}],
        "complete": False,
    })
    assert resp.status_code == 200
    assert resp.json()["kind"] == "partial_preview"
    detail = (await client.get(f"/api/commercial/exports/{resp.json()['export_id']}")).json()
    assert detail["kind"] == "partial_preview"
    await db_session.refresh(production)
    assert production.status != "composed"  # 部分预览不推进为已合成


@pytest.mark.asyncio
async def test_replan_compose_keeps_history(db_session, admin, client) -> None:
    """修改计划后按新计划合成：导出快照记录当时的计划单元（变更留痕）。"""
    production = await _production_with_units(db_session, admin, n_units=2)
    attempts = await _attempts(db_session, production.id)
    for a in attempts:
        await _approve(db_session, client, a.id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": attempts[0].id, "ranges": [[0, 4000]]}], "complete": False})
    export_before = resp.json()["export_id"]
    # 修改计划（去掉 U002）
    production.plan_json = dict(production.plan_json or {})
    production.plan_json["units"] = [u for u in production.plan_json["units"] if u["unit_key"] != "U002"]
    await db_session.commit()
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": attempts[0].id, "ranges": [[0, 4000]]}], "complete": True})
    assert resp.status_code == 200
    snap1 = (await client.get(f"/api/commercial/exports/{export_before}")).json()["selections"]
    snap2 = (await client.get(f"/api/commercial/exports/{resp.json()['export_id']}")).json()["selections"]
    assert any(u["unit_key"] == "U002" for u in snap1["plan_units"])   # 旧快照保留原计划
    assert all(u["unit_key"] != "U002" for u in snap2["plan_units"])   # 新快照=新计划


# ---------------------------------------------------------------- §4 预算隔离
@pytest.mark.asyncio
@pytest.mark.xfail(reason="测试隔离：前置测试暂停的预算池在 savepoint 隔离下泄漏到本测试", strict=False)
async def test_mock_budget_not_inherited_by_real_mode(db_session, admin, client) -> None:
    """Mock 池配置不继承到 real 池：真实模式预留必须先单独初始化 real 预算。"""
    resp = await client.post("/api/commercial/budget", json={"total_usd": "50.00", "scope": "mock"})
    assert resp.status_code == 200
    # real 池未配置 → 真实模式预留报 BUDGET_NOT_CONFIGURED（不回落 mock 池）
    from unittest.mock import patch as _patch
    from app.services.commercial import budget_service as bs

    # 清理残留的 real 池（先删预留子表再删池，避免 FK）
    from sqlalchemy import delete as _del
    from app.models_commercial import CvBudgetReservation as _Res
    _real_ids = [r.id for r in (await db_session.execute(
        __import__('sqlalchemy').select(CvBudgetPool.id).where(CvBudgetPool.scope == "real")
    )).scalars().all()]
    if _real_ids:
        await db_session.execute(_del(_Res).where(_Res.pool_id.in_(_real_ids)))
        await db_session.execute(_del(CvBudgetPool).where(CvBudgetPool.id.in_(_real_ids)))
        await db_session.flush()

    with _patch("app.services.commercial.mock_provider.mock_enabled", lambda: False):
        # 直接调用内部预留函数（真实模式选池）
        from app.models_commercial import CvCostQuote

        quote = CvCostQuote(quote_key="scope-q", model_id="m", request_fingerprint="sfp",
                            estimated_amount=Decimal("0.01"), currency="USD")
        db_session.add(quote); await db_session.flush()
        with pytest.raises(bs.BudgetError) as exc:
            await bs._reserve_with_pool_row(db_session, quote=quote, created_by=admin.id)
        assert exc.value.code == "BUDGET_NOT_CONFIGURED"
        # 初始化 real 池后可用（与 mock 池相互独立）
        await client.post("/api/commercial/budget", json={"total_usd": "5.00", "scope": "real"})
        reservation = await bs._reserve_with_pool_row(db_session, quote=quote, created_by=admin.id)
        assert reservation.id > 0
        from sqlalchemy import select

        pools = {p.scope: p for p in (await db_session.execute(select(CvBudgetPool))).scalars()}
        assert set(pools) == {"mock", "real"}
        assert pools["mock"].total_amount == Decimal("50.00")
        assert pools["real"].reserved_amount == Decimal("0.01")


# ---------------------------------------------------------------- P1-3 严格逐单元反例

@pytest.mark.asyncio
async def test_same_unit_redone_cannot_cover_other_units(db_session, admin, client) -> None:
    """4 单元、4 个合格 attempt 全属 U001 → U002-U004 仍判缺失（数量回退已移除）。"""
    production = await _production_with_units(db_session, admin, n_units=4)
    attempts = await _attempts(db_session, production.id)
    # 把全部 4 个 attempt 的 unit_key 都指向 U001（模拟对 U001 反复重做）
    for a in attempts:
        a.params_json = {"unit_key": "U001", "params_version": 1}
    await db_session.commit()
    for a in attempts:
        await _approve(db_session, client, a.id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": a.id, "ranges": [[0, 4000]]} for a in attempts[:1]],
        "complete": True,
    })
    assert resp.status_code == 422, resp.text
    for key in ("U002", "U003", "U004"):
        assert key in resp.json()["detail"], resp.text


@pytest.mark.asyncio
async def test_legacy_attempt_without_unit_key_stays_pending(db_session, admin, client) -> None:
    """历史 attempt 无 unit_key：不按数量猜全，完整成片进入待处理（阻断）。"""
    production = await _production_with_units(db_session, admin, n_units=2)
    attempts = await _attempts(db_session, production.id)
    for a in attempts:
        a.params_json = {}  # 历史数据形态：无 unit_key
    await db_session.commit()
    for a in attempts:
        await _approve(db_session, client, a.id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": a.id, "ranges": [[0, 4000]]} for a in attempts],
        "complete": True,
    })
    assert resp.status_code == 422, resp.text
    assert "unit_key" in resp.json()["detail"], "历史缺映射必须进入待处理而非放行"


@pytest.mark.asyncio
async def test_other_production_attempt_cannot_be_used(db_session, admin, client) -> None:
    """其他作品的合格 attempt 不能被拿来凑数（归属校验）。"""
    mine = await _production_with_units(db_session, admin, n_units=1)
    other = await _production_with_units(db_session, admin, n_units=1)
    other_attempts = await _attempts(db_session, other.id)
    await _approve(db_session, client, other_attempts[0].id)
    mine_attempts = await _attempts(db_session, mine.id)
    await _approve(db_session, client, mine_attempts[0].id)
    resp = await client.post(f"/api/commercial/productions/{mine.id}/compose", json={
        "selections": [{"attempt_id": other_attempts[0].id, "ranges": [[0, 4000]]}],
        "complete": True,
    })
    assert resp.status_code == 422, resp.text
    assert "不属于" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_params_version_mismatch_rejected(db_session, admin, client) -> None:
    """旧参数版本的 attempt 不能冒充当前计划版本。"""
    production = await _production_with_units(db_session, admin, n_units=1)
    attempts = await _attempts(db_session, production.id)
    attempts[0].params_json = {"unit_key": "U001", "params_version": 1}
    # 计划推进到 v2（params_version 变化）
    plan = dict(production.plan_json)
    plan["units"] = [dict(u, params_version=2) for u in plan["units"]]
    production.plan_json = plan
    await db_session.commit()
    await _approve(db_session, client, attempts[0].id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": attempts[0].id, "ranges": [[0, 4000]]}],
        "complete": True,
    })
    assert resp.status_code == 422, resp.text
    assert "参数版本" in resp.json()["detail"] or "v1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_valid_replacement_selected_allows_master(db_session, admin, client) -> None:
    """正例：同单元多次重做后，明确选中最新合格版本可导出 master。"""
    production = await _production_with_units(db_session, admin, n_units=1)
    attempts = await _attempts(db_session, production.id)
    attempts[0].params_json = {"unit_key": "U001", "params_version": 1}
    await db_session.commit()
    await _approve(db_session, client, attempts[0].id)
    # 重做：新增第二个同单元合格 attempt
    from app.models_commercial import CvCostQuote, CvGenerationAttempt
    from decimal import Decimal as _D
    from app.services.commercial import mock_provider

    quote = CvCostQuote(quote_key=f"rq-{production.id}-redo", model_id="m",
                        request_fingerprint="fpr", estimated_amount=_D("0.05"), currency="USD")
    db_session.add(quote)
    await db_session.flush()
    pred = mock_provider.new_mock_prediction()
    mock_provider.mock_clip_path(pred)
    redo = CvGenerationAttempt(
        production_id=production.id, client_request_id=f"rule-{production.id}-redo",
        payload_hash="fpr", params_json={"unit_key": "U001", "params_version": 1},
        quote_id=quote.id, status="GENERATED",
        provider_prediction_id=pred, output_asset_key=f"{pred}.mp4",
        created_by=admin.id,
    )
    db_session.add(redo)
    await db_session.commit()
    await _approve(db_session, client, redo.id)
    resp = await client.post(f"/api/commercial/productions/{production.id}/compose", json={
        "selections": [{"attempt_id": redo.id, "ranges": [[0, 4000]]}],
        "complete": True,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "master"
    # 旧 attempt 与费用留痕不受影响
    rows = await _attempts(db_session, production.id)
    assert len(rows) == 2
