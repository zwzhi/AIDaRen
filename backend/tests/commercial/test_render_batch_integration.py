from __future__ import annotations

import pytest


def _graph():
    return {
        "shots": [
            {"shot_key": "hook", "start_ms": 0, "end_ms": 12_000},
            {"shot_key": "demo", "start_ms": 12_000, "end_ms": 32_000, "action_neutral_points_ms": [22_000]},
        ]
    }


def test_render_batch_plan_freezes_approved_inputs_and_keeps_segments_bounded():
    from app.services.commercial.render_batch import build_render_batch_plan

    result = build_render_batch_plan(
        _graph(),
        source_duration_ms=32_000,
        master_voice_track_id="voice-master-1",
        script_version_id=11,
        anchor_set_id=12,
        voice_render_id=13,
        subtitle_version_id=14,
        input_statuses={"script": "approved", "anchor_set": "approved", "voice": "approved", "subtitle": "approved"},
    )

    assert result.status == "ready"
    assert result.master_voice_track_id == "voice-master-1"
    assert result.frozen_version_hash
    assert all(item["request_duration_ms"] <= 15_000 for item in result.segments)
    assert {item["master_voice_track_id"] for item in result.timeline} == {"voice-master-1"}


def test_render_batch_composition_recovers_out_of_order_segment_outputs():
    from app.services.commercial.render_batch import compose_render_batch

    result = compose_render_batch(
        {
            "segments": [
                {"segment_index": 0, "shot_key": "hook", "start_ms": 0, "end_ms": 12_000},
                {"segment_index": 1, "shot_key": "demo", "start_ms": 12_000, "end_ms": 22_000},
                {"segment_index": 2, "shot_key": "demo", "start_ms": 22_000, "end_ms": 32_000},
            ],
            "frozen_version_hash": "frozen-hash",
        },
        [
            {"segment_index": 2, "output_key": "out-2"},
            {"segment_index": 0, "output_key": "out-0"},
            {"segment_index": 1, "output_key": "out-1"},
        ],
    )

    assert [item["output_key"] for item in result.segments] == ["out-0", "out-1", "out-2"]
    assert result.frozen_version_hash == "frozen-hash"


def test_render_batch_composition_rejects_non_ready_inputs():
    from app.services.commercial.render_batch import RenderBatchInputError, validate_render_batch_inputs

    with pytest.raises(RenderBatchInputError, match="批准"):
        validate_render_batch_inputs(
            {"script": "approved", "anchor_set": "approved", "voice": "approved", "subtitle": "draft"},
            batch_status="ready",
        )

    with pytest.raises(RenderBatchInputError, match="ready"):
        validate_render_batch_inputs(
            {"script": "approved", "anchor_set": "approved", "voice": "approved", "subtitle": "approved"},
            batch_status="needs_human_review",
        )
