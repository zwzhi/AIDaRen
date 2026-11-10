"""素材交付编排：内部资产 → 校验 → 上传/刷新 → 生成请求句柄（§8.6）。"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import CvMediaAsset, CvProviderMediaHandle
from app.services.providers.atlas.media import UploadFailedError, handle_expired, upload_media

if TYPE_CHECKING:
    pass

# Mock 句柄有效期（短，便于开发中验证过期刷新路径）
_MOCK_HANDLE_TTL = timedelta(minutes=30)


class MediaDeliveryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _asset_bytes(asset: CvMediaAsset) -> bytes:
    from app.services.commercial.storage import asset_disk_path

    path = asset_disk_path(asset.object_key)
    if not path.is_file():
        raise MediaDeliveryError("ASSET_FILE_MISSING", f"素材文件缺失：{asset.id}")
    return path.read_bytes()


async def get_or_upload_handle(
    db: AsyncSession, asset: CvMediaAsset, *,
    base_url: str, api_key: str, transport=None, mock: bool = False,
) -> CvProviderMediaHandle:
    """取得可用上游句柄：有效句柄复用；过期/缺失重新上传并留痕。

    Mock 模式生成 MOCK- 句柄（不碰网络），行为与真实路径一致以便测试
    成功/失败/过期/刷新。
    """
    row = (await db.execute(
        select(CvProviderMediaHandle).where(
            CvProviderMediaHandle.asset_id == asset.id,
            CvProviderMediaHandle.provider == "atlas",
        ).order_by(CvProviderMediaHandle.id.desc())
    )).scalars().first()
    if row is not None and not handle_expired(row):
        return row

    raw = _asset_bytes(asset)
    sha = hashlib.sha256(raw).hexdigest()
    if mock:
        handle = f"MOCK-media-{asset.id}-{sha[:8]}"
        expires = datetime.now(UTC) + _MOCK_HANDLE_TTL
    else:
        result = await upload_media(
            raw, asset.mime, base_url=base_url, api_key=api_key, transport=transport,
        )
        handle = result["handle"]
        raw_expires = result.get("expires_at")
        expires = None
        if raw_expires:
            try:
                expires = datetime.fromisoformat(str(raw_expires).replace("Z", "+00:00"))
            except ValueError:
                expires = None
    fresh = CvProviderMediaHandle(
        asset_id=asset.id, provider="atlas", handle=handle,
        upstream_url="", expires_at=expires, source_sha256=sha,
    )
    db.add(fresh)
    await db.flush()
    return fresh


async def ensure_generation_handles(
    db: AsyncSession, asset_ids: list[int], *, base_url: str, api_key: str,
    transport=None, mock: bool = False,
) -> dict[int, str]:
    """批量取得生成用句柄：先做生成侧资产策略校验（owned_*、授权、血缘）。"""
    from app.services.commercial.asset_policy import (
        CommercialAssetPolicyError,
        validate_asset_for_generation,
    )

    out: dict[int, str] = {}
    for asset_id in asset_ids:
        asset = await db.get(CvMediaAsset, int(asset_id))
        if asset is None:
            raise MediaDeliveryError("ASSET_NOT_FOUND", f"素材不存在：{asset_id}")
        try:
            await validate_asset_for_generation(db, asset)
        except CommercialAssetPolicyError as exc:
            raise MediaDeliveryError(exc.code, exc.message) from exc
        handle = await get_or_upload_handle(
            db, asset, base_url=base_url, api_key=api_key, transport=transport, mock=mock,
        )
        out[int(asset_id)] = handle.handle
    return out


__all__ = [
    "MediaDeliveryError",
    "UploadFailedError",
    "ensure_generation_handles",
    "get_or_upload_handle",
]
