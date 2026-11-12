"""Product research primitives.

The provider-facing fetcher is intentionally separate from these deterministic
merge rules.  Web research produces candidates; this module decides which
candidate can become a product revision without overwriting confirmed facts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import CvProduct, CvProductVersion
from app.models_commercial_v2 import (
    CvProductFactCandidate,
    CvProductResearchRun,
    CvProductSource,
    CvProductVariant,
)


@dataclass(frozen=True)
class VariantResolution:
    status: str
    variant_key: str
    label: str
    reason: str = ""


def resolve_product_variant(identity: Mapping[str, Any]) -> VariantResolution:
    """Resolve a product identity without inventing an official SKU."""
    sku = str(identity.get("sku") or "").strip()
    shade = str(identity.get("shade_code") or "").strip()
    spec = str(identity.get("spec") or identity.get("spec_text") or "").strip()
    label = str(identity.get("variant_label") or "").strip()
    candidates = identity.get("candidate_count")
    if sku or shade or spec:
        parts = [part for part in (sku, shade, spec) if part]
        return VariantResolution("resolved", "|".join(parts), label or " / ".join(parts))
    if label:
        return VariantResolution("user_defined", f"user:{label}", label)
    if candidates in (None, 0, 1):
        return VariantResolution("single_variant", "default", "默认款", "页面未发现可区分变体")
    return VariantResolution("ambiguous", "", "", "存在多个候选变体但没有可靠身份字段")


def merge_fact_candidates(
    confirmed: Mapping[str, Any],
    candidates: Mapping[str, Any],
    *,
    locked_fields: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Merge new research without overwriting confirmed values.

    Returns ``(merged, conflicts)``.  Conflicts retain both values so the UI
    can ask for a decision and later publish a new immutable product version.
    """
    merged = dict(confirmed)
    conflicts: dict[str, dict[str, Any]] = {}
    for field, value in candidates.items():
        if field in locked_fields and field in confirmed and confirmed[field] != value:
            conflicts[field] = {"confirmed": confirmed[field], "candidate": value}
            continue
        if field in confirmed and confirmed[field] != value:
            conflicts[field] = {"confirmed": confirmed[field], "candidate": value}
            continue
        merged[field] = value
    return merged, conflicts


def should_refresh(*, input_hash: str, stored_input_hash: str | None, stale: bool = False) -> bool:
    """Return whether a research run is needed for the current input."""
    return bool(stale or not stored_input_hash or input_hash != stored_input_hash)


def research_input_hash(*, image_asset_ids: list[int], name: str, description: str, source_urls: list[str]) -> str:
    value = {
        "image_asset_ids": sorted(int(item) for item in image_asset_ids),
        "name": str(name or "").strip(),
        "description": str(description or "").strip(),
        "source_urls": sorted(str(item).strip() for item in source_urls if str(item).strip()),
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def start_product_research(
    db: AsyncSession,
    product_id: int,
    *,
    image_asset_ids: list[int],
    name: str,
    description: str = "",
    source_urls: list[str] | None = None,
    user_id: int,
) -> CvProductResearchRun:
    product = await db.get(CvProduct, product_id)
    if product is None:
        raise ValueError("PRODUCT_NOT_FOUND")
    urls = list(source_urls or [])
    input_hash = research_input_hash(
        image_asset_ids=image_asset_ids, name=name, description=description, source_urls=urls,
    )
    existing = (await db.execute(select(CvProductResearchRun).where(
        CvProductResearchRun.product_id == product_id,
        CvProductResearchRun.input_hash == input_hash,
        CvProductResearchRun.status.in_(("candidate", "needs_review", "published")),
    ).order_by(CvProductResearchRun.id.desc()))).scalars().first()
    if existing is not None:
        return existing

    resolution = resolve_product_variant({"candidate_count": 1})
    variant = CvProductVariant(
        product_id=product_id,
        variant_key=resolution.variant_key,
        variant_label=resolution.label,
        resolution_status=resolution.status,
        status="draft",
        created_by=user_id,
    )
    db.add(variant)
    await db.flush()
    run = CvProductResearchRun(
        product_id=product_id,
        variant_id=variant.id,
        input_hash=input_hash,
        model_id="fixture-product-research-v2",
        model_version="fixture-1",
        status="candidate",
        refresh_reason="initial",
        created_by=user_id,
    )
    db.add(run)
    await db.flush()

    for url in urls:
        db.add(CvProductSource(
            research_run_id=run.id,
            url=url,
            domain=url.split("/", 3)[2] if "://" in url else "",
            content_hash=hashlib.sha256(url.encode()).hexdigest(),
            source_level="user_url",
        ))
    facts = {
        "product_name": str(name or product.name).strip(),
        "description": str(description or "").strip(),
        "image_asset_ids": [int(item) for item in image_asset_ids],
    }
    for field_name, value in facts.items():
        db.add(CvProductFactCandidate(
            research_run_id=run.id,
            variant_id=variant.id,
            field_name=field_name,
            value_json=value,
            confidence=1,
            status="candidate",
        ))
    await db.commit()
    await db.refresh(run)
    return run


async def merge_product_candidates(
    db: AsyncSession,
    run_id: int,
    decisions: list[Mapping[str, Any]],
    *,
    user_id: int,
) -> CvProductVersion:
    run = await db.get(CvProductResearchRun, run_id)
    if run is None:
        raise ValueError("RESEARCH_RUN_NOT_FOUND")
    product = await db.get(CvProduct, run.product_id)
    if product is None:
        raise ValueError("PRODUCT_NOT_FOUND")
    rows = (await db.execute(select(CvProductFactCandidate).where(
        CvProductFactCandidate.research_run_id == run_id,
    ))).scalars().all()
    decision_map = {int(item.get("candidate_id")): str(item.get("status") or "approved") for item in decisions}
    approved: dict[str, Any] = {}
    for row in rows:
        status = decision_map.get(row.id, "candidate")
        if status not in {"approved", "confirmed"}:
            continue
        row.status = "confirmed"
        row.reviewed_by = user_id
        row.reviewed_at = datetime.now(UTC)
        approved[row.field_name] = row.value_json

    latest = (await db.execute(select(CvProductVersion).where(
        CvProductVersion.product_id == product.id,
    ).order_by(CvProductVersion.version.desc()))).scalars().first()
    version_no = int(latest.version if latest else 0) + 1
    version = CvProductVersion(
        product_id=product.id,
        version=version_no,
        form=str(approved.get("form") or (latest.form if latest else "")),
        specs_text=str(approved.get("description") or (latest.specs_text if latest else "")),
        image_asset_ids=approved.get("image_asset_ids") or (latest.image_asset_ids if latest else []),
        claims=approved.get("claims") or (latest.claims if latest else []),
        forbidden_phrases=latest.forbidden_phrases if latest else [],
        allowed_actions=approved.get("allowed_actions") or (latest.allowed_actions if latest else []),
        published_by=user_id,
    )
    db.add(version)
    product.current_version = version_no
    run.status = "published"
    run.completed_at = datetime.now(UTC)
    variant = await db.get(CvProductVariant, run.variant_id) if run.variant_id else None
    if variant is not None:
        variant.status = "published"
    await db.commit()
    await db.refresh(version)
    return version


async def list_product_states(db: AsyncSession, product_version_id: int) -> list[Any]:
    from app.models_commercial_v2 import CvProductState
    return list((await db.execute(select(CvProductState).where(
        CvProductState.product_version_id == product_version_id,
        CvProductState.status.in_(("candidate", "approved")),
    ).order_by(CvProductState.id))).scalars().all())

