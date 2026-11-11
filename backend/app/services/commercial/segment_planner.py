"""Deterministic planning for long source videos consumed by H3.

The planner operates on an already analysed shot graph.  It does not call a
provider and it never edits script text.  Logical timeline ranges stay
contiguous while ``source_start_ms`` and ``source_end_ms`` expose optional
frame overlap for continuity at a generated segment boundary.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


MAX_SEGMENT_DURATION_MS = 15_000
READY_STATUS = "ready"
MANUAL_REVIEW_STATUS = "manual_review"


@dataclass(frozen=True)
class SegmentPlanningResult:
    """Immutable result object for callers that prefer attribute access.

    ``as_dict`` returns the wire representation used by the functional
    helpers.  Keeping the wire shape as dictionaries preserves compatibility
    with existing JSON-oriented commercial services.
    """

    status: str
    segments: tuple[dict[str, Any], ...]
    timeline: tuple[dict[str, Any], ...]
    source_duration_ms: int
    master_voice_track_id: str | None
    requires_manual_review: bool
    review_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timeline_version": 1,
            "source_duration_ms": self.source_duration_ms,
            "master_voice_track_id": self.master_voice_track_id,
            "requires_manual_review": self.requires_manual_review,
            "review_reasons": list(self.review_reasons),
            "segments": [dict(item) for item in self.segments],
            "timeline": [dict(item) for item in self.timeline],
            "dialogue_policy": {
                "master_voice_track_id": self.master_voice_track_id,
                "rewrite_per_segment": False,
                "script_source": "unified_timeline",
            },
        }


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _values_for_keys(row: Mapping[str, Any], keys: Sequence[str]) -> list[int]:
    values: list[int] = []
    for key in keys:
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, Mapping):
            raw = raw.values()
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        try:
            iterator = iter(raw)
        except TypeError:
            iterator = iter([raw])
        for item in iterator:
            if isinstance(item, Mapping):
                item = item.get("time_ms", item.get("at_ms", item.get("timestamp_ms")))
            number = _as_int(item, -1)
            if number >= 0:
                values.append(number)
    return values


def _normalise_rows(shot_graph: Any) -> list[dict[str, Any]]:
    if isinstance(shot_graph, Mapping):
        rows = shot_graph.get("shots") or shot_graph.get("nodes") or []
    else:
        rows = getattr(shot_graph, "shots", shot_graph)
    normalised: list[dict[str, Any]] = []
    for position, item in enumerate(rows or []):
        if isinstance(item, Mapping):
            row = dict(item)
        else:
            row = {
                "shot_key": getattr(item, "shot_key", getattr(item, "shot_id", "")),
                "start_ms": getattr(item, "start_ms", 0),
                "end_ms": getattr(item, "end_ms", 0),
                "action_neutral_points_ms": getattr(item, "action_neutral_points_ms", ()),
                "safe_split_points_ms": getattr(item, "safe_split_points_ms", ()),
            }
        shot_key = str(row.get("shot_key") or row.get("shot_id") or row.get("id") or "")
        start_ms = _as_int(row.get("start_ms"), -1)
        end_ms = _as_int(row.get("end_ms"), -1)
        if not shot_key or start_ms < 0 or end_ms <= start_ms:
            raise ValueError(f"invalid shot graph row at index {position}")
        safe_points = _values_for_keys(
            row,
            (
                "action_neutral_points_ms",
                "action_neutral_ms",
                "action_neutral_points",
                "safe_split_points_ms",
                "safe_cut_points_ms",
                "safe_boundaries_ms",
                "neutral_points_ms",
                "edit_points_ms",
                "cut_points_ms",
                "boundaries_ms",
            ),
        )
        # Some shot graph producers store action markers as objects.
        actions = row.get("actions") or row.get("action_markers") or ()
        safe_points.extend(
            _values_for_keys({"actions": actions}, ("actions",))
        )
        normalised.append(
            {
                **row,
                "shot_key": shot_key,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "safe_points_ms": tuple(sorted(set(safe_points))),
                "graph_position": position,
            }
        )
    # Time order is deterministic even if a provider returned rows out of order.
    return sorted(normalised, key=lambda value: (value["start_ms"], value["end_ms"], value["graph_position"]))


def _segments_for_shot(
    shot: Mapping[str, Any],
    *,
    max_duration_ms: int,
    overlap_ms: int,
    source_duration_ms: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    shot_key = str(shot["shot_key"])
    shot_start = int(shot["start_ms"])
    shot_end = int(shot["end_ms"])
    safe_points = tuple(
        point for point in shot.get("safe_points_ms", ()) if shot_start < point < shot_end
    )
    segments: list[dict[str, Any]] = []
    review_reasons: list[str] = []
    cursor = shot_start
    while cursor < shot_end:
        target = min(cursor + max_duration_ms, shot_end)
        if target == shot_end:
            boundary = target
            split_reason = "shot_end"
            safe_boundary = True
        else:
            candidates = [point for point in safe_points if cursor < point <= target]
            if candidates:
                boundary = max(candidates)
                split_reason = "action_neutral_point"
                safe_boundary = True
            else:
                # A hard H3 limit is still emitted so downstream work can be
                # previewed, while the plan explicitly asks a human to review.
                boundary = target
                split_reason = "hard_limit_manual_review"
                safe_boundary = False
                review_reasons.append(
                    f"shot {shot_key} has no safe split boundary before {target}ms"
                )
        logical_start = cursor
        logical_end = boundary
        segments.append(
            {
                "shot_key": shot_key,
                "start_ms": logical_start,
                "end_ms": logical_end,
                "duration_ms": logical_end - logical_start,
                "source_start_ms": max(0, logical_start - overlap_ms),
                "source_end_ms": min(source_duration_ms, logical_end + overlap_ms),
                "overlap_ms": overlap_ms,
                "continuity_anchor_time_ms": logical_start,
                "split_reason": split_reason,
                "safe_boundary": safe_boundary,
                "requires_manual_review": not safe_boundary,
            }
        )
        cursor = boundary
    return segments, review_reasons


def plan_segments(
    shot_graph: Any,
    *,
    source_duration_ms: int | None = None,
    max_segment_duration_ms: int = MAX_SEGMENT_DURATION_MS,
    overlap_ms: int = 0,
) -> list[dict[str, Any]]:
    """Return contiguous, bounded logical ranges in deterministic shot order."""
    rows = _normalise_rows(shot_graph)
    if not rows:
        raise ValueError("shot graph must contain at least one shot")
    if max_segment_duration_ms <= 0 or max_segment_duration_ms > MAX_SEGMENT_DURATION_MS:
        raise ValueError("max_segment_duration_ms must be between 1 and 15000")
    if overlap_ms < 0:
        raise ValueError("overlap_ms must be non-negative")
    inferred_duration = max(row["end_ms"] for row in rows)
    duration = _as_int(source_duration_ms, inferred_duration) if source_duration_ms is not None else inferred_duration
    if duration < inferred_duration:
        raise ValueError("source_duration_ms cannot be shorter than the shot graph")
    built: list[dict[str, Any]] = []
    for row in rows:
        shot_segments, _ = _segments_for_shot(
            row,
            max_duration_ms=max_segment_duration_ms,
            overlap_ms=overlap_ms,
            source_duration_ms=duration,
        )
        built.extend(shot_segments)
    for index, item in enumerate(built):
        item["segment_index"] = index
    return built


def _build_timeline(
    segments: Iterable[Mapping[str, Any]], master_voice_track_id: str | None
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for segment in segments:
        row = dict(segment)
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        row.update(
            {
                "master_voice_track_id": master_voice_track_id,
                "segment_audio_range": {"start_ms": start_ms, "end_ms": end_ms},
                "dialogue_rewrite_allowed": False,
                "script_source": "unified_timeline",
            }
        )
        timeline.append(row)
    return timeline


def plan_long_video(
    shot_graph: Any,
    *,
    source_duration_ms: int | None = None,
    master_voice_track_id: str | None = None,
    max_segment_duration_ms: int = MAX_SEGMENT_DURATION_MS,
    overlap_ms: int = 0,
) -> dict[str, Any]:
    """Build one full-video timeline and its H3 segment ranges."""
    rows = _normalise_rows(shot_graph)
    if not rows:
        raise ValueError("shot graph must contain at least one shot")
    inferred_duration = max(row["end_ms"] for row in rows)
    duration = _as_int(source_duration_ms, inferred_duration) if source_duration_ms is not None else inferred_duration
    segments = plan_segments(
        {"shots": rows},
        source_duration_ms=duration,
        max_segment_duration_ms=max_segment_duration_ms,
        overlap_ms=overlap_ms,
    )
    review_reasons: list[str] = []
    previous_end: int | None = None
    for item in segments:
        item["master_voice_track_id"] = master_voice_track_id
        item["segment_audio_range"] = {
            "start_ms": item["start_ms"],
            "end_ms": item["end_ms"],
        }
        if previous_end is not None and item["start_ms"] != previous_end:
            review_reasons.append(
                f"timeline gap or overlap between {previous_end}ms and {item['start_ms']}ms"
            )
        previous_end = item["end_ms"]
        if item["requires_manual_review"]:
            review_reasons.append(
                f"segment {item['segment_index']} requires a safe action boundary"
            )
    if segments and segments[0]["start_ms"] != 0:
        review_reasons.append("shot graph does not start at 0ms")
    if segments and segments[-1]["end_ms"] != duration:
        review_reasons.append("shot graph does not cover source duration")
    # Preserve insertion order while removing duplicate reasons.
    unique_reasons = tuple(dict.fromkeys(review_reasons))
    timeline = _build_timeline(segments, master_voice_track_id)
    result = SegmentPlanningResult(
        status=MANUAL_REVIEW_STATUS if unique_reasons else READY_STATUS,
        segments=tuple(segments),
        timeline=tuple(timeline),
        source_duration_ms=duration,
        master_voice_track_id=master_voice_track_id,
        requires_manual_review=bool(unique_reasons),
        review_reasons=unique_reasons,
    )
    return result.as_dict()


class SegmentPlanner:
    """Object facade around :func:`plan_long_video` for service consumers."""

    def plan(self, shot_graph: Any, **kwargs: Any) -> dict[str, Any]:
        return plan_long_video(shot_graph, **kwargs)

    def segments(self, shot_graph: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return plan_segments(shot_graph, **kwargs)


def build_unified_timeline(
    shot_graph: Any, **kwargs: Any
) -> dict[str, Any]:
    """Alias kept explicit for callers that only need the timeline contract."""
    return plan_long_video(shot_graph, **kwargs)


__all__ = [
    "MANUAL_REVIEW_STATUS",
    "MAX_SEGMENT_DURATION_MS",
    "READY_STATUS",
    "SegmentPlanner",
    "SegmentPlanningResult",
    "build_unified_timeline",
    "plan_long_video",
    "plan_segments",
]
