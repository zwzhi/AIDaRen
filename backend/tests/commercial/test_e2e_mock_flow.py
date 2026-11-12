# -*- coding: utf-8 -*-
"""阶段二 E2E：模拟供应商 + 真实应用流程（模板 T1 → C1 → 换素材 C2）。

只模拟外部供应商（Gemini/H3/报价），其余全部真实：
REST 接口、权限、数据库持久化、预算预留、幂等、审核门槛、FFmpeg 合成。
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import CvAnalysisRun, CvMediaAsset
from tests.conftest import make_user


def _png_bytes(width=4, height=4) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _mp3_bytes(path: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", str(path)],
        check=True, capture_output=True,
    )
    return path.read_bytes()


def _video_bytes(path: Path, seconds: int = 3) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=160x120:rate=10",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path.read_bytes()


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
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _upload(c: httpx.AsyncClient, name: str, content: bytes, role: str, mime: str) -> int:
    resp = await c.post(
        "/api/commercial/sources",
        files={"file": (name, content, mime)},
        data={"source_role": role, "rights_declaration": "E2E 测试素材"},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _make_actor(c: httpx.AsyncClient, name: str, tmp: Path, voice_bytes: bytes) -> tuple[int, int, int]:
    image_id = await _upload(c, f"{name}.png", _png_bytes(), "owned_actor_image", "image/png")
    voice_id = await _upload(c, f"{name}.mp3", voice_bytes, "owned_voice_reference", "audio/mpeg")
    resp = await c.post("/api/commercial/actors", json={
        "name": name, "image_asset_ids": [image_id], "appearance_desc": "测试达人",
    })
    assert resp.status_code == 200, resp.text
    actor_id = resp.json()["actor_id"]
    actor_version_id = resp.json()["actor_version_id"]
    resp = await c.post(f"/api/commercial/actors/{actor_id}/voices", json={"audio_asset_id": voice_id})
    assert resp.status_code == 200, resp.text
    return actor_version_id, resp.json()["voice_profile_id"], voice_id


async def _run_pipeline(
    c: httpx.AsyncClient, tmp: Path, *,
    template_version_id: int, actor_version_id: int, voice_profile_id: int,
    product_version_id: int, claim_text: str, old_claim: str, tag: str,
) -> dict:
    """一个作品的全流程：创建 → 适配 → 计划 → 报价 → 生成（Mock）→ 审核 → 合成。"""
    # 1) 创建作品
    resp = await c.post("/api/commercial/productions", json={
        "template_version_id": template_version_id,
        "actor_version_id": actor_version_id,
        "voice_profile_id": voice_profile_id,
        "product_version_id": product_version_id,
        "target_duration_ms": 15_000, "resolution_id": "768p",
        "dialogue_locked": False,
    })
    assert resp.status_code == 200, resp.text
    production_id = resp.json()["production_id"]

    # 2) 文案适配（Mock Gemini 文本适配器）
    resp = await c.post(f"/api/commercial/productions/{production_id}/adapt", json={"marketing_goal": "种草"})
    assert resp.status_code == 200, resp.text
    shots = resp.json()["shots"]
    dialogues = " ".join(str(s["dialogue"]) for s in shots)
    assert claim_text in dialogues, f"{tag}：适配台词应包含本商品卖点"
    assert old_claim not in dialogues, f"{tag}：旧商品卖点不得迁移"

    # 3) 编译生成单元（三时长分离）
    resp = await c.post(f"/api/commercial/productions/{production_id}/plan")
    assert resp.status_code == 200, resp.text
    units = resp.json()["units"]
    assert units, f"{tag}：应产出至少一个生成单元"

    # 4) 报价（Mock 价显著标记）
    quote_ids = {}
    for unit in units:
        resp = await c.post(f"/api/commercial/productions/{production_id}/quote", json={"unit_key": unit["unit_key"]})
        assert resp.status_code == 200, resp.text
        quote = resp.json()
        assert quote["mock"] is True and "mock" in quote["price_source"]
        quote_ids[unit["unit_key"]] = quote["quote_id"]

    # 5) 生成（双击幂等 + Mock 驱动到 GENERATED）
    attempt_ids = {}
    for unit in units:
        client_req = f"e2e-{tag}-{unit['unit_key']}"
        first = await c.post(f"/api/commercial/productions/{production_id}/generate", json={
            "unit_key": unit["unit_key"], "quote_id": quote_ids[unit["unit_key"]],
            "client_request_id": client_req, "drive": True,
        })
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["attempt_status"] == "GENERATED", body
        assert body["prediction_id"].startswith("MOCK-")
        attempt_ids[unit["unit_key"]] = body["attempt_id"]
        # 双击/刷新重放：同一 client_request_id → 同一 attempt
        replay = await c.post(f"/api/commercial/productions/{production_id}/generate", json={
            "unit_key": unit["unit_key"], "quote_id": quote_ids[unit["unit_key"]],
            "client_request_id": client_req, "drive": True,
        })
        assert replay.status_code == 202
        assert replay.json()["attempt_id"] == body["attempt_id"]
        assert replay.json()["idempotent_replay"] is True

    # 6) 逐镜审核（八维全过）
    for unit_key, attempt_id in attempt_ids.items():
        resp = await c.post(f"/api/commercial/attempts/{attempt_id}/review", json={
            "dimensions": {
                "人物身份": "PASS", "商品准确": "PASS", "音色": "PASS", "台词": "PASS",
                "口型": "PASS", "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS",
            },
            "speech_required": True,
        })
        assert resp.status_code == 200 and resp.json()["overall"] == "REVIEW_APPROVED"

    # 7) 合成（采用区间=各单元全部时长）+ 下载
    selections = []
    detail = (await c.get(f"/api/commercial/productions/{production_id}")).json()
    units_plan = detail["plan"]["units"]
    by_attempt = {a["id"]: a for a in detail["attempts"]}
    for unit in units_plan:
        for a in detail["attempts"]:
            pass
    # 用 attempt 输出整段作为采用区间（Mock 片段 5s，单元时长 ≤5s）
    for attempt_id in attempt_ids.values():
        selections.append({"attempt_id": attempt_id, "ranges": [[0, 4000]]})
    resp = await c.post(f"/api/commercial/productions/{production_id}/compose", json={
        "selections": selections, "subtitles": True,
    })
    assert resp.status_code == 200, resp.text
    export_id = resp.json()["export_id"]
    dl = await c.get(f"/api/commercial/exports/{export_id}/download")
    assert dl.status_code == 200 and dl.content[:4] != b""
    return {"production_id": production_id, "export_id": export_id, "attempt_ids": attempt_ids}


@pytest.mark.asyncio
async def test_mock_e2e_template_reuse_two_material_sets(client, admin, db_session, tmp_path) -> None:
    """上传参考视频→解析→模板T1→C1→同模板换素材C2；仅外部供应商被模拟。"""
    # 0) 预算池（admin）
    resp = await client.post("/api/commercial/budget", json={"total_usd": "50.00"})
    assert resp.status_code == 200, resp.text

    # 1) 参考视频上传 + Mock 解析
    video_id = await _upload(client, "ref.mp4", _video_bytes(tmp_path / "ref.mp4", 30),
                             "reference_source_video", "video/mp4")
    resp = await client.get(f"/api/commercial/assets/{video_id}")
    source_meta = resp.json()
    assert source_meta["duration_ms"] and source_meta["duration_ms"] >= 2500
    # 创建 CvReferenceSource 记录（首版由 sources 服务在内部登记；测试直接补一条登记行）
    from app.models_commercial import CvReferenceSource

    asset = await db_session.get(CvMediaAsset, video_id)
    source = CvReferenceSource(
        team_id=None, media_asset_id=video_id, duration_ms=asset.duration_ms,
        origin_note="E2E 参考片", uploaded_by=admin.id, status="probed",
    )
    db_session.add(source)
    await db_session.flush()

    resp = await client.post(f"/api/commercial/sources/{source.id}/analyze")
    assert resp.status_code == 202, resp.text
    analysis = resp.json()
    assert analysis["status"] == "completed" and analysis["mock"] is True
    run_id = analysis["analysis_run_id"]

    resp = await client.get(f"/api/commercial/analyses/{run_id}")
    shots = resp.json()["result"]["shots"]
    assert len(shots) == 3

    # 2) 模板 T1（人工校准=直接采用解析结构）
    resp = await client.post("/api/commercial/templates", json={
        "name": "E2E-问题展示引导", "analysis_run_id": run_id, "shots": shots,
    })
    assert resp.status_code == 200, resp.text
    template_version_id = resp.json()["version_id"]

    # 3) 两套素材
    voice1 = _mp3_bytes(tmp_path / "v1.mp3")
    actor_v1, voice_p1, voice_asset_1 = await _make_actor(client, "达人一号", tmp_path, voice1)
    voice2 = _mp3_bytes(tmp_path / "v2.mp3")
    actor_v2, voice_p2, voice_asset_2 = await _make_actor(client, "达人二号", tmp_path, voice2)
    p1_img = await _upload(client, "p1.png", _png_bytes(), "owned_product_image", "image/png")
    p2_img = await _upload(client, "p2.png", _png_bytes(), "owned_product_image", "image/png")

    async def _product(name: str, img: int, claim: str) -> int:
        resp = await client.post("/api/commercial/products", json={
            "name": name, "form": "贴片", "image_asset_ids": [img],
            "claims": [{"claim_id": f"{name}-c1", "text": claim, "approved": False, "source": "测试"}],
            "forbidden_phrases": [], "allowed_actions": ["贴敷手背展示"],
        })
        assert resp.status_code == 200, resp.text
        vid = resp.json()["product_version_id"]
        # 审核：服务端强制 approved=False，需手动审核后才可用于台词
        from app.models_commercial import CvProductVersion
        version = await db_session.get(CvProductVersion, vid)
        version.claims = [{**c, "approved": True} for c in (version.claims or [])]
        await db_session.commit()
        return vid

    p1 = await _product("P1贴片", p1_img, "贴敷八小时持久清凉")
    p2 = await _product("P2贴片", p2_img, "温和不刺激敏感肌可用")

    # 4) C1：第一套素材
    c1 = await _run_pipeline(
        client, tmp_path, template_version_id=template_version_id,
        actor_version_id=actor_v1, voice_profile_id=voice_p1, product_version_id=p1,
        claim_text="贴敷八小时持久清凉", old_claim="温和不刺激敏感肌可用", tag="C1",
    )

    # 5) C2：同模板换第二套素材（不重新解析、不上传原片）
    analysis_runs_before = (await db_session.execute(
        select(func.count()).select_from(CvAnalysisRun)
    )).scalar_one()
    c2 = await _run_pipeline(
        client, tmp_path, template_version_id=template_version_id,
        actor_version_id=actor_v2, voice_profile_id=voice_p2, product_version_id=p2,
        claim_text="温和不刺激敏感肌可用", old_claim="贴敷八小时持久清凉", tag="C2",
    )
    analysis_runs_after = (await db_session.execute(
        select(func.count()).select_from(CvAnalysisRun)
    )).scalar_one()
    assert analysis_runs_before == analysis_runs_after, "复用模板不得产生新的解析任务"

    # INV-01 E2E：两次作品所有 attempt 参数都不含原片资产
    from app.models_commercial import CvGenerationAttempt

    attempts = (await db_session.execute(
        select(CvGenerationAttempt).where(
            CvGenerationAttempt.production_id.in_([c1["production_id"], c2["production_id"]])
        )
    )).scalars().all()
    assert attempts
    for attempt in attempts:
        params = attempt.params_json or {}
        used = set(params.get("actor_image_asset_ids") or []) | set(params.get("product_image_asset_ids") or []) | set(params.get("voice_reference_asset_ids") or [])
        assert video_id not in used, "原片资产出现在生成参数中（INV-01 违规）"

    # 费用台账：两次作品的 Mock 花费都已如实入账（P1-5 后 Mock 确定性本地价
    # 生成即结算：pending 可为 0，但总费用绝不写 0）
    detail2 = (await client.get(f"/api/commercial/productions/{c2['production_id']}")).json()
    assert detail2["costs"]["mock"] is True
    assert detail2["costs"]["total_usd"] not in ("", "0", "0.00")


@pytest.mark.asyncio
async def test_e2e_cross_user_permission(client, db_session) -> None:
    """非管理员调用管理操作：403（服务端校验，非前端隐藏）。"""
    stranger = await make_user(db_session)
    app = client._transport.app  # type: ignore[attr-defined]

    async def override_stranger():
        return await db_session.get(User, stranger.id, populate_existing=True)

    app.dependency_overrides[get_current_user] = override_stranger
    resp = await client.post("/api/commercial/budget", json={"total_usd": "10.00"})
    assert resp.status_code == 403
    # 未登录：移除覆盖，走真实鉴权依赖 → 401
    app.dependency_overrides.pop(get_current_user, None)
    resp = await client.get("/api/commercial/templates")
    assert resp.status_code == 401
