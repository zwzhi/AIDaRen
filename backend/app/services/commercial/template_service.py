"""模板版本化：发布校验、不可变版本与实例化（任务书 §5.3/§5.4）。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models_commercial import CvMediaAsset, CvReferenceSource, CvTemplate, CvTemplateVersion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TemplatePublishError(Exception):
    """发布校验失败（版本冲突/结构非法）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_REQUIRED_SHOT_FIELDS = ("shot_id", "start_ms", "end_ms")


def _validate_draft(draft_payload: dict[str, Any], *, source_duration_ms: int | None = None) -> None:
    shots = draft_payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise TemplatePublishError("TEMPLATE_STRUCTURE_INVALID", "模板至少包含一个镜头")
    previous_end = 0
    for shot in shots:
        if not isinstance(shot, dict) or any(f not in shot for f in _REQUIRED_SHOT_FIELDS):
            raise TemplatePublishError("TEMPLATE_STRUCTURE_INVALID", f"镜头缺少必需字段：{_REQUIRED_SHOT_FIELDS}")
        start, end = shot.get("start_ms"), shot.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise TemplatePublishError("TEMPLATE_TIME_INVALID", "镜头时间码必须是整数毫秒")
        if start < 0 or end <= start:
            raise TemplatePublishError("TEMPLATE_TIME_INVALID", "镜头时间范围非法")
        if start < previous_end:
            raise TemplatePublishError("TEMPLATE_TIME_INVALID", "镜头时间范围重叠")
        if source_duration_ms is not None and end > source_duration_ms:
            raise TemplatePublishError("TEMPLATE_TIME_INVALID", "镜头超出原片时长")
        previous_end = end


async def publish_template(
    db: AsyncSession, *, template: CvTemplate, draft_payload: dict[str, Any],
    expected_version: int, publisher_id: int,
    analysis_run_id: int | None = None,
    source_duration_ms: int | None = None,
) -> CvTemplateVersion:
    """校验草稿并冻结为不可变版本；expected_version 防并发覆盖。

    - 版本号 = 模板 current_version + 1；不匹配 → 冲突（调用方返回 409 语义）；
    - 同版本号已存在（重复提交）→ 冲突；
    - 发布后模板 current_version 前移；历史版本保持 published 不改写。
    """
    _validate_draft(draft_payload, source_duration_ms=source_duration_ms)
    next_version = int(template.current_version or 0) + 1
    if int(expected_version) != next_version:
        raise TemplatePublishError(
            "TEMPLATE_VERSION_CONFLICT",
            f"expected_version={expected_version} 与下一个版本 {next_version} 不一致",
        )
    exists = (await db.execute(
        select(CvTemplateVersion.id).where(
            CvTemplateVersion.template_id == template.id,
            CvTemplateVersion.version == next_version,
        )
    )).scalar_one_or_none()
    if exists is not None:
        raise TemplatePublishError("TEMPLATE_VERSION_CONFLICT", f"版本 {next_version} 已发布，不可改写")
    version = CvTemplateVersion(
        template_id=template.id, version=next_version, status="published",
        structure_json=draft_payload, source_analysis_run_id=analysis_run_id,
        published_by=publisher_id,
    )
    db.add(version)
    template.current_version = next_version
    await db.flush()
    return version


async def instantiate_template(
    db: AsyncSession, version: CvTemplateVersion
) -> dict[str, Any]:
    """从已发布版本生成实例化计划骨架（不读原片；source_available 标明复查可用性）。"""
    structure = dict(version.structure_json or {})
    return {
        "template_version_id": version.id,
        "version": version.version,
        "shots": list(structure.get("shots") or []),
        "variables": list(structure.get("variables") or []),
        "source_available": await source_availability(db, version),
    }


async def source_availability(db: AsyncSession, version: CvTemplateVersion) -> bool:
    """原片复查可用性：分析链上的源未被删除且资产未撤销。"""
    if version.source_analysis_run_id is None:
        return False
    from app.models_commercial import CvAnalysisRun

    run = await db.get(CvAnalysisRun, version.source_analysis_run_id)
    if run is None:
        return False
    source = await db.get(CvReferenceSource, run.source_id)
    if source is None or source.status == "deleted":
        return False
    asset = await db.get(CvMediaAsset, source.media_asset_id)
    return asset is not None and asset.rights_status != "revoked"
