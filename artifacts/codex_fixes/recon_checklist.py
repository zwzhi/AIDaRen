# -*- coding: utf-8 -*-
"""业务库商业域账目核对清单（只读；P1-2/P1-5 修复前置盘点）。

输出 attempts ↔ reservations ↔ ledger 的不一致项，供人工决定处置；
本脚本不修改任何数据。运行：
  cd backend && .venv/Scripts/python.exe ../artifacts/codex_fixes/recon_checklist.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

DB = "postgresql+asyncpg://printfilm:printfilm-local-dev@127.0.0.1:15432/printfilm"


async def main() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    out: list[str] = ["# 商业域账目核对清单（只读盘点 · 生成于 P1-2/P1-5 修复前）", ""]
    engine = create_async_engine(DB)
    async with engine.connect() as c:
        sections = [
            ("A. attempt 无预留记录（批准事务不完整或历史数据）", """
                SELECT a.id, a.client_request_id, a.status, a.reservation_id
                FROM cv_generation_attempts a
                LEFT JOIN cv_budget_reservations r ON r.id = a.reservation_id
                WHERE a.reservation_id IS NOT NULL AND r.id IS NULL
                ORDER BY a.id"""),
            ("B. 预留仍 reserved 但 attempt 已终态（未释放/未结算的悬挂预留）", """
                SELECT r.id AS reservation_id, r.amount, a.id AS attempt_id, a.status
                FROM cv_budget_reservations r
                JOIN cv_generation_attempts a ON a.reservation_id = r.id
                WHERE r.status = 'reserved'
                  AND a.status IN ('GENERATED','PROVIDER_FAILED','CANCELLED','REVIEW_APPROVED','REVIEW_REJECTED')
                ORDER BY r.id"""),
            ("C. SUBMIT_UNKNOWN 的预留（保留正确，列出待人工对账）", """
                SELECT r.id AS reservation_id, r.amount, a.id AS attempt_id, a.error_code
                FROM cv_budget_reservations r
                JOIN cv_generation_attempts a ON a.reservation_id = r.id
                WHERE a.status = 'SUBMIT_UNKNOWN' AND r.status = 'reserved'
                ORDER BY r.id"""),
            ("D. 同一 attempt 多条账本行（历史重复入账，修复前缺陷特征）", """
                SELECT attempt_ref, count(*) AS rows, sum(amount) AS total
                FROM cv_usage_ledger GROUP BY attempt_ref HAVING count(*) > 1
                ORDER BY rows DESC"""),
            ("E. GENERATED 但无账本行（入账缺失）", """
                SELECT a.id AS attempt_id, a.status
                FROM cv_generation_attempts a
                LEFT JOIN cv_usage_ledger l ON l.attempt_ref = CAST(a.id AS TEXT)
                WHERE a.status IN ('GENERATED','REVIEW_APPROVED','REVIEW_REJECTED')
                  AND l.id IS NULL
                ORDER BY a.id"""),
            ("F. 预算池余额快照（reserved/settled 与明细合计的差异）", """
                SELECT p.id, p.scope, p.total_amount, p.reserved_amount, p.settled_amount,
                       COALESCE((SELECT sum(r.amount) FROM cv_budget_reservations r
                                 WHERE r.pool_id = p.id AND r.status = 'reserved'), 0) AS reserved_detail,
                       COALESCE((SELECT sum(r.amount) FROM cv_budget_reservations r
                                 WHERE r.pool_id = p.id AND r.status = 'settled'), 0) AS settled_detail
                FROM cv_budget_pools p ORDER BY p.id"""),
        ]
        for title, sql in sections:
            rows = (await c.execute(text(sql))).mappings().all()
            out.append(f"## {title}")
            if not rows:
                out.append("- （无）")
            for row in rows:
                out.append(f"- {dict(row)}")
            out.append("")
    await engine.dispose()

    dest = Path(__file__).with_name("recon_checklist.md")
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"written: {dest}")
    print("\n".join(out[:40]))


if __name__ == "__main__":
    asyncio.run(main())
