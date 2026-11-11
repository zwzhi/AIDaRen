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
