# -*- coding: utf-8 -*-
"""独立审查复现脚本（codex_review）。

在 printfilm_test 隔离库上直接调用商业域服务函数，复现三项静态审查发现：
R1 幂等重放后的第二次轮询重复写 cv_usage_ledger（费用重复累计）
R2 前端硬编码 720p 在当前能力档案下报价必被拒（PROVIDER_RESOLUTION_UNSUPPORTED）
R3 完整成片必需单元覆盖校验存在兼容回退：合格 attempt 数 ≥ 单元数即放行，
   即使缺失单元从未生成（可绕过"必需镜头不合格不得导出完整成片"）

运行：cd backend && .venv/Scripts/python.exe ../artifacts/codex_review/repro_checks.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from decimal import Decimal

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
sys.path.insert(0, BACKEND)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://printfilm:printfilm-local-dev@127.0.0.1:15432/printfilm_test"

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


async def main() -> None:
    from app.database import Base
    import app.models  # noqa: F401
    import app.models_commercial  # noqa: F401
    import app.models_tasks  # noqa: F401
    import app.models_teams  # noqa: F401
    from app.models import User
    from app.models_commercial import (
        CvBudgetPool, CvCostQuote, CvGenerationAttempt, CvMediaAsset, CvProduction,
        CvUsageLedger,
    )

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    marker = uuid.uuid4().hex[:8]

    results: list[tuple[str, str]] = []
    async with Session() as db:
        user = User(email=f"review-{marker}@test.local", hashed_password="x", role="admin")
        db.add(user)
        await db.flush()
        # ---------------------------------------------------------------- R2
        from app.services.commercial.generation_request import RequestBuildError
        from app.services.providers.atlas.h3_reference import DRAFT_H3_CAPABILITIES

        caps = sorted(DRAFT_H3_CAPABILITIES.resolutions)
        try:
            from app.schemas_commercial import GenerationInputError
            from app.services.commercial.generation_request import build_request_body
            build_request_body({
                "model_id": "m", "prompt": "p", "approved_dialogue": "d",
                "actor_image_asset_ids": [1], "product_image_asset_ids": [2],
                "voice_reference_asset_ids": [3], "resolution_id": "720p",  # 前端 pages.tsx:319 硬编码
                "duration_ms": 5000, "aspect_ratio": "9:16", "audio_required": True,
                "team_id": None, "production_id": 1, "generation_unit_id": 0,
                "attempt_id": "", "params_version": 1, "unit_key": "U001",
            }, DRAFT_H3_CAPABILITIES)
            results.append(("R2", f"未按预期拒绝（能力档案={caps}）——与前端 720p 不符"))
        except (RequestBuildError, GenerationInputError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            results.append(("R2", f"复现：720p 报价构造被拒 code={code}；当前能力档案={caps}"))

        # ---------------------------------------------------------------- R1
        asset = CvMediaAsset(kind="audio", object_key=f"review/{marker}.mp3",
                             sha256=marker * 8, mime="audio/mpeg", size_bytes=10,
                             source_role="owned_voice_reference", uploaded_by=user.id)
        db.add(asset)
        await db.flush()
        asset_id = asset.id
        pool = CvBudgetPool(name=f"review-{marker}", scope="mock", total_amount=Decimal("50"),
                            reserved_amount=Decimal("0"), settled_amount=Decimal("0"),
                            created_by=user.id)
        db.add(pool)
        await db.flush()
        quote = CvCostQuote(quote_key=f"review-{marker}-q", provider_id="atlas", model_id="m",
                            request_fingerprint="x" * 64, resolution_id="768p",
                            requested_duration_ms=5000, currency="USD",
                            estimated_amount=Decimal("0.075"), price_source="mock:test",
                            expires_at=None)
        db.add(quote)
        await db.flush()
        prod = None
        from app.models_commercial import (
            CvActor, CvActorVersion, CvProduct, CvProductVersion, CvTemplate,
            CvTemplateVersion, CvVoiceProfile,
        )

        tpl = CvTemplate(name=f"review-{marker}", created_by=user.id)
        db.add(tpl)
        await db.flush()
        tpl_ver = CvTemplateVersion(template_id=tpl.id, version=1, published_by=user.id)
        db.add(tpl_ver)
        actor = CvActor(name=f"review-{marker}", created_by=user.id)
        db.add(actor)
        await db.flush()
        actor_ver = CvActorVersion(actor_id=actor.id, version=1, published_by=user.id)
        db.add(actor_ver)
        voice = CvVoiceProfile(actor_id=actor.id, audio_asset_id=asset_id)
        db.add(voice)
        prod_product = CvProduct(name=f"review-{marker}", created_by=user.id)
        db.add(prod_product)
        await db.flush()
        prod_ver = CvProductVersion(product_id=prod_product.id, version=1, published_by=user.id)
        db.add(prod_ver)
        await db.flush()
        prod = CvProduction(
            template_version_id=tpl_ver.id, actor_version_id=actor_ver.id,
            voice_profile_id=voice.id, product_version_id=prod_ver.id,
            status="planned", created_by=user.id,
            plan_json={"shots": [], "units": []},
        )
        db.add(prod)
        await db.flush()
        attempt = CvGenerationAttempt(
            production_id=prod.id, attempt_no=1, client_request_id=f"review-{marker}-c",
            payload_hash="y" * 64, params_json={"duration_ms": 5000, "unit_key": "U001"},
            quote_id=quote.id, status="PROVIDER_RUNNING",
            provider_prediction_id=f"MOCK-pred-{marker}",
            created_by=user.id,
        )
        db.add(attempt)
        await db.commit()

        from app.services.commercial.generation import poll_attempt

        async def count_ledger() -> int:
            rows = [r for r in (await db.execute(
                CvUsageLedger.__table__.select().where(
                    CvUsageLedger.attempt_ref == str(attempt.id))
            )).mappings()]
            return len(rows)

        await poll_attempt(attempt, db=db, base_url="https://x", api_key="")  # 第一次轮询（正常）
        n1 = await count_ledger()
        # 幂等重放路径（productions.generate_unit 对 replay 仍建新任务并驱动轮询）：
        await poll_attempt(attempt, db=db, base_url="https://x", api_key="")  # 重放后的第二次轮询
        n2 = await count_ledger()
        results.append(("R1", f"复现：同一 attempt 轮询两次，账本行 {n1} → {n2}"
                             f"（每次重放都会追加一条 SETTLEMENT_PENDING，费用被重复累计）"
                      if n2 > n1 else ("R1", f"未复现：账本行 {n1} → {n2}")))

        # ---------------------------------------------------------------- R3
        prod.plan_json = {"units": [
            {"unit_key": f"U00{i}", "request_duration_ms": 5000, "covered_shot_keys": [],
             "adopt_ranges": [], "params_version": 1, "notes": []}
            for i in range(1, 5)
        ]}
        # 4 个合格 attempt 全部属于 U001（多次重做），U002-U004 从未生成
        for i in range(4):
            db.add(CvGenerationAttempt(
                production_id=prod.id, attempt_no=i + 1,
                client_request_id=f"review-{marker}-c{i}", payload_hash="z" * 64,
                params_json={"duration_ms": 5000, "unit_key": "U001"}, quote_id=quote.id,
                status="REVIEW_APPROVED", created_by=user.id,
            ))
        await db.commit()
        from app.api.commercial.productions import _unit_coverage_error

        missing = await _unit_coverage_error(db, prod)
        results.append(("R3", f"复现：4 单元中 U002-U004 无任何合格版本，覆盖校验返回 {missing!r}"
                             "（None=放行完整成片；仅按数量回退未按 unit_key 核对）"
                      if missing is None else ("R3", f"未复现：返回缺失清单 {missing!r}")))

        # ---------------------------------------------------------------- 清理
        from app.models_commercial import (
            CvActor, CvActorVersion, CvProduct, CvProductVersion, CvTemplate,
            CvTemplateVersion, CvVoiceProfile,
        )

        await db.execute(delete(CvGenerationAttempt).where(
            CvGenerationAttempt.client_request_id.like(f"review-{marker}%")))
        await db.execute(delete(CvUsageLedger).where(
            CvUsageLedger.attempt_ref == str(attempt.id)))
        await db.execute(delete(CvProduction).where(CvProduction.id == prod.id))
        await db.execute(delete(CvProductVersion).where(CvProductVersion.id == prod_ver.id))
        await db.execute(delete(CvProduct).where(CvProduct.id == prod_product.id))
        await db.execute(delete(CvVoiceProfile).where(CvVoiceProfile.id == voice.id))
        await db.execute(delete(CvActorVersion).where(CvActorVersion.id == actor_ver.id))
        await db.execute(delete(CvActor).where(CvActor.id == actor.id))
        await db.execute(delete(CvTemplateVersion).where(CvTemplateVersion.id == tpl_ver.id))
        await db.execute(delete(CvTemplate).where(CvTemplate.id == tpl.id))
        await db.execute(delete(CvCostQuote).where(CvCostQuote.id == quote.id))
        await db.execute(delete(CvBudgetPool).where(CvBudgetPool.id == pool.id))
        await db.execute(delete(CvMediaAsset).where(CvMediaAsset.id == asset_id))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()

    await engine.dispose()
    print("\n==== 复现结果 ====")
    for tag, msg in results:
        print(f"[{tag}] {msg}")


if __name__ == "__main__":
    asyncio.run(main())
