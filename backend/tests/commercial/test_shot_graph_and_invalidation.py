"""Task 2 contract tests for deterministic frames, anchors, and invalidation."""
from __future__ import annotations

import pytest


def test_simple_and_product_shots_choose_bounded_anchor_counts() -> None:
    from app.services.commercial.frames import sample_anchor_candidates

    shot_graph = {
        "shots": [
            {
                "shot_key": "hook",
                "start_ms": 0,
                "end_ms": 15_000,
                "complexity": "simple",
                "product_presence": "absent",
            },
            {
                "shot_key": "product",
                "start_ms": 15_000,
                "end_ms": 30_000,
                "complexity": "high",
                "product_presence": "required",
            },
        ]
    }

    candidates = sample_anchor_candidates(shot_graph, max_frames=9)

    assert len(candidates) in {3, 5, 7}
    assert len(candidates) <= 9
    assert {candidate.shot_key for candidate in candidates} == {"hook", "product"}
    assert all(0 <= candidate.time_ms <= 30_000 for candidate in candidates)


def test_source_frame_asset_is_private_and_preserves_lineage() -> None:
    from app.models_commercial import CvMediaAsset
    from app.services.commercial.frames import source_frame_asset

    parent = CvMediaAsset(
        id=42,
        kind="video",
        object_key="reference_source_video/20261112/source.mp4",
        sha256="a" * 64,
        mime="video/mp4",
        size_bytes=100,
        duration_ms=15_000,
        source_role="reference_source_video",
        uploaded_by=7,
    )

    frame = source_frame_asset(
        parent,
        time_ms=3_200,
        object_key="reference_source_frame/20261112/frame.jpg",
        sha256="b" * 64,
        size_bytes=12,
    )

    assert frame.source_role == "reference_source_frame"
    assert frame.derived_from_asset_id == parent.id
    assert frame.kind == "image"
    assert frame.duration_ms is None
    assert frame.width is None
    assert frame.height is None
    assert frame.rights_status == "authorized"
    assert frame.source_metadata["time_ms"] == 3_200


def test_invalidation_marks_downstream_revisions_and_quote_stale() -> None:
    from app.services.commercial.frames import invalidation_statuses

    result = invalidation_statuses(changed_shot_keys={"product"}, reason="product_version_changed")

    assert result == {
        "shot_graph": "superseded",
        "script": "invalidated",
        "anchor_set": "invalidated",
        "voice_render": "invalidated",
        "quote": "invalidated",
    }


def test_timeline_compiler_keeps_order_external_and_is_deterministic() -> None:
    from app.services.commercial.timeline import TimelineCompiler

    compiler = TimelineCompiler()
    compiled = compiler.compile(
        [
            {"shot_key": "b", "start_ms": 1_000, "end_ms": 2_000},
            {"shot_key": "a", "start_ms": 0, "end_ms": 1_000},
        ]
    )

    assert [item["shot_key"] for item in compiled] == ["b", "a"]
    assert compiler.compile(compiled) == compiled
