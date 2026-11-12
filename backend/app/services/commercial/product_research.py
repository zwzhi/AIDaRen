"""Product research primitives.

The provider-facing fetcher is intentionally separate from these deterministic
merge rules.  Web research produces candidates; this module decides which
candidate can become a product revision without overwriting confirmed facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


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

