# -*- coding: utf-8 -*-
"""商业域幂等增量迁移（additive only；不重写历史账目）。

- cv_usage_ledger.event_key：业务事件键，配合 (attempt_ref, event_key) 唯一索引
  实现"同一业务事件只入账一次"；
- 历史行回填 event_key='legacy.<id>'（仅赋值，不改金额与状态），
  唯一索引因此可安全创建；重复账目由对账清单输出，不在此删除。
"""
from sqlalchemy import text


async def apply_commercial_schema_patches(conn) -> None:
    """幂等补齐商业域结构；只允许 additive DDL。"""
    # V2 asset tables are additive.  They are kept in a separate module so
    # the legacy product/actor tables remain backwards compatible while an
    # existing PostgreSQL installation receives the same tables as a fresh
    # create_all database.
    from app import models_commercial_v2
    from app.database import Base

    v2_tables = [
        models_commercial_v2.CvProductVariant.__table__,
        models_commercial_v2.CvProductResearchRun.__table__,
        models_commercial_v2.CvProductSource.__table__,
        models_commercial_v2.CvProductFactCandidate.__table__,
        models_commercial_v2.CvProductState.__table__,
        models_commercial_v2.CvProductStateAsset.__table__,
        models_commercial_v2.CvProductCapability.__table__,
        models_commercial_v2.CvWardrobeItem.__table__,
        models_commercial_v2.CvWardrobeVersion.__table__,
        models_commercial_v2.CvWardrobeSet.__table__,
        models_commercial_v2.CvActorWardrobeLook.__table__,
        models_commercial_v2.CvActorReferenceSet.__table__,
        models_commercial_v2.CvActorReferenceFrame.__table__,
        models_commercial_v2.CvVoiceSource.__table__,
        models_commercial_v2.CvWorkflowRun.__table__,
        models_commercial_v2.CvWorkflowStageRun.__table__,
    ]
    await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=v2_tables, checkfirst=True))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_replication_projects (
            id INTEGER PRIMARY KEY,
            production_id INTEGER NOT NULL UNIQUE REFERENCES cv_productions(id),
            mode VARCHAR(32) NOT NULL DEFAULT 'structural_rewrite',
            route_reason TEXT NOT NULL DEFAULT '',
            route_confidence NUMERIC(8,5),
            rights_status VARCHAR(24) NOT NULL DEFAULT 'pending',
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            current_script_version_id INTEGER,
            current_anchor_set_id INTEGER,
            current_voice_render_id INTEGER,
            expected_version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_rights_evidence (
            id INTEGER PRIMARY KEY,
            replication_project_id INTEGER REFERENCES cv_replication_projects(id),
            subject_type VARCHAR(32) NOT NULL,
            subject_id INTEGER NOT NULL,
            holder_name VARCHAR(160) NOT NULL DEFAULT '',
            scope VARCHAR(64) NOT NULL DEFAULT '',
            territory VARCHAR(64) NOT NULL DEFAULT '',
            channels JSON,
            valid_from TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            evidence_asset_id INTEGER REFERENCES cv_media_assets(id),
            verified BOOLEAN NOT NULL DEFAULT FALSE,
            verified_by INTEGER REFERENCES users(id),
            verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cv_replication_status "
        "ON cv_replication_projects(status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cv_rights_subject "
        "ON cv_rights_evidence(subject_type, subject_id)"
    ))
    # Deterministic source-frame lineage fields (additive for installations
    # created before the replication tables were introduced).
    media_columns = {
        row[0] for row in (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'cv_media_assets'"
        ))).fetchall()
    }
    if "source_time_ms" not in media_columns:
        await conn.execute(text(
            "ALTER TABLE cv_media_assets ADD COLUMN source_time_ms INTEGER"
        ))
    if "source_metadata" not in media_columns:
        await conn.execute(text(
            "ALTER TABLE cv_media_assets ADD COLUMN source_metadata JSON"
        ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cv_media_asset_source_time "
        "ON cv_media_assets(derived_from_asset_id, source_time_ms)"
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_shot_graphs (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            revision INTEGER NOT NULL DEFAULT 1,
            shot_key VARCHAR(96) NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            purpose VARCHAR(64) NOT NULL DEFAULT '',
            complexity VARCHAR(24) NOT NULL DEFAULT 'simple',
            camera_json JSON,
            composition_json JSON,
            action_json JSON,
            emotion_json JSON,
            product_presence VARCHAR(16) NOT NULL DEFAULT 'unknown',
            product_confidence NUMERIC(8,5),
            product_evidence_json JSON,
            anchor_candidates_json JSON,
            source_span_json JSON,
            analysis_version VARCHAR(32) NOT NULL DEFAULT '1',
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            invalidation_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cv_shot_graph_revision_key UNIQUE(replication_project_id, revision, shot_key)
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_script_versions (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            version INTEGER NOT NULL,
            shot_graph_revision INTEGER,
            mode VARCHAR(32) NOT NULL DEFAULT 'structural_rewrite',
            script_json JSON,
            claim_ids_json JSON,
            prompt_version VARCHAR(32) NOT NULL DEFAULT '1',
            model_id VARCHAR(96) NOT NULL DEFAULT '',
            model_version VARCHAR(96) NOT NULL DEFAULT '',
            input_hash VARCHAR(64) NOT NULL DEFAULT '',
            status VARCHAR(24) NOT NULL DEFAULT 'draft',
            invalidation_reason TEXT,
            approved_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cv_script_version UNIQUE(replication_project_id, version)
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_anchor_sets (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            version INTEGER NOT NULL,
            shot_graph_revision INTEGER,
            status VARCHAR(24) NOT NULL DEFAULT 'candidate',
            mode VARCHAR(32) NOT NULL DEFAULT 'structural_rewrite',
            frame_count INTEGER NOT NULL DEFAULT 0,
            input_hash VARCHAR(64) NOT NULL DEFAULT '',
            invalidation_reason TEXT,
            approved_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cv_anchor_set_version UNIQUE(replication_project_id, version)
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_anchor_frames (
            id SERIAL PRIMARY KEY,
            anchor_set_id INTEGER NOT NULL REFERENCES cv_anchor_sets(id),
            shot_key VARCHAR(96) NOT NULL,
            sequence INTEGER NOT NULL,
            time_ms INTEGER NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'source',
            source_asset_id INTEGER REFERENCES cv_media_assets(id),
            edited_asset_id INTEGER REFERENCES cv_media_assets(id),
            parent_anchor_id INTEGER REFERENCES cv_anchor_frames(id),
            actor_version_id INTEGER REFERENCES cv_actor_versions(id),
            product_version_id INTEGER REFERENCES cv_product_versions(id),
            provider VARCHAR(32) NOT NULL DEFAULT 'deterministic',
            model_id VARCHAR(96) NOT NULL DEFAULT '',
            model_version VARCHAR(96) NOT NULL DEFAULT '',
            prompt_hash VARCHAR(64) NOT NULL DEFAULT '',
            seed INTEGER,
            quality_status VARCHAR(24) NOT NULL DEFAULT 'pending',
            review_status VARCHAR(24) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cv_anchor_frame_sequence UNIQUE(anchor_set_id, shot_key, sequence)
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_voice_renders (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            script_version_id INTEGER REFERENCES cv_script_versions(id),
            voice_profile_id INTEGER REFERENCES cv_voice_profiles(id),
            model_id VARCHAR(96) NOT NULL DEFAULT '',
            model_version VARCHAR(96) NOT NULL DEFAULT '',
            audio_asset_id INTEGER REFERENCES cv_media_assets(id),
            duration_ms INTEGER,
            script_hash VARCHAR(64) NOT NULL DEFAULT '',
            rights_evidence_id INTEGER REFERENCES cv_rights_evidence(id),
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            invalidation_reason TEXT,
            approved_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_subtitle_versions (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            script_version_id INTEGER REFERENCES cv_script_versions(id),
            voice_render_id INTEGER REFERENCES cv_voice_renders(id),
            version INTEGER NOT NULL DEFAULT 1,
            subtitles_json JSON,
            style_json JSON,
            language VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
            status VARCHAR(24) NOT NULL DEFAULT 'draft',
            invalidation_reason TEXT,
            approved_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    ))
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_cv_shot_graph_project_status ON cv_shot_graphs(replication_project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cv_script_project_status ON cv_script_versions(replication_project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cv_anchor_set_project_status ON cv_anchor_sets(replication_project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cv_anchor_frame_set_shot ON cv_anchor_frames(anchor_set_id, shot_key)",
        "CREATE INDEX IF NOT EXISTS ix_cv_voice_render_project_status ON cv_voice_renders(replication_project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cv_subtitle_project_status ON cv_subtitle_versions(replication_project_id, status)",
    ):
        await conn.execute(text(index_sql))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_render_batches (
            id SERIAL PRIMARY KEY,
            replication_project_id INTEGER NOT NULL REFERENCES cv_replication_projects(id),
            script_version_id INTEGER REFERENCES cv_script_versions(id),
            anchor_set_id INTEGER REFERENCES cv_anchor_sets(id),
            voice_render_id INTEGER REFERENCES cv_voice_renders(id),
            subtitle_version_id INTEGER REFERENCES cv_subtitle_versions(id),
            stage VARCHAR(16) NOT NULL DEFAULT 'preview',
            status VARCHAR(24) NOT NULL DEFAULT 'ready',
            master_voice_track_id VARCHAR(128),
            total_duration_ms INTEGER NOT NULL DEFAULT 0,
            frozen_version_hash VARCHAR(64) NOT NULL DEFAULT '',
            expected_version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    ))
    await conn.execute(text(
        """CREATE TABLE IF NOT EXISTS cv_render_segments (
            id SERIAL PRIMARY KEY,
            render_batch_id INTEGER NOT NULL REFERENCES cv_render_batches(id),
            segment_index INTEGER NOT NULL,
            shot_keys_json JSON,
            source_start_ms INTEGER NOT NULL,
            source_end_ms INTEGER NOT NULL,
            overlap_ms INTEGER NOT NULL DEFAULT 0,
            continuity_anchor_time_ms INTEGER NOT NULL DEFAULT 0,
            request_duration_ms INTEGER NOT NULL,
            anchor_frame_ids_json JSON,
            segment_audio_start_ms INTEGER NOT NULL DEFAULT 0,
            segment_audio_end_ms INTEGER NOT NULL DEFAULT 0,
            provider_task_id VARCHAR(128),
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            output_asset_id INTEGER REFERENCES cv_media_assets(id),
            error_code VARCHAR(64),
            CONSTRAINT uq_cv_render_segment_index UNIQUE(render_batch_id, segment_index)
        )"""
    ))
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_cv_render_batch_project_status ON cv_render_batches(replication_project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cv_render_segment_batch_status ON cv_render_segments(render_batch_id, status)",
    ):
        await conn.execute(text(index_sql))

    # Extend pre-existing quote/attempt/export rows without rewriting history.
    extension_specs = {
        "cv_cost_quotes": {
            "script_version_id": "INTEGER REFERENCES cv_script_versions(id)",
            "anchor_set_id": "INTEGER REFERENCES cv_anchor_sets(id)",
            "voice_render_id": "INTEGER REFERENCES cv_voice_renders(id)",
            "invalidation_reason": "TEXT",
        },
        "cv_generation_attempts": {
            "replication_project_id": "INTEGER REFERENCES cv_replication_projects(id)",
            "script_version_id": "INTEGER REFERENCES cv_script_versions(id)",
            "anchor_set_id": "INTEGER REFERENCES cv_anchor_sets(id)",
            "voice_render_id": "INTEGER REFERENCES cv_voice_renders(id)",
            "preview_or_final": "VARCHAR(16) NOT NULL DEFAULT 'preview'",
        },
        "cv_exports": {
            "script_version_id": "INTEGER REFERENCES cv_script_versions(id)",
            "anchor_set_id": "INTEGER REFERENCES cv_anchor_sets(id)",
            "voice_render_id": "INTEGER REFERENCES cv_voice_renders(id)",
            "render_batch_id": "INTEGER REFERENCES cv_render_batches(id)",
            "frozen_version_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "segment_outputs_json": "JSON",
            "quality_check_json": "JSON",
        },
    }
    for table_name, specs in extension_specs.items():
        rows = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name"
        ), {"table_name": table_name})
        columns = {row[0] for row in rows.fetchall()}
        for column_name, definition in specs.items():
            if column_name not in columns:
                await conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                ))
    quote_columns = {
        row[0] for row in (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'cv_cost_quotes'"
        ))).fetchall()
    }
    if "replication_project_id" not in quote_columns:
        await conn.execute(text(
            "ALTER TABLE cv_cost_quotes ADD COLUMN replication_project_id INTEGER "
            "REFERENCES cv_replication_projects(id)"
        ))
    if "status" not in quote_columns:
        await conn.execute(text(
            "ALTER TABLE cv_cost_quotes ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'draft'"
        ))
    if "max_amount" not in quote_columns:
        await conn.execute(text(
            "ALTER TABLE cv_cost_quotes ADD COLUMN max_amount NUMERIC(20,8)"
        ))
    if "accepted_by" not in quote_columns:
        await conn.execute(text(
            "ALTER TABLE cv_cost_quotes ADD COLUMN accepted_by INTEGER REFERENCES users(id)"
        ))
    if "accepted_at" not in quote_columns:
        await conn.execute(text(
            "ALTER TABLE cv_cost_quotes ADD COLUMN accepted_at TIMESTAMPTZ"
        ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cv_quote_replication_status "
        "ON cv_cost_quotes(replication_project_id, status)"
    ))
    await conn.execute(text(
        "ALTER TABLE cv_budget_pools ALTER COLUMN scope SET DEFAULT 'mock'"
    ))
    await conn.execute(text(
        "UPDATE cv_budget_pools SET scope = 'mock' WHERE scope IS NULL"
    ))
    await conn.execute(text("DROP INDEX IF EXISTS uq_cv_budget_pool_name_scope"))
    present = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'cv_usage_ledger'"))
    columns = {row[0] for row in present.fetchall()}
    if "event_key" not in columns:
        await conn.execute(text(
            "ALTER TABLE cv_usage_ledger ADD COLUMN IF NOT EXISTS event_key VARCHAR(64) NOT NULL DEFAULT ''"
        ))
        # 历史行赋唯一键值（不触碰金额/状态）；空串行也补齐
        await conn.execute(text(
            "UPDATE cv_usage_ledger SET event_key = 'legacy.' || id "
            "WHERE event_key IS NULL OR event_key = ''"
        ))
    if await conn.scalar(text("SELECT to_regclass('uq_cv_ledger_attempt_event')")) is None:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cv_ledger_attempt_event "
            "ON cv_usage_ledger (attempt_ref, event_key)"
        ))
