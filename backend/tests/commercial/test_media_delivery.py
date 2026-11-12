# -*- coding: utf-8 -*-
"""素材交付适配：上传成功/失败/过期/刷新（Mock 与注入 transport）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from app.models_commercial import CvMediaAsset, CvProviderMediaHandle
from app.services.commercial import media_delivery
from app.services.providers.atlas.media import UploadFailedError
from tests.conftest import make_user


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


async def _asset(db, owner) -> CvMediaAsset:
    import secrets

    asset = CvMediaAsset(
        kind="image", object_key=f"owned_product_image/t/{secrets.token_hex(6)}.png",
        sha256="d" * 64, mime="image/png", size_bytes=8,
        source_role="owned_product_image", uploaded_by=owner.id,
    )
    db.add(asset)
    await db.flush()
    from app.services.commercial.storage import asset_disk_path

    path = asset_disk_path(asset.object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return asset


@pytest.mark.asyncio
async def test_upload_success_records_handle(db_session, owner) -> None:
    asset = await _asset(db_session, owner)

    def handler(request):
        return httpx.Response(200, json={"id": "media-abc", "url": "https://cdn.example.test/m"})

    handle = await media_delivery.get_or_upload_handle(
        db_session, asset, base_url="https://api.atlascloud.ai", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    assert handle.handle == "media-abc"
    assert handle.source_sha256  # 来源哈希留痕


@pytest.mark.asyncio
async def test_nested_atlas_upload_response_persists_download_url(db_session, owner) -> None:
    asset = await _asset(db_session, owner)

    def handler(request):
        return httpx.Response(200, json={"code": 200, "data": {
            "download_url": "https://cdn.example.test/atlas-upload.jpg",
            "filename": "atlas-upload.jpg",
        }})

    handle = await media_delivery.get_or_upload_handle(
        db_session, asset, base_url="https://api.atlascloud.ai", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    assert handle.handle == "atlas-upload.jpg"
    assert handle.upstream_url == "https://cdn.example.test/atlas-upload.jpg"


@pytest.mark.asyncio
async def test_upload_failure_raises(db_session, owner) -> None:
    asset = await _asset(db_session, owner)

    def handler(request):
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(UploadFailedError):
        await media_delivery.get_or_upload_handle(
            db_session, asset, base_url="https://api.atlascloud.ai", api_key="k",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_expired_handle_refreshed(db_session, owner) -> None:
    """句柄过期 → 重新上传获取新句柄，旧记录保留。"""
    asset = await _asset(db_session, owner)
    stale = CvProviderMediaHandle(
        asset_id=asset.id, provider="atlas", handle="media-old",
        expires_at=datetime.now(UTC) - timedelta(minutes=1), source_sha256="x",
    )
    db_session.add(stale)
    await db_session.flush()

    def handler(request):
        return httpx.Response(200, json={"id": "media-new"})

    fresh = await media_delivery.get_or_upload_handle(
        db_session, asset, base_url="https://api.atlascloud.ai", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    assert fresh.handle == "media-new"
    assert stale.handle == "media-old"  # 历史留痕不删


@pytest.mark.asyncio
async def test_mock_handle_no_network(db_session, owner) -> None:
    """Mock 模式：句柄带 MOCK- 前缀、有 TTL、零网络调用。"""
    asset = await _asset(db_session, owner)

    def handler(request):  # pragma: no cover —— 不应被调用
        raise AssertionError("mock 模式不得发起网络请求")

    handle = await media_delivery.get_or_upload_handle(
        db_session, asset, base_url="https://api.atlascloud.ai", api_key="k",
        transport=httpx.MockTransport(handler), mock=True,
    )
    assert handle.handle.startswith("MOCK-media-")
    assert handle.expires_at is not None


@pytest.mark.asyncio
async def test_analysis_only_asset_rejected_in_delivery(db_session, owner) -> None:
    """交付路径复用资产策略：原片关键帧不能拿到生成句柄（INV-01）。"""
    import secrets

    frame = CvMediaAsset(
        kind="image", object_key=f"reference_source_frame/t/{secrets.token_hex(6)}.png",
        sha256="e" * 64, mime="image/png", size_bytes=8,
        source_role="reference_source_frame", uploaded_by=owner.id,
    )
    db_session.add(frame)
    await db_session.flush()
    from app.services.commercial.storage import asset_disk_path

    path = asset_disk_path(frame.object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(media_delivery.MediaDeliveryError) as exc:
        await media_delivery.ensure_generation_handles(
            db_session, [frame.id], base_url="https://api.atlascloud.ai",
            api_key="k", mock=True,
        )
    assert exc.value.code == "SOURCE_REFERENCE_FORBIDDEN"
