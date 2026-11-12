"""Versioned asset models for the next commercial replication slice.

The first commercial tables predate product research, wardrobe and reference
selection.  These models are additive and deliberately keep the old product,
actor and voice rows usable while new workflows migrate to immutable versions.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CvProductVariant(Base):
    __tablename__ = "cv_product_variants"
    __table_args__ = (UniqueConstraint("product_id", "variant_key", name="uq_cv_product_variant_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("cv_products.id"), index=True)
    variant_key: Mapped[str] = mapped_column(String(160), default="default")
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shade_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant_label: Mapped[str] = mapped_column(String(160), default="默认款")
    spec_text: Mapped[str] = mapped_column(Text, default="")
    resolution_status: Mapped[str] = mapped_column(String(24), default="single_variant", index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvProductResearchRun(Base):
    __tablename__ = "cv_product_research_runs"
    __table_args__ = (Index("ix_cv_product_research_product_status", "product_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("cv_products.id"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("cv_product_variants.id"), nullable=True, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_id: Mapped[str] = mapped_column(String(96), default="")
    model_version: Mapped[str] = mapped_column(String(96), default="")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    refresh_reason: Mapped[str] = mapped_column(String(64), default="initial")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvProductSource(Base):
    __tablename__ = "cv_product_sources"
    __table_args__ = (UniqueConstraint("research_run_id", "content_hash", name="uq_cv_product_source_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("cv_product_research_runs.id"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    domain: Mapped[str] = mapped_column(String(255), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_level: Mapped[str] = mapped_column(String(32), default="user_url")
    rights_status: Mapped[str] = mapped_column(String(24), default="reference_only")
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvProductFactCandidate(Base):
    __tablename__ = "cv_product_fact_candidates"
    __table_args__ = (Index("ix_cv_product_fact_candidate_run_field", "research_run_id", "field_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("cv_product_research_runs.id"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("cv_product_variants.id"), nullable=True, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("cv_product_sources.id"), nullable=True, index=True)
    field_name: Mapped[str] = mapped_column(String(96), index=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    conflict_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvProductResearchUsage(Base):
    __tablename__ = "cv_product_research_usage"
    __table_args__ = (UniqueConstraint("research_run_id", name="uq_cv_product_research_usage_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("cv_product_research_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="atlas")
    model_id: Mapped[str] = mapped_column(String(96), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    price_source: Mapped[str] = mapped_column(String(64), default="atlas:usage_estimate")
    raw_usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvProductState(Base):
    __tablename__ = "cv_product_states"
    __table_args__ = (UniqueConstraint("product_version_id", "state_key", name="uq_cv_product_state_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_version_id: Mapped[int] = mapped_column(ForeignKey("cv_product_versions.id"), index=True)
    state_key: Mapped[str] = mapped_column(String(48), index=True)
    label: Mapped[str] = mapped_column(String(96), default="")
    action_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvProductStateAsset(Base):
    __tablename__ = "cv_product_state_assets"
    __table_args__ = (UniqueConstraint("state_id", "asset_id", "role", name="uq_cv_product_state_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("cv_product_states.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    role: Mapped[str] = mapped_column(String(48), default="reference")
    source_type: Mapped[str] = mapped_column(String(32), default="user_upload")
    review_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)


class CvProductCapability(Base):
    __tablename__ = "cv_product_capabilities"
    __table_args__ = (UniqueConstraint("product_version_id", "capability_key", name="uq_cv_product_capability"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_version_id: Mapped[int] = mapped_column(ForeignKey("cv_product_versions.id"), index=True)
    capability_key: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    preconditions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    forbidden_conditions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)


class CvWardrobeItem(Base):
    __tablename__ = "cv_wardrobe_items"
    __table_args__ = (Index("ix_cv_wardrobe_item_scope_status", "scope", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(48), default="other")
    scope: Mapped[str] = mapped_column(String(16), default="personal")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvWardrobeVersion(Base):
    __tablename__ = "cv_wardrobe_versions"
    __table_args__ = (UniqueConstraint("item_id", "version", name="uq_cv_wardrobe_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("cv_wardrobe_items.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str] = mapped_column(String(64), default="")
    material: Mapped[str] = mapped_column(String(96), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rights_status: Mapped[str] = mapped_column(String(24), default="pending")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvWardrobeSet(Base):
    __tablename__ = "cv_wardrobe_sets"
    __table_args__ = (Index("ix_cv_wardrobe_set_scope_status", "scope", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    scope: Mapped[str] = mapped_column(String(16), default="personal")
    wardrobe_version_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvActorWardrobeLook(Base):
    __tablename__ = "cv_actor_wardrobe_looks"
    __table_args__ = (UniqueConstraint("actor_version_id", "wardrobe_version_id", name="uq_cv_actor_wardrobe_look"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_version_id: Mapped[int] = mapped_column(ForeignKey("cv_actor_versions.id"), index=True)
    wardrobe_version_id: Mapped[int] = mapped_column(ForeignKey("cv_wardrobe_versions.id"), index=True)
    output_asset_id: Mapped[int | None] = mapped_column(ForeignKey("cv_media_assets.id"), nullable=True, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvActorReferenceSet(Base):
    __tablename__ = "cv_actor_reference_sets"
    __table_args__ = (UniqueConstraint("actor_version_id", "version", name="uq_cv_actor_reference_set"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_version_id: Mapped[int] = mapped_column(ForeignKey("cv_actor_versions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvActorReferenceFrame(Base):
    __tablename__ = "cv_actor_reference_frames"
    __table_args__ = (UniqueConstraint("reference_set_id", "sequence", name="uq_cv_actor_reference_frame"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_set_id: Mapped[int] = mapped_column(ForeignKey("cv_actor_reference_sets.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(48), default="identity")
    source_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yaw: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    pitch: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    expression: Mapped[str] = mapped_column(String(48), default="neutral")
    shot_scale: Mapped[str] = mapped_column(String(32), default="medium")
    pose_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    wardrobe_version_id: Mapped[int | None] = mapped_column(ForeignKey("cv_wardrobe_versions.id"), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)


class CvVoiceSource(Base):
    __tablename__ = "cv_voice_sources"
    __table_args__ = (Index("ix_cv_voice_source_actor_status", "actor_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("cv_actors.id"), index=True)
    source_asset_id: Mapped[int] = mapped_column(ForeignKey("cv_media_assets.id"), index=True)
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    quality_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rights_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("cv_rights_evidence.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CvWorkflowRun(Base):
    __tablename__ = "cv_workflow_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_cv_workflow_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replication_project_id: Mapped[int] = mapped_column(ForeignKey("cv_replication_projects.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="balanced")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CvWorkflowStageRun(Base):
    __tablename__ = "cv_workflow_stage_runs"
    __table_args__ = (UniqueConstraint("workflow_run_id", "stage", name="uq_cv_workflow_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("cv_workflow_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    depends_on_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    human_gate_reason: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
