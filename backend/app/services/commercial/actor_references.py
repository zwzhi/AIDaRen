"""Deterministic actor-reference retrieval for anchor editing."""
from __future__ import annotations

from typing import Any, Mapping


def _match(expected: Any, actual: Any, weight: float) -> float:
    if expected in (None, "", []):
        return 0.0
    if actual == expected:
        return weight
    return 0.0


def rank_actor_references(
    reference_frames: list[Mapping[str, Any]],
    source_features: Mapping[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return only the best references; never pass the full reference set downstream."""
    if limit < 1:
        raise ValueError("limit must be positive")
    ranked: list[dict[str, Any]] = []
    for frame in reference_frames:
        score = 0.0
        score += _match(source_features.get("angle"), frame.get("angle"), 0.35)
        score += _match(source_features.get("shot_scale"), frame.get("shot_scale"), 0.20)
        score += _match(source_features.get("expression"), frame.get("expression"), 0.15)
        score += _match(source_features.get("pose"), frame.get("pose"), 0.15)
        score += _match(source_features.get("wardrobe_version_id"), frame.get("wardrobe_version_id"), 0.10)
        score += float(frame.get("quality_score") or 0.0) * 0.05
        ranked.append({"frame": dict(frame), "score": round(score, 6)})
    ranked.sort(key=lambda item: (-item["score"], int(item["frame"].get("sequence") or 0)))
    return ranked[:limit]

