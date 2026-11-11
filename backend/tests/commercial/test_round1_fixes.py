# -*- coding: utf-8 -*-
"""第一轮确定性缺陷回归：列表先过滤后分页 / 烧录留存 / 费用 mock 证据。"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import (
    CvActor,
    CvActorVersion,
    CvBudgetPool,
    CvExport,
    CvGenerationAttempt,
    CvProduct,
    CvProductVersion,
    CvProduction,
    CvTemplate,
    CvTemplateVersion,
    CvVoiceProfile,
)
from tests.conftest import make_user


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


@pytest_asyncio.fixture
async def client(db_session, owner):
    app = FastAPI()
    app.include_router(commercial_router, prefix="/api/commercial")
    async def override_db():
        yield db_session
    async def override_user():
        return await db_session.get(User, owner.id, populate_existing=True)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _min_production(db, user_id: int, name: str = "P") -> CvProduction:
    """最小合法作品行（仅验证列表查询，不走完整创建链）。"""
    template = CvTemplate(name=f"T-{name}", created_by=user_id)
    db.add(template); await db.flush()
    tv = CvTemplateVersion(template_id=template.id, version=1, status="published",
                           structure_json={"shots": []}, published_by=user_id)
    actor = CvActor(name=f"A-{name}", created_by=user_id); db.add(actor); await db.flush()
    av = CvActorVersion(actor_id=actor.id, version=1, status="published", published_by=user_id)
    product = CvProduct(name=f"PR-{name}", created_by=user_id); db.add(product); await db.flush()
    pv = CvProductVersion(product_id=product.id, version=1, form="贴片", published_by=user_id)
    db.add_all([tv, av, pv]); await db.flush()
    from app.models_commercial import CvMediaAsset
    import secrets

    asset = CvMediaAsset(
        kind="audio", object_key=f"owned_voice_reference/t/{secrets.token_hex(4)}.mp3",
        sha256="e" * 64, mime="audio/mpeg", size_bytes=4,
        source_role="owned_voice_reference", uploaded_by=user_id,
    )
    db.add(asset); await db.flush()
    vp = CvVoiceProfile(actor_id=actor.id, audio_asset_id=asset.id)
    db.add(vp); await db.flush()
    pr = CvProduction(template_version_id=tv.id, actor_version_id=av.id,
                      voice_profile_id=vp.id, product_version_id=pv.id, created_by=user_id)
    db.add(pr); await db.flush()
    return pr


# ---------------------------------------------------------------- F2 先过滤后分页
@pytest.mark.asyncio
async def test_listing_scopes_before_limit(client, db_session, owner) -> None:
    """他人高产 55 条后，本人旧作品仍出现在自己的第一页。"""
    other = await make_user(db_session)
    mine = await _min_production(db_session, owner.id, "mine-old")
    for i in range(55):
        await _min_production(db_session, other.id, f"o{i}")
    await db_session.commit()

    resp = await client.get("/api/commercial/productions")
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()["items"]]
    assert mine.id in ids, "本人作品被他人高产挤出列表（先取后滤缺陷）"
    other_ids = [item["id"] for item in resp.json()["items"]]
    # 本人页不应包含他人作品（所有行 created_by 均为本人）
    all_ids = (await db_session.execute(
        __import__("sqlalchemy").select(CvProduction.id)
    )).scalars().all()
    mine_ids = {p.id for p in (await db_session.execute(
        __import__("sqlalchemy").select(CvProduction).where(CvProduction.created_by == owner.id)
    )).scalars().all()}
    leaked = [i for i in other_ids if i in set(all_ids) and i not in mine_ids]
    assert not leaked, f"他人作品混入本人列表：{leaked[:5]}"


@pytest.mark.asyncio
async def test_listing_pagination_params(client, db_session, owner) -> None:
    for i in range(5):
        await _min_production(db_session, owner.id, f"pg{i}")
    await db_session.commit()
    r1 = await client.get("/api/commercial/productions?limit=2&offset=0")
    r2 = await client.get("/api/commercial/productions?limit=2&offset=2")
    ids1 = [i["id"] for i in r1.json()["items"]]
    ids2 = [i["id"] for i in r2.json()["items"]]
    assert len(ids1) == 2 and len(ids2) == 2
    assert not set(ids1) & set(ids2), "分页参数未生效（页间重叠）"


# ---------------------------------------------------------------- F5 烧录留存
@pytest.mark.asyncio
async def test_burn_persists_srt_and_aligned_state(client, db_session, owner, tmp_path) -> None:
    from app.services.commercial import compose as compose_svc

    clip_dir = tmp_path / "outputs"; clip_dir.mkdir(parents=True)
    import subprocess

    clip = clip_dir / "burn.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=2:size=160x120:rate=10",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
    pr = await _min_production(db_session, owner.id, "burn")
    export = CvExport(production_id=pr.id, master_path=str(clip),
                      srt_content="1\n00:00:00,000 --> 00:00:01,000\n旧草稿\n",
                      created_by=owner.id)
    db_session.add(export); await db_session.flush()

    r = await client.post(f"/api/commercial/exports/{export.id}/burn", json={
        "srt_content": "1\n00:00:00,000 --> 00:00:01,000\n校对后的字幕\n"})
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/commercial/exports/{export.id}")).json()
    assert detail["srt_content"].find("校对后的字幕") >= 0, "烧录后未留存本次字幕内容"
    assert detail["srt_aligned"] is True, "烧录后校对状态未写入"
    assert detail["srt_edited_at"], "校对时间未留存"


@pytest.mark.asyncio
async def test_unburned_export_stays_draft(client, db_session, owner, tmp_path) -> None:
    pr = await _min_production(db_session, owner.id, "draft")
    export = CvExport(production_id=pr.id, master_path=str(tmp_path / "x.mp4"),
                      srt_content="草稿", created_by=owner.id)
    db_session.add(export); await db_session.flush()
    detail = (await client.get(f"/api/commercial/exports/{export.id}")).json()
    assert detail["srt_aligned"] is False  # 未烧录的历史导出保持草稿态


# ---------------------------------------------------------------- F6 费用 mock 证据
@pytest.mark.asyncio
async def test_costs_mock_from_attempt_evidence(client, db_session, owner) -> None:
    """尝试带 MOCK- 前缀 → mock=true，即使当前关闭商业 mock 模式也按事实标记。"""
    from unittest.mock import patch as _patch

    pr = await _min_production(db_session, owner.id, "cost")
    db_session.add(CvGenerationAttempt(
        production_id=pr.id, client_request_id="cr-ev", payload_hash="h",
        status="GENERATED", provider_prediction_id="MOCK-pred-x",
        created_by=owner.id))
    await db_session.commit()
    with _patch("app.services.commercial.mock_provider.mock_enabled", lambda: False):
        d = (await client.get(f"/api/commercial/productions/{pr.id}")).json()
    assert d["costs"]["mock"] is True
    assert d["costs"]["mock_basis"] == "attempts"
