# -*- coding: utf-8 -*-
"""P1-8/P1-7｜新台词接线与音轨保留回归。

- dialogue_override 走完：请求体 → 参数快照 → 报价指纹 → attempt → 字幕导出；
  旧 attempt/旧导出不被覆盖；参数变化使旧批准失效（QUOTE_CHANGED）；
- Mock 生成片段自带音轨；合成母版含音轨且时长=采用区间之和；
  烧录版保留母版音轨；
- audio_required 片段无音轨 → 合成 422 阻断（不填充静音冒充）；
- 采用区间超出实际媒体时长 → 422（不静默截短）。
"""
from __future__ import annotations

import json
import subprocess
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from tests.conftest import make_user

DIALOGUE_A = "第一版台词：清晨的第一杯水"
DIALOGUE_B = "第二版台词：温和不刺激敏感肌也能放心贴"


def _ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        check=True, capture_output=True,
    ).stdout.decode("utf-8")
    data = json.loads(out)
    streams = data.get("streams") or []
    return {
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "duration_ms": int(float((data.get("format") or {}).get("duration") or 0) * 1000),
    }


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


async def _seed_single_unit_production(db: AsyncSession, admin) -> int:
    """一个含单必需单元（5s）的作品 + 达人/音色/商品父链（Mock 模式直接落库）。"""
    from app.models_commercial import (
        CvActor, CvActorVersion, CvBudgetPool, CvMediaAsset, CvProduct,
        CvProductVersion, CvProduction, CvTemplate, CvTemplateVersion, CvVoiceProfile,
    )

    await CvBudgetPool.ensure_default(db, total=Decimal("50"), created_by=admin.id)
    image = CvMediaAsset(kind="image", object_key="da/i1.png", sha256="1" * 64,
                         mime="image/png", size_bytes=4, source_role="owned_actor_image",
                         uploaded_by=admin.id)
    voice = CvMediaAsset(kind="audio", object_key="da/v1.mp3", sha256="2" * 64,
                         mime="audio/mpeg", size_bytes=4, source_role="owned_voice_reference",
                         uploaded_by=admin.id)
    db.add_all([image, voice])
    await db.flush()
    # 素材交付层需要真实文件（私有存储根内）
    from app.services.commercial.storage import asset_disk_path

    for asset in (image, voice):
        path = asset_disk_path(asset.object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"DA-TESTBYTES-0123456789")
    tpl = CvTemplate(name="da-t", created_by=admin.id)
    db.add(tpl)
    await db.flush()
    tpl_ver = CvTemplateVersion(template_id=tpl.id, version=1, published_by=admin.id)
    db.add(tpl_ver)
    actor = CvActor(name="da-a", created_by=admin.id)
    db.add(actor)
    await db.flush()
    actor_ver = CvActorVersion(actor_id=actor.id, version=1, image_asset_ids=[image.id],
                               published_by=admin.id)
    db.add(actor_ver)
    vp = CvVoiceProfile(actor_id=actor.id, audio_asset_id=voice.id)
    db.add(vp)
    product = CvProduct(name="da-p", created_by=admin.id)
    db.add(product)
    await db.flush()
    prod_ver = CvProductVersion(product_id=product.id, version=1,
                                image_asset_ids=[image.id], published_by=admin.id)
    db.add(prod_ver)
    await db.flush()
    production = CvProduction(
        template_version_id=tpl_ver.id, actor_version_id=actor_ver.id,
        voice_profile_id=vp.id, product_version_id=prod_ver.id,
        status="planned", created_by=admin.id,
        plan_json={
            "shots": [{"shot_key": "S01", "dialogue": DIALOGUE_A, "target_duration_ms": 5000}],
            "units": [{"unit_key": "U001", "request_duration_ms": 5000,
                       "covered_shot_keys": ["S01"],
                       "adopt_ranges": [["S01", 0, 5000]], "params_version": 1, "notes": []}],
        },
    )
    db.add(production)
    await db.commit()
    return production.id


