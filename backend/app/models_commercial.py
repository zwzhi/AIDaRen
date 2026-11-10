"""商业模板业务域（commercial）ORM 模型。

按任务书 §11：新业务实体使用 cv_ 前缀；与底座 users/teams/TaskRun 通过
真实 FK 关联，不把商业项目 ID 塞进原 projects.id 外键。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CvMediaAsset(Base):
    """商业域私有媒体资产：原片、关键帧、达人图、授权音色、商品图、场景图等。

    存储在后端管理的私有目录（COMMERCIAL_STORAGE_ROOT），不经 /static 公开；
    下载必须走带权限校验的受控接口。生成入口只接受 owned_* 角色。
    """

    __tablename__ = "cv_media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # image | video | audio
    object_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # 媒体属性（可探测时填写）
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_audio: Mapped[bool | None] = mapped_column(Integer, nullable=True)  # ffprobe 有无音轨
    # 来源角色与派生链（任务书 §5.5）
    source_role: Mapped[str] = mapped_column(String(48), index=True)
    derived_from_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_media_assets.id"), nullable=True, index=True
    )
    # 权利状态与授权范围
    rights_status: Mapped[str] = mapped_column(String(16), default="authorized")
    rights_declaration: Mapped[str] = mapped_column(Text, default="")
    authorized_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvReferenceSource(Base):
    """参考视频登记：只供解析与人工复核，绝不成为生成素材（§5.1）。"""

    __tablename__ = "cv_reference_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="probed")  # probed|deleted
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvAnalysisRun(Base):
    """一次 Gemini 解析任务记录（含缓存键；§5.4）。"""

    __tablename__ = "cv_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("cv_reference_sources.id"), index=True)
    model_id: Mapped[str] = mapped_column(String(96))
    source_sha256: Mapped[str] = mapped_column(String(64))
    cache_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="1")
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|completed|failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvTemplate(Base):
    """商业模板：内容层不可变，编辑产生新草稿、发布新版本（§5.4）。"""

    __tablename__ = "cv_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvTemplateVersion(Base):
    """模板发布版本：结构 JSON 冻结快照，历史作品长期引用。"""

    __tablename__ = "cv_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_cv_template_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("cv_templates.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="published")  # published|revoked
    structure_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_analysis_runs.id"), nullable=True
    )
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
