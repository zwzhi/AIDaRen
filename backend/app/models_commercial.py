"""商业模板业务域（commercial）ORM 模型。

按任务书 §11：新业务实体使用 cv_ 前缀；与底座 users/teams/TaskRun 通过
真实 FK 关联，不把商业项目 ID 塞进原 projects.id 外键。
"""
from __future__ import annotations

from datetime import datetime

from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
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
    # Deterministic source-frame lineage.  ``source_time_ms`` is only set for
    # frames extracted from a reference video, while ``source_metadata`` keeps
    # extractor details extensible without changing the asset identity.
    source_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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


class CvActor(Base):
    """我方达人档案（§6.1）。"""

    __tablename__ = "cv_actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvActorVersion(Base):
    """达人版本：形象图集与外观快照，作品固定引用版本。"""

    __tablename__ = "cv_actor_versions"
    __table_args__ = (
        UniqueConstraint("actor_id", "version", name="uq_cv_actor_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("cv_actors.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="published")
    image_asset_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # int 列表
    appearance_desc: Mapped[str] = mapped_column(Text, default="")
    wardrobe_desc: Mapped[str] = mapped_column(Text, default="")
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvVoiceProfile(Base):
    """授权音色：归属达人 + 音频资产 + 授权期限（INV-02）。"""

    __tablename__ = "cv_voice_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("cv_actors.id"), index=True)
    audio_asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    pronunciation_notes: Mapped[str] = mapped_column(Text, default="")
    authorized_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|revoked
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvProduct(Base):
    """商品档案（§6.2）。"""

    __tablename__ = "cv_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvProductVersion(Base):
    """商品版本：图片/规格/审核卖点/禁止表述/允许展示动作快照。"""

    __tablename__ = "cv_product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_cv_product_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("cv_products.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    form: Mapped[str] = mapped_column(String(32), default="")  # 瓶装|贴片|盒装|...
    specs_text: Mapped[str] = mapped_column(Text, default="")
    image_asset_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    claims: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [{claim_id,text,approved,source}]
    forbidden_phrases: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allowed_actions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CvCostQuote(Base):
    """报价快照（§10.2）：绑定完整参数指纹，参数变化即失效。"""

    __tablename__ = "cv_cost_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    provider_id: Mapped[str] = mapped_column(String(32), default="atlas")
    model_id: Mapped[str] = mapped_column(String(96))
    capability_version: Mapped[str] = mapped_column(String(32), default="")
    request_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    resolution_id: Mapped[str] = mapped_column(String(16), default="")
    requested_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    estimated_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    price_source: Mapped[str] = mapped_column(String(64), default="")
    provider_payload_redacted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fx_rate_label: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replication_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_replication_projects.id"), nullable=True, index=True
    )
    script_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_script_versions.id"), nullable=True, index=True
    )
    anchor_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_anchor_sets.id"), nullable=True, index=True
    )
    voice_render_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_voice_renders.id"), nullable=True, index=True
    )
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvBudgetPool(Base):
    """共享预算池（首版单池）：可用 = total - settled - reserved。"""

    __tablename__ = "cv_budget_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="default")
    scope: Mapped[str] = mapped_column(String(8), default="mock")  # mock|real：演示预算与真实授权隔离
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @classmethod
    async def ensure_default(cls, db, *, total: Decimal, created_by: int,
                             scope: str = "mock") -> "CvBudgetPool":
        pool = (await db.execute(
            __import__("sqlalchemy").select(cls).where(cls.name == "default", cls.scope == scope)
        )).scalar_one_or_none()
        if pool is None:
            pool = cls(name="default", scope=scope, total_amount=total, created_by=created_by)
            db.add(pool)
            await db.flush()
        return pool