async def _quote_generate(client, pid: int, req_id: str, dialogue: str = "",
                          quote_id: int | None = None):
    if quote_id is None:
        q = await client.post(f"/api/commercial/productions/{pid}/quote", json={
            "unit_key": "U001", "dialogue_override": dialogue})
        assert q.status_code == 200, q.text
        quote_id = q.json()["quote_id"]
    g = await client.post(f"/api/commercial/productions/{pid}/generate", json={
        "unit_key": "U001", "quote_id": quote_id, "client_request_id": req_id,
        "drive": True, "dialogue_override": dialogue})
    return g


# ---------------------------------------------------------------- 新台词全链

@pytest.mark.asyncio
async def test_dialogue_override_flows_to_attempt_and_subtitles(client, db_session, admin):
    """两段不同台词的重做：新台词进入请求/快照/指纹/字幕；旧 attempt 不被覆盖。"""
    pid = await _seed_single_unit_production(db_session, admin)

    # 第一次：无覆盖（计划台词 A）
    g1 = await _quote_generate(client, pid, "dlg-run-1", dialogue="")
    assert g1.status_code == 202, g1.text
    first_attempt = g1.json()["attempt_id"]

    from app.models_commercial import CvGenerationAttempt

    a1 = await db_session.get(CvGenerationAttempt, first_attempt)
    assert DIALOGUE_A in (a1.params_json or {}).get("approved_dialogue", "")

    # 审核通过并合成导出（旧字幕）
    r = await client.post(f"/api/commercial/attempts/{first_attempt}/review", json={
        "dimensions": {"人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                        "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS"},
        "speech_required": True})
    assert r.status_code == 200 and r.json()["overall"] == "REVIEW_APPROVED"
    detail = (await client.get(f"/api/commercial/productions/{pid}")).json()
    old_resp = await client.post(f"/api/commercial/productions/{pid}/compose", json={
        "selections": [{"attempt_id": first_attempt, "ranges": [[0, 5000]]}],
        "subtitles": True, "complete": True})
    assert old_resp.status_code == 200, old_resp.text
    old_export = old_resp.json()
    old_srt = (await client.get(f"/api/commercial/exports/{old_export['export_id']}")).json()["srt_content"]
    assert DIALOGUE_A in old_srt

    # 第二次：改台词 B 重做（新报价 → 新 attempt）
    g2 = await _quote_generate(client, pid, "dlg-run-2", dialogue=DIALOGUE_B)
    assert g2.status_code == 202, g2.text
    second_attempt = g2.json()["attempt_id"]
    assert second_attempt != first_attempt
    a2 = await db_session.get(CvGenerationAttempt, second_attempt)
    params2 = a2.params_json or {}
    assert params2.get("approved_dialogue") == DIALOGUE_B, "重做台词必须进入新 attempt 快照"
    assert params2.get("approved_dialogue") != (a1.params_json or {}).get("approved_dialogue")

    # 旧 attempt 不被覆盖
    await db_session.refresh(a1)
    assert DIALOGUE_A in (a1.params_json or {}).get("approved_dialogue", "")

    # 台词变化 → 旧报价确认时 QUOTE_CHANGED
    q_old = await client.post(f"/api/commercial/productions/{pid}/quote", json={
        "unit_key": "U001", "dialogue_override": ""})
    g_mismatch = await _quote_generate(client, pid, "dlg-run-3", dialogue=DIALOGUE_B,
                                       quote_id=q_old.json()["quote_id"])
    assert g_mismatch.status_code == 409, g_mismatch.text
    assert "QUOTE_CHANGED" in g_mismatch.json()["detail"] or "参数" in g_mismatch.json()["detail"]

    # 新 attempt 审核通过后合成：字幕携带新台词；旧导出保持旧台词
    r2 = await client.post(f"/api/commercial/attempts/{second_attempt}/review", json={
        "dimensions": {"人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                        "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS"},
        "speech_required": True})
    assert r2.status_code == 200
    new_resp = await client.post(f"/api/commercial/productions/{pid}/compose", json={
        "selections": [{"attempt_id": second_attempt, "ranges": [[0, 5000]]}],
        "subtitles": True, "complete": True})
    assert new_resp.status_code == 200, new_resp.text
    new_export = new_resp.json()
    new_srt = (await client.get(f"/api/commercial/exports/{new_export['export_id']}")).json()["srt_content"]
    assert DIALOGUE_B in new_srt, "重做后的字幕必须来自新 attempt 的新台词"
    still_old = (await client.get(f"/api/commercial/exports/{old_export['export_id']}")).json()["srt_content"]
    assert DIALOGUE_A in still_old, "历史导出不得被覆盖"


# ---------------------------------------------------------------- 音轨保留

@pytest.mark.asyncio
async def test_mock_clip_has_audio_and_compose_preserves_it(client, db_session, admin):
    """Mock 片段带音轨；母版含音轨、时长=采用区间；烧录版保留音轨。"""
    pid = await _seed_single_unit_production(db_session, admin)
    g = await _quote_generate(client, pid, "aud-run-1")
    assert g.status_code == 202, g.text
    attempt_id = g.json()["attempt_id"]

    from app.models_commercial import CvGenerationAttempt
    from app.services.commercial.storage import commercial_storage_root

    a = await db_session.get(CvGenerationAttempt, attempt_id)
    clip = commercial_storage_root() / "outputs" / (a.output_asset_key or "")
    info = _ffprobe(str(clip))
    assert info["has_audio"], "Mock 生成片段必须自带音轨（P1-7 测试基建）"

    r = await client.post(f"/api/commercial/attempts/{attempt_id}/review", json={
        "dimensions": {"人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                        "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS"},
        "speech_required": True})
    assert r.status_code == 200
    export = (await client.post(f"/api/commercial/productions/{pid}/compose", json={
        "selections": [{"attempt_id": attempt_id, "ranges": [[0, 4000]]}],
        "subtitles": True, "complete": True})).json()
    master = export["master_path"]
    master_info = _ffprobe(master)
    assert master_info["has_audio"], "合成母版必须保留音轨（修复前 -an 全部丢弃）"
    assert abs(master_info["duration_ms"] - 4000) <= 150, \
        f"母版时长应=采用区间 4000ms，实际 {master_info['duration_ms']}ms"

    # 烧录版保留音轨
    b = await client.post(f"/api/commercial/exports/{export['export_id']}/burn", json={
        "srt_content": "1\n00:00:00,000 --> 00:00:02,000\n测试\n"})
    assert b.status_code == 200, b.text
    burned_info = _ffprobe(b.json()["subtitled_path"])
    assert burned_info["has_audio"], "烧录版必须保留母版音轨"


@pytest.mark.asyncio
async def test_audio_required_without_track_blocks_compose(client, db_session, admin):
    """audio_required 的片段无音轨 → 合成 422（不填充静音冒充）。"""
    pid = await _seed_single_unit_production(db_session, admin)
    g = await _quote_generate(client, pid, "aud-run-2")
    attempt_id = g.json()["attempt_id"]
    from app.models_commercial import CvGenerationAttempt
    from app.services.commercial.storage import commercial_storage_root

    a = await db_session.get(CvGenerationAttempt, attempt_id)
    # 替换输出为无声片段（audio_required=True 的 attempt）
    silent = commercial_storage_root() / "outputs" / "silent-probe.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=5:size=320x180:rate=12",
                    "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True)
    a.output_asset_key = silent.name
    await db_session.commit()

    r = await client.post(f"/api/commercial/attempts/{attempt_id}/review", json={
        "dimensions": {"人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                        "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS"},
        "speech_required": True})
    assert r.status_code == 200
    resp = await client.post(f"/api/commercial/productions/{pid}/compose", json={
        "selections": [{"attempt_id": attempt_id, "ranges": [[0, 4000]]}],
        "subtitles": False, "complete": True})
    assert resp.status_code == 422
    assert "音轨" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_adopt_range_beyond_media_rejected(client, db_session, admin):
    """采用区间超出实际媒体时长 → 422（不静默截短）。"""
    pid = await _seed_single_unit_production(db_session, admin)
    g = await _quote_generate(client, pid, "aud-run-3")
    attempt_id = g.json()["attempt_id"]
    r = await client.post(f"/api/commercial/attempts/{attempt_id}/review", json={
        "dimensions": {"人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                        "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS"},
        "speech_required": True})
    assert r.status_code == 200
    resp = await client.post(f"/api/commercial/productions/{pid}/compose", json={
        "selections": [{"attempt_id": attempt_id, "ranges": [[0, 60000]]}],
        "subtitles": False, "complete": True})
    assert resp.status_code == 422
    assert "超出" in resp.json()["detail"] or "时长" in resp.json()["detail"]
