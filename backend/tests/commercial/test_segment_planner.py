"""Contract tests for deterministic long-video H3 segment planning."""
from __future__ import annotations


def _shot_graph():
    return {
        "shots": [
            {"shot_key": "hook", "start_ms": 0, "end_ms": 12_000},
            {
                "shot_key": "demo",
                "start_ms": 12_000,
                "end_ms": 42_000,
                "action_neutral_points_ms": [27_000],
            },
            {
                "shot_key": "proof",
                "start_ms": 42_000,
                "end_ms": 60_000,
                "action_neutral_points_ms": [54_000],
            },
        ]
    }


def test_long_shots_split_on_neutral_points_and_preserve_order():
    from app.services.commercial.segment_planner import plan_segments

    segments = plan_segments(_shot_graph(), overlap_ms=240)

    assert [item["shot_key"] for item in segments] == ["hook", "demo", "demo", "proof", "proof"]
    assert [item["start_ms"] for item in segments] == [0, 12_000, 27_000, 42_000, 54_000]
    assert [item["end_ms"] for item in segments] == [12_000, 27_000, 42_000, 54_000, 60_000]
    assert [item["segment_index"] for item in segments] == [0, 1, 2, 3, 4]
    assert all(item["duration_ms"] <= 15_000 for item in segments)
    assert all(item["overlap_ms"] == 240 for item in segments)
    assert all(item["continuity_anchor_time_ms"] == item["start_ms"] for item in segments)


def test_split_without_safe_boundary_requires_manual_review_but_stays_bounded():
    from app.services.commercial.segment_planner import plan_long_video

    result = plan_long_video(
        {"shots": [{"shot_key": "long_take", "start_ms": 0, "end_ms": 31_000}]},
        master_voice_track_id="voice-master-1",
    )

    assert result["status"] == "manual_review"
    assert result["requires_manual_review"] is True
    assert result["segments"][-1]["end_ms"] == 31_000
    assert all(item["duration_ms"] <= 15_000 for item in result["segments"])
    assert result["review_reasons"]


def test_unified_timeline_uses_one_voice_track_without_dialogue_rewrites():
    from app.services.commercial.segment_planner import plan_long_video

    result = plan_long_video(_shot_graph(), master_voice_track_id="voice-master-1")

    assert result["timeline_version"] == 1
    assert result["master_voice_track_id"] == "voice-master-1"
    assert len(result["timeline"]) == len(result["segments"])
    for segment in result["timeline"]:
        assert segment["master_voice_track_id"] == "voice-master-1"
        assert segment["segment_audio_range"] == {
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
        }
        assert segment["dialogue_rewrite_allowed"] is False
        assert segment["script_source"] == "unified_timeline"


def test_plan_is_reproducible_for_same_graph():
    from app.services.commercial.segment_planner import plan_long_video

    first = plan_long_video(_shot_graph(), master_voice_track_id="voice-master-1")
    second = plan_long_video(_shot_graph(), master_voice_track_id="voice-master-1")

    assert first == second