class CvBudgetReservation(Base):
    """一次批准的预算预留（并发安全：池行条件更新）。"""

    __tablename__ = "cv_budget_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("cv_budget_pools.id"), index=True)
    # 原子预留路径可在报价落库前占额度（如管理员手工预留），允许空引用
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("cv_cost_quotes.id"), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="reserved")  # reserved|settled|released
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvGenerationAttempt(Base):
    """生成尝试：幂等键 + 参数哈希 + 状态机（§9.2 的持久层）。"""

    __tablename__ = "cv_generation_attempts"
    __table_args__ = (
        UniqueConstraint("client_request_id", name="uq_cv_attempt_client_request"),
        Index("ix_cv_attempt_unit", "generation_unit_id", "attempt_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_id: Mapped[int | None] = mapped_column(Integer, index=True)
    generation_unit_id: Mapped[int | None] = mapped_column(Integer, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    client_request_id: Mapped[str] = mapped_column(String(128), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    # 已确认制作计划参数快照（报价与生成同源；fingerprint 即其哈希）
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("cv_cost_quotes.id"), nullable=True)
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("cv_budget_reservations.id"), nullable=True)
    replication_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_replication_projects.id"), nullable=True, index=True
    )
    script_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_script_versions.id"), nullable=True, index=True
    )
    anchor_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_anchor_sets.id"), nullable=True, index=True
    )
    voice_render_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_voice_renders.id"), nullable=True, index=True
    )
    preview_or_final: Mapped[str] = mapped_column(String(16), default="preview")
    # §9.2 状态
    status: Mapped[str] = mapped_column(String(32), default="APPROVED", index=True)
    provider_prediction_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    output_asset_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CvUsageLedger(Base):
    """Atlas 原币账本（§10.4）：NUMERIC(20,8)，绝不用 float/fen。

    event_key 标识业务事件（generation.pending / generation.settled），
    (attempt_ref, event_key) 唯一 → 同一业务事件幂等入账，不重复累计。
    """

    __tablename__ = "cv_usage_ledger"
    __table_args__ = (
        Index("uq_cv_ledger_attempt_event", "attempt_ref", "event_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_ref: Mapped[str] = mapped_column(String(64), index=True)
    provider_id: Mapped[str] = mapped_column(String(32), default="atlas")
    model_id: Mapped[str] = mapped_column(String(96), default="")
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    amount_cny: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    settlement_status: Mapped[str] = mapped_column(String(24), default="SETTLEMENT_PENDING", index=True)
    event_key: Mapped[str] = mapped_column(String(64), default="")
    usage_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reconciled_manually: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvReview(Base):
    """逐镜审核记录（§15.1）：只追加、不覆盖，审核人留痕。"""

    __tablename__ = "cv_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("cv_generation_attempts.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(32))
    verdict: Mapped[str] = mapped_column(String(16))  # PASS|FAIL|NEEDS_REVIEW|NOT_APPLICABLE
    reason: Mapped[str] = mapped_column(Text, default="")
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvProviderMediaHandle(Base):
    """服务商侧素材句柄：内部资产 → 上传句柄/有效期/来源（§8.6）。

    短期上游 URL 绝不当永久资产；过期后由刷新逻辑重新上传。
    """

    __tablename__ = "cv_provider_media_handles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="atlas")
    purpose: Mapped[str] = mapped_column(String(32), default="generation")  # 生成用途
    handle: Mapped[str] = mapped_column(String(255))
    upstream_url: Mapped[str] = mapped_column(String(1024), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvProduction(Base):
    """作品：模板版本 + 达人/音色/商品快照 + 制作计划（§11.1）。"""

    __tablename__ = "cv_productions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_version_id: Mapped[int] = mapped_column(ForeignKey("cv_template_versions.id"), index=True)
    actor_version_id: Mapped[int] = mapped_column(ForeignKey("cv_actor_versions.id"), index=True)
    voice_profile_id: Mapped[int] = mapped_column(ForeignKey("cv_voice_profiles.id"), index=True)
    product_version_id: Mapped[int] = mapped_column(ForeignKey("cv_product_versions.id"), index=True)
    allow_cross_actor_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    dialogue_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    marketing_goal: Mapped[str] = mapped_column(String(255), default="")
    locked_dialogue: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_duration_ms: Mapped[int] = mapped_column(Integer, default=30_000)
    resolution_id: Mapped[str] = mapped_column(String(16), default="768p")
    aspect_ratio: Mapped[str] = mapped_column(String(8), default="9:16")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    # 制作计划快照：adapted shots + generation units + adoption ranges
    plan_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CvReplicationProject(Base):
    """参考驱动复刻项目：与最终商业作品一对一。"""

    __tablename__ = "cv_replication_projects"
    __table_args__ = (
        UniqueConstraint("production_id", name="uq_cv_replication_production"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_id: Mapped[int] = mapped_column(ForeignKey("cv_productions.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="structural_rewrite")
    route_reason: Mapped[str] = mapped_column(Text, default="")
    route_confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    rights_status: Mapped[str] = mapped_column(String(24), default="pending")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    current_script_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_anchor_set_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_voice_render_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CvShotGraph(Base):
    """Versioned, externally ordered shot graph produced from a source video."""

    __tablename__ = "cv_shot_graphs"
    __table_args__ = (
        UniqueConstraint("replication_project_id", "revision", "shot_key", name="uq_cv_shot_graph_revision_key"),
        Index("ix_cv_shot_graph_project_status", "replication_project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(
        ForeignKey("cv_replication_projects.id"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    shot_key: Mapped[str] = mapped_column(String(96))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(64), default="")
    complexity: Mapped[str] = mapped_column(String(24), default="simple")
    camera_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    composition_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    action_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    emotion_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    product_presence: Mapped[str] = mapped_column(String(16), default="unknown")
    product_confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    product_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    anchor_candidates_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_span_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_version: Mapped[str] = mapped_column(String(32), default="1")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvScriptVersion(Base):
    """Immutable script revision tied to a shot graph revision."""

    __tablename__ = "cv_script_versions"
    __table_args__ = (
        UniqueConstraint("replication_project_id", "version", name="uq_cv_script_version"),
        Index("ix_cv_script_project_status", "replication_project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(
        ForeignKey("cv_replication_projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    shot_graph_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="structural_rewrite")
    script_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    claim_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="1")
    model_id: Mapped[str] = mapped_column(String(96), default="")
    model_version: Mapped[str] = mapped_column(String(96), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvAnchorSet(Base):
    """Immutable candidate or approved anchor-frame revision."""

    __tablename__ = "cv_anchor_sets"
    __table_args__ = (
        UniqueConstraint("replication_project_id", "version", name="uq_cv_anchor_set_version"),
        Index("ix_cv_anchor_set_project_status", "replication_project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(
        ForeignKey("cv_replication_projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    shot_graph_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="structural_rewrite")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvAnchorFrame(Base):
    """Single source or edited frame with complete lineage."""

    __tablename__ = "cv_anchor_frames"
    __table_args__ = (
        UniqueConstraint("anchor_set_id", "shot_key", "sequence", name="uq_cv_anchor_frame_sequence"),
        Index("ix_cv_anchor_frame_set_shot", "anchor_set_id", "shot_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anchor_set_id: Mapped[int] = mapped_column(ForeignKey("cv_anchor_sets.id"), index=True)
    shot_key: Mapped[str] = mapped_column(String(96))
    sequence: Mapped[int] = mapped_column(Integer)
    time_ms: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32), default="source")
    source_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cv_media_assets.id"), nullable=True, index=True)
    edited_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cv_media_assets.id"), nullable=True, index=True)
    parent_anchor_id: Mapped[int | None] = mapped_column(ForeignKey("cv_anchor_frames.id"), nullable=True, index=True)
    actor_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_actor_versions.id"), nullable=True)
    product_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_product_versions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="deterministic")
    model_id: Mapped[str] = mapped_column(String(96), default="")
    model_version: Mapped[str] = mapped_column(String(96), default="")
    prompt_hash: Mapped[str] = mapped_column(String(64), default="")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), default="pending")
    review_status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvVoiceRender(Base):
    """Versioned voice render tied to script input."""

    __tablename__ = "cv_voice_renders"
    __table_args__ = (Index("ix_cv_voice_render_project_status", "replication_project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(ForeignKey("cv_replication_projects.id"), index=True)
    script_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_script_versions.id"), nullable=True, index=True)
    voice_profile_id: Mapped[int | None] = mapped_column(ForeignKey("cv_voice_profiles.id"), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(String(96), default="")
    model_version: Mapped[str] = mapped_column(String(96), default="")
    audio_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cv_media_assets.id"), nullable=True, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    script_hash: Mapped[str] = mapped_column(String(64), default="")
    rights_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("cv_rights_evidence.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvSubtitleVersion(Base):
    """Subtitle timeline revision shared by preview and final export."""

    __tablename__ = "cv_subtitle_versions"
    __table_args__ = (Index("ix_cv_subtitle_project_status", "replication_project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(ForeignKey("cv_replication_projects.id"), index=True)
    script_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_script_versions.id"), nullable=True, index=True)
    voice_render_id: Mapped[int | None] = mapped_column(ForeignKey("cv_voice_renders.id"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    subtitles_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    style_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvRightsEvidence(Base):
    """权利凭证快照，支持视频、人物、声音、音乐和商品素材。"""

    __tablename__ = "cv_rights_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_replication_projects.id"), nullable=True, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    holder_name: Mapped[str] = mapped_column(String(160), default="")
    scope: Mapped[str] = mapped_column(String(64), default="")
    territory: Mapped[str] = mapped_column(String(64), default="")
    channels: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_media_assets.id"), nullable=True, index=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvExport(Base):
    """成片导出：选定 attempt 与采用区间快照 + 母版/字幕版路径。"""

    __tablename__ = "cv_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_id: Mapped[int] = mapped_column(ForeignKey("cv_productions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="master")  # master|partial_preview
    master_path: Mapped[str] = mapped_column(String(512))
    subtitled_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_adopt_ms: Mapped[int] = mapped_column(Integer, default=0)
    selections_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    srt_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 字幕校对状态与编辑留痕（烧录时写入；历史导出默认未校对草稿）
    srt_aligned: Mapped[bool] = mapped_column(Boolean, default=False)
    srt_edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    srt_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    script_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_script_versions.id"), nullable=True, index=True
    )
    anchor_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_anchor_sets.id"), nullable=True, index=True
    )
    voice_render_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_voice_renders.id"), nullable=True, index=True
    )
    quality_check_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
