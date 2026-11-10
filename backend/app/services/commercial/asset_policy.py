"""商业域资产来源角色与授权策略（任务书 §5.5 / INV-01 / INV-02）。

生成入口只接受 owned_* 角色的授权资产；analysis_only（原片/关键帧/音轨）
及其派生、同哈希副本一律拒绝进入生成素材位。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models_commercial import CvMediaAsset

# 来源角色全集（任务书 §5.5）
SOURCE_ROLES: frozenset[str] = frozenset({
    "reference_source_video",
    "reference_source_frame",
    "reference_source_audio",
    "owned_actor_image",
    "owned_voice_reference",
    "owned_product_image",
    "owned_scene_image",
    "owned_generated_frame",
    "output_clip",
})
ANALYSIS_ONLY_ROLES: frozenset[str] = frozenset({
    "reference_source_video",
    "reference_source_frame",
    "reference_source_audio",
})
GENERATION_ALLOWED_ROLES: frozenset[str] = frozenset({
    "owned_actor_image",
    "owned_voice_reference",
    "owned_product_image",
    "owned_scene_image",
    "owned_generated_frame",
})

_MAX_LINEAGE_DEPTH = 10


class CommercialAssetPolicyError(Exception):
    """资产不满足生成/访问策略；code 对应任务书 §11.3 错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _rights_blocked(asset: CvMediaAsset, now: datetime) -> str | None:
    if asset.rights_status == "revoked":
        return "素材授权已被撤销"
    until = asset.authorized_until
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until <= now:
            return "素材授权已过期"
    return None


async def _lineage_has_analysis_only(db: AsyncSession, asset: CvMediaAsset) -> bool:
    """沿 derived_from 链向上追溯（有界），任一祖先是 analysis_only 即命中。"""
    current = asset
    for _ in range(_MAX_LINEAGE_DEPTH):
        parent_id = current.derived_from_asset_id
        if parent_id is None:
            return False
        parent = await db.get(type(current), int(parent_id))
        if parent is None:
            return False
        if parent.source_role in ANALYSIS_ONLY_ROLES:
            return True
        current = parent
    return False


async def _sha_matches_analysis_only(db: AsyncSession, asset: CvMediaAsset) -> bool:
    """同一内容字节已以 analysis_only 角色入库：换名重传不能洗白（INV-01）。"""
    from app.models_commercial import CvMediaAsset as Asset

    stmt = select(Asset.id).where(
        Asset.sha256 == asset.sha256,
        Asset.source_role.in_(tuple(ANALYSIS_ONLY_ROLES)),
        Asset.id != asset.id,
    )
    return (await db.scalar(stmt)) is not None


async def validate_asset_for_generation(db: AsyncSession, asset: CvMediaAsset) -> None:
    """校验资产可进入生成素材位；不满足时抛 CommercialAssetPolicyError。"""
    if asset.source_role not in SOURCE_ROLES:
        raise CommercialAssetPolicyError("ASSET_ROLE_INVALID", f"未知来源角色：{asset.source_role}")
    if asset.source_role not in GENERATION_ALLOWED_ROLES:
        raise CommercialAssetPolicyError(
            "SOURCE_REFERENCE_FORBIDDEN",
            f"素材角色 {asset.source_role} 仅限分析使用，不能进入生成",
        )
    blocked = _rights_blocked(asset, datetime.now(UTC))
    if blocked:
        raise CommercialAssetPolicyError("ASSET_RIGHTS_EXPIRED", blocked)
    if await _lineage_has_analysis_only(db, asset):
        raise CommercialAssetPolicyError(
            "SOURCE_REFERENCE_FORBIDDEN", "素材派生自原片分析资产，不能进入生成"
        )
    if await _sha_matches_analysis_only(db, asset):
        raise CommercialAssetPolicyError(
            "SOURCE_REFERENCE_FORBIDDEN", "素材内容与原片分析资产相同，不能进入生成"
        )


async def ensure_asset_readable(
    db: AsyncSession, asset: CvMediaAsset, user_id: int, *, is_admin: bool = False
) -> None:
    """下载/元数据访问的团队归属校验；非本团队一律按不存在处理（404 语义）。"""
    if is_admin:
        return
    if asset.uploaded_by == user_id:
        return
    if asset.team_id is not None:
        from app.models_teams import TeamMember

        stmt = select(TeamMember.id).where(
            TeamMember.team_id == asset.team_id,
            TeamMember.user_id == user_id,
            TeamMember.active.is_(True),
        )
        if (await db.scalar(stmt)) is not None:
            return
    raise CommercialAssetPolicyError("ASSET_ACCESS_DENIED", "无权访问该素材")
