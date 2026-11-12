"""Persistent product-research endpoints (fixture-first, no paid provider calls)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import CvProduct
from app.models_commercial_v2 import CvProductFactCandidate, CvProductResearchRun
from app.services.commercial.product_research import merge_product_candidates, start_product_research

router = APIRouter()


async def _product_for_user(db: AsyncSession, product_id: int, user: User) -> CvProduct:
    product = await db.get(CvProduct, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    if user.role != "admin" and product.created_by != user.id:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


class ProductResearchCreateBody(BaseModel):
    image_asset_ids: list[int] = Field(default_factory=list)
    name: str = ""
    description: str = ""
    source_urls: list[str] = Field(default_factory=list)


class ProductResearchReviewBody(BaseModel):
    decisions: list[dict[str, Any]] = Field(default_factory=list)


def _run_view(run: CvProductResearchRun, candidates: list[CvProductFactCandidate]) -> dict[str, Any]:
    return {
        "id": run.id,
        "product_id": run.product_id,
        "variant_id": run.variant_id,
        "status": run.status,
        "input_hash": run.input_hash,
        "model_id": run.model_id,
        "model_version": run.model_version,
        "refresh_reason": run.refresh_reason,
        "candidates": [
            {
                "id": row.id,
                "field_name": row.field_name,
                "value": row.value_json,
                "confidence": float(row.confidence) if row.confidence is not None else None,
                "status": row.status,
                "source_id": row.source_id,
            }
            for row in candidates
        ],
    }


@router.post("/products/{product_id}/research", summary="启动商品研究")
async def create_product_research(
    product_id: int,
    body: ProductResearchCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    product = await _product_for_user(db, product_id, user)
    run = await start_product_research(
        db,
        product.id,
        image_asset_ids=body.image_asset_ids,
        name=body.name or product.name,
        description=body.description,
        source_urls=body.source_urls,
        user_id=user.id,
    )
    candidates = list((await db.execute(select(CvProductFactCandidate).where(
        CvProductFactCandidate.research_run_id == run.id,
    ))).scalars().all())
    return _run_view(run, candidates)


@router.get("/product-research/{run_id}", summary="查看商品研究")
async def get_product_research(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await db.get(CvProductResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    await _product_for_user(db, run.product_id, user)
    candidates = list((await db.execute(select(CvProductFactCandidate).where(
        CvProductFactCandidate.research_run_id == run.id,
    ))).scalars().all())
    return _run_view(run, candidates)


@router.post("/product-research/{run_id}/review", summary="确认商品研究候选")
async def review_product_research(
    run_id: int,
    body: ProductResearchReviewBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await db.get(CvProductResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    await _product_for_user(db, run.product_id, user)
    try:
        version = await merge_product_candidates(db, run.id, body.decisions, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"product_version_id": version.id, "version": version.version, "status": "published"}

