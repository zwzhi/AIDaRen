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
