# -*- coding: utf-8 -*-
"""T02｜商业域媒体安全：私有存储、越权下载、伪 MIME、角色与授权边界。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from tests.conftest import make_user

SOURCES_URL = "/api/commercial/sources"


def _make_video(path: Path, seconds: int = 1) -> Path:
    """用 ffmpeg testsrc 生成可探测的极小 mp4（离线、确定性）。"""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=160x120:rate=10",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    return _make_video(tmp_path_factory.mktemp("media") / "sample.mp4", seconds=2)


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


@pytest_asyncio.fixture
async def stranger(db_session):
    return await make_user(db_session)


@pytest_asyncio.fixture
async def api_client(db_session, owner):
    """带登录态覆盖的商业域测试应用。"""
    app = FastAPI()
    app.include_router(commercial_router, prefix="/api/commercial")

    async def override_db():
        yield db_session

    async def override_user():
        return await db_session.get(User, owner.id, populate_existing=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _upload(client: httpx.AsyncClient, path: Path, role: str = "reference_source_video",
                  filename: str | None = None, content: bytes | None = None,
                  content_type: str = "video/mp4") -> httpx.Response:
    if content is not None:
        files = {"file": (filename or path.name, content, content_type)}
    else:
        files = {"file": (filename or path.name, path.read_bytes(), content_type)}
    data = {"source_role": role, "rights_declaration": "测试素材，有权使用"}
    return await client.post(SOURCES_URL, files=files, data=data)


# ---------------------------------------------------------------- 上传与校验
@pytest.mark.asyncio
async def test_upload_reference_video_returns_internal_id(api_client, sample_video) -> None:
    resp = await _upload(api_client, sample_video)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] > 0
    assert body["source_role"] == "reference_source_video"
    assert body["mime"].startswith("video/")
    assert body["duration_ms"] >= 1500
    # 不暴露本地路径
    assert "object_key" not in body and "path" not in str(body)


@pytest.mark.asyncio
async def test_fake_mime_rejected(api_client, tmp_path) -> None:
    """文本文件改名 .mp4：真实 MIME 探测失败必须拒绝。"""
    resp = await _upload(
        api_client, tmp_path / "fake.mp4", content=b"this is definitely not a video" * 10,
    )
    assert resp.status_code == 422
    assert "媒体" in resp.json()["detail"] or "格式" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_role_rejected(api_client, sample_video) -> None:
    resp = await _upload(api_client, sample_video, role="evil_role")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_oversize_duration_clear_message(api_client, tmp_path, monkeypatch) -> None:
    """超过 180 秒上限：给出明确提示，不是静默截短（用小上限模拟）。"""
    from app import config
    monkeypatch.setattr(config.get_settings(), "commercial_max_reference_duration_seconds", 1)
    path = _make_video(tmp_path / "long.mp4", seconds=2)
    resp = await _upload(api_client, path)
    assert resp.status_code == 422
    assert "时长" in resp.json()["detail"]


# ---------------------------------------------------------------- 下载权限
@pytest.mark.asyncio
async def test_owner_can_download(api_client, sample_video) -> None:
    up = await _upload(api_client, sample_video)
    asset_id = up.json()["id"]
    resp = await api_client.get(f"/api/commercial/assets/{asset_id}/download")
    assert resp.status_code == 200
    assert resp.content[:4]  # 非空文件


@pytest.mark.asyncio
async def test_cross_team_download_denied(db_session, api_client, sample_video, stranger) -> None:
    """其他团队/用户访问资源 ID：404，包括试听与下载路径。"""
    from app.models_teams import Team, TeamMember

    up = await _upload(api_client, sample_video)
    asset_id = up.json()["id"]
    # 将资产绑定到 owner 的团队
    from app.models_commercial import CvMediaAsset
    asset = await db_session.get(CvMediaAsset, asset_id)
    team = Team(name="t-a", owner_user_id=asset.uploaded_by)
    db_session.add(team)
    await db_session.flush()
    asset.team_id = team.id
    db_session.add(TeamMember(team_id=team.id, user_id=asset.uploaded_by, role="owner"))
    await db_session.commit()

    # stranger 不在该团队 → 404（不泄露存在性）
    app = api_client._transport.app  # type: ignore[attr-defined]
    async def override_stranger():
        return await db_session.get(User, stranger.id, populate_existing=True)
    app.dependency_overrides[get_current_user] = override_stranger
    resp = await api_client.get(f"/api/commercial/assets/{asset_id}/download")
    assert resp.status_code == 404
    meta = await api_client.get(f"/api/commercial/assets/{asset_id}")
    assert meta.status_code == 404


@pytest.mark.asyncio
async def test_analysis_only_asset_blocked_for_generation(api_client, sample_video, db_session) -> None:
    """analysis_only 角色及其派生不能进入生成素材位。"""
    from app.services.commercial.asset_policy import CommercialAssetPolicyError, validate_asset_for_generation

    up = await _upload(api_client, sample_video)
    asset_id = up.json()["id"]
    from app.models_commercial import CvMediaAsset
    asset = await db_session.get(CvMediaAsset, asset_id)
    with pytest.raises(CommercialAssetPolicyError) as exc:
        await validate_asset_for_generation(db_session, asset)
    assert "SOURCE_REFERENCE_FORBIDDEN" in str(exc.value) or exc.value.code == "SOURCE_REFERENCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_expired_rights_block_generation(api_client, db_session, tmp_path) -> None:
    """授权过期后：上传可留档，但生成校验必须拦截。"""
    from datetime import datetime, timedelta, timezone

    from app.models_commercial import CvMediaAsset
    from app.services.commercial.asset_policy import CommercialAssetPolicyError, validate_asset_for_generation

    path = tmp_path / "img.png"
    import struct, zlib
    def _png(width=2, height=2) -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.write_bytes(_png())

    resp = await _upload(api_client, path, role="owned_actor_image", content_type="image/png")
    assert resp.status_code == 200, resp.text
    asset = await db_session.get(CvMediaAsset, resp.json()["id"])
    assert await validate_asset_for_generation(db_session, asset) is None  # 未过期可用

    asset.authorized_until = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    with pytest.raises(CommercialAssetPolicyError):
        await validate_asset_for_generation(db_session, asset)
