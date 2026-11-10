# -*- coding: utf-8 -*-
"""T02｜资产血缘与 SSRF 边界：派生链不得绕过 analysis_only 限制。"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.commercial import router as commercial_router
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from tests.conftest import make_user


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


@pytest_asyncio.fixture
async def api_client(db_session, owner):
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


async def _png_upload(client: httpx.AsyncClient, role: str) -> int:
    import struct, zlib

    def _png(width=2, height=2) -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    resp = await client.post(
        "/api/commercial/sources",
        files={"file": ("a.png", _png(), "image/png")},
        data={"source_role": role, "rights_declaration": "测试"},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


@pytest.mark.asyncio
async def test_renamed_source_frame_cannot_become_owned(api_client, db_session) -> None:
    """同一份原片关键帧字节换名/换角色重新上传为 owned_*：sha256 命中 analysis_only 资产即拒绝。"""
    from app.models_commercial import CvMediaAsset
    from app.services.commercial.asset_policy import CommercialAssetPolicyError, validate_asset_for_generation

    frame_id = await _png_upload(api_client, "reference_source_frame")
    frame = await db_session.get(CvMediaAsset, frame_id)
    # 复制同一字节，伪装成 owned 角色新建资产
    clone = CvMediaAsset(
        team_id=frame.team_id,
        kind="image",
        object_key=frame.object_key + "-clone",
        sha256=frame.sha256,
        mime=frame.mime,
        size_bytes=frame.size_bytes,
        source_role="owned_scene_image",
        uploaded_by=frame.uploaded_by,
        rights_status="authorized",
    )
    db_session.add(clone)
    await db_session.flush()
    with pytest.raises(CommercialAssetPolicyError):
        await validate_asset_for_generation(db_session, clone)


@pytest.mark.asyncio
async def test_derived_lineage_from_analysis_only_blocked(api_client, db_session) -> None:
    """从 analysis_only 资产派生（derived_from）的“owned”资产：血缘追溯后拒绝。"""
    from app.models_commercial import CvMediaAsset
    from app.services.commercial.asset_policy import CommercialAssetPolicyError, validate_asset_for_generation

    source_id = await _png_upload(api_client, "reference_source_frame")
    owned_id = await _png_upload(api_client, "owned_actor_image")
    owned = await db_session.get(CvMediaAsset, owned_id)
    owned.derived_from_asset_id = source_id
    await db_session.commit()
    with pytest.raises(CommercialAssetPolicyError) as exc:
        await validate_asset_for_generation(db_session, owned)
    assert "SOURCE_REFERENCE_FORBIDDEN" in str(exc.value) or exc.value.code == "SOURCE_REFERENCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_owned_image_with_clean_lineage_passes(api_client, db_session) -> None:
    from app.models_commercial import CvMediaAsset
    from app.services.commercial.asset_policy import validate_asset_for_generation

    owned_id = await _png_upload(api_client, "owned_product_image")
    asset = await db_session.get(CvMediaAsset, owned_id)
    assert await validate_asset_for_generation(db_session, asset) is None


# ---------------------------------------------------------------- SSRF 防护
def test_provider_url_guard_blocks_internal_targets() -> None:
    from app.services.providers.atlas.media import SsrfBlockedError, assert_public_https_url

    for bad in (
        "http://api.atlascloud.ai/x",              # 非 https
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",  # 云元数据
        "https://localhost/x",
        "https://[::1]/x",
        "https://192.168.1.10/x",
        "https://10.0.0.5/x",
        "https://172.16.0.9/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(SsrfBlockedError):
            assert_public_https_url(bad)


def test_provider_url_guard_allows_public_https() -> None:
    from app.services.providers.atlas.media import assert_public_https_url

    assert assert_public_https_url("https://api.atlascloud.ai/v1beta/models") is None


@pytest.mark.asyncio
async def test_fetch_rejects_redirect_to_internal() -> None:
    """服务商输出 URL 302 到内网：跟随重定向前校验并阻断。"""
    from app.services.providers.atlas.media import SsrfBlockedError, fetch_url_to_file

    def handler(request: httpx.Request) -> httpx.Response:
        if "evil-redirect" in request.url.host:
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/meta"})
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(handler)
    import tempfile, os
    fd, tmp = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        with pytest.raises(SsrfBlockedError):
            await fetch_url_to_file(
                "https://public-files.example.test/evil-redirect", tmp, transport=transport
            )
    finally:
        os.unlink(tmp)
