"""Deterministic render-batch planning and composition helpers.

The helpers in this module only build and validate metadata.  They never call a
paid provider, which keeps preview/final orchestration recoverable in tests and
in the local mock environment.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.commercial.segment_planner import plan_long_video


class RenderBatchInputError(ValueError):
    """Raised when a batch cannot be consumed by preview/final composition."""


_APPROVED = {"approved", "frozen"}


@dataclass(frozen=True)
class RenderBatchPlan:
    status: str
    source_duration_ms: int
    master_voice_track_id: str | None
    segments: tuple[dict[str, Any], ...]
    timeline: tuple[dict[str, Any], ...]
    frozen_version_hash: str
    requires_manual_review: bool
    review_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RenderBatchComposition:
    frozen_version_hash: str
    segments: tuple[dict[str, Any], ...]
    output_keys: tuple[str, ...]
    total_duration_ms: int
    qa_summary: dict[str, Any]


def validate_render_batch_inputs(
    input_statuses: Mapping[str, str], *, batch_status: str
) -> None:
    """Enforce the shared approved-input gate for preview and final export."""
    for key in ("script", "anchor_set", "voice", "subtitle"):
        if str(input_statuses.get(key) or "") not in _APPROVED:
            raise RenderBatchInputError(f"{key}版本必须先批准")
    if batch_status != "ready":
        raise RenderBatchInputError("render batch 必须处于 ready 状态")


def _freeze_hash(
    *,
    script_version_id: int | None,
    anchor_set_id: int | None,
    voice_render_id: int | None,
    subtitle_version_id: int | None,
    plan: Mapping[str, Any],
) -> str:
    material = {
        "script_version_id": script_version_id,
        "anchor_set_id": anchor_set_id,
        "voice_render_id": voice_render_id,
        "subtitle_version_id": subtitle_version_id,
        "timeline": plan.get("timeline") or [],
        "master_voice_track_id": plan.get("master_voice_track_id"),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_render_batch_plan(
    shot_graph: Any,
    *,
    source_duration_ms: int | None = None,
    master_voice_track_id: str | None = None,
    overlap_ms: int = 0,
    script_version_id: int | None = None,
    anchor_set_id: int | None = None,
    voice_render_id: int | None = None,
    subtitle_version_id: int | None = None,
    input_statuses: Mapping[str, str] | None = None,
) -> RenderBatchPlan:
    plan = plan_long_video(
        shot_graph,
        source_duration_ms=source_duration_ms,
        master_voice_track_id=master_voice_track_id,
        overlap_ms=overlap_ms,
    )
    frozen_hash = _freeze_hash(
        script_version_id=script_version_id,
        anchor_set_id=anchor_set_id,
        voice_render_id=voice_render_id,
        subtitle_version_id=subtitle_version_id,
        plan=plan,
    )
    return RenderBatchPlan(
        status=str(plan["status"]),
        source_duration_ms=int(plan["source_duration_ms"]),
        master_voice_track_id=plan.get("master_voice_track_id"),
        segments=tuple(dict(item) for item in plan["segments"]),
        timeline=tuple(dict(item) for item in plan["timeline"]),
        frozen_version_hash=frozen_hash,
        requires_manual_review=bool(plan.get("requires_manual_review")),
        review_reasons=tuple(str(item) for item in plan.get("review_reasons") or []),
    )


def compose_render_batch(
    batch: Mapping[str, Any], outputs: Sequence[Mapping[str, Any]]
) -> RenderBatchComposition:
    """Merge segment results by index, making arrival order irrelevant."""
    planned = [dict(item) for item in batch.get("segments") or []]
    if not planned:
        raise RenderBatchInputError("render batch 没有分段")
    by_index = {int(item.get("segment_index")): dict(item) for item in outputs if item.get("segment_index") is not None}
    expected = list(range(len(planned)))
    if sorted(by_index) != expected:
        missing = sorted(set(expected) - set(by_index))
        raise RenderBatchInputError(f"render batch 缺少分段输出: {missing}")
    merged: list[dict[str, Any]] = []
    output_keys: list[str] = []
    for plan_row in sorted(planned, key=lambda item: int(item.get("segment_index", 0))):
        index = int(plan_row["segment_index"])
        output = by_index[index]
        if not output.get("output_key") and output.get("output_asset_id") is None:
            raise RenderBatchInputError(f"分段 {index} 缺少输出")
        row = dict(plan_row)
        row.update({key: value for key, value in output.items() if key != "segment_index"})
        merged.append(row)
        if row.get("output_key"):
            output_keys.append(str(row["output_key"]))
        elif row.get("output_asset_id") is not None:
            output_keys.append(str(row["output_asset_id"]))
    total = sum(int(row["end_ms"]) - int(row["start_ms"]) for row in merged)
    return RenderBatchComposition(
        frozen_version_hash=str(batch.get("frozen_version_hash") or ""),
        segments=tuple(merged),
        output_keys=tuple(output_keys),
        total_duration_ms=total,
        qa_summary={
            "segment_count": len(merged),
            "ordered_segment_indexes": [int(row["segment_index"]) for row in merged],
            "all_segments_ready": True,
        },
    )


__all__ = [
    "RenderBatchComposition",
    "RenderBatchInputError",
    "RenderBatchPlan",
    "build_render_batch_plan",
    "compose_render_batch",
    "validate_render_batch_inputs",
]
