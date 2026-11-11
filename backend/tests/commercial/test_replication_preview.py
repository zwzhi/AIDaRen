from __future__ import annotations

import pytest

from app.services.providers.atlas.h3_reference import (
    DRAFT_H3_CAPABILITIES,
    H3VideoAdapter,
    PreviewInputError,
    build_h3_preview_request,
    plan_anchor_batches,
)
from app.services.commercial.generation_request import build_preview_request
from app.services.commercial.timeline import TimelineCompiler


def _frozen(**overrides):
    value = {
        "model_id": "minimax-h3-developer-reference",
        "prompt": "结构化改写的镜头",
        "approved_dialogue": "这是一段新的台词",
        "duration_ms": 5000,
        "aspect_ratio": "9:16",
        "resolution_id": "480p",
        "audio_required": True,
        "actor_image_asset_ids": [101],
        "product_image_asset_ids": [201],
        "voice_reference_asset_ids": [301],
        "script": {"status": "approved", "version": 3, "hash": "script-hash"},
        "anchor_set": {
            "status": "approved",
            "version": 2,
            "hash": "anchor-hash",
            "frames": [
                {"shot_key": "S01", "sequence": 0, "asset_id": 11, "time_ms": 0},
                {"shot_key": "S01", "sequence": 1, "asset_id": 12, "time_ms": 1500},
            ],
        },
        "voice": {"status": "approved", "version": 4, "hash": "voice-hash", "asset_id": 301},
        "subtitle": {"status": "approved", "version": 1, "hash": "subtitle-hash"},
        "frozen_version_hash": "frozen-hash",
    }
    value.update(overrides)
    return value


def test_preview_defaults_to_portrait_and_lowest_verified_resolution() -> None:
    caps = DRAFT_H3_CAPABILITIES
    assert caps.preview_aspect_ratio == "9:16"
    assert caps.preview_default_resolution == "480p"
    assert caps.max_reference_images == 9
    body = build_preview_request(_frozen(resolution_id=""), caps)
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "480p"
    assert body["preview"] is True


def test_preview_requires_all_frozen_revisions() -> None:
    for key in ("script", "anchor_set", "voice", "subtitle"):
        value = _frozen()
        value.pop(key)
        with pytest.raises(PreviewInputError, match="冻结"):
            build_preview_request(value, DRAFT_H3_CAPABILITIES)


def test_preview_anchor_frames_keep_order_and_version_hash() -> None:
    body = build_preview_request(_frozen(), DRAFT_H3_CAPABILITIES)
    assert body["anchor_frame_mapping"] == [
        {"shot_key": "S01", "sequence": 0, "time_ms": 0, "asset_id": 11},
        {"shot_key": "S01", "sequence": 1, "time_ms": 1500, "asset_id": 12},
    ]
    assert body["reference_images"] == [11, 12]
    assert body["frozen_version_hash"] == "frozen-hash"


def test_anchor_batches_split_continuous_clip_and_explicitly_over_nine() -> None:
    frames = [
        {"shot_key": "S01", "sequence": i, "asset_id": i + 1, "time_ms": i * 100}
        for i in range(10)
    ]
    batches = plan_anchor_batches(frames)
    assert [len(batch) for batch in batches] == [3, 3, 3, 1]
    assert batches[0][0]["sequence"] == 0
    assert batches[-1][0]["sequence"] == 9
    with pytest.raises(PreviewInputError, match="拆批"):
        build_h3_preview_request(
            _frozen(anchor_set={"status": "approved", "frames": frames}),
            DRAFT_H3_CAPABILITIES,
        )


def test_mock_preview_submit_does_not_call_real_api_and_is_recoverable(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("real H3 API must not be called in mock mode")

    monkeypatch.setattr("app.services.providers.atlas.h3_reference.submit_generation", fail)
    adapter = H3VideoAdapter(mode="mock")
    task = adapter.submit_preview(_frozen())
    assert task.provider_task_id.startswith("MOCK-")
    assert task.status == "awaiting_poll"
    assert task.request["preview"] is True
    assert adapter.submit_preview(_frozen()) is task
    assert adapter.recover(task.provider_task_id).status == "succeeded"


def test_timeline_compose_preview_preserves_order_and_frozen_hash() -> None:
    compiler = TimelineCompiler()
    result = compiler.compose_preview(
        [
            {"provider_task_id": "MOCK-2", "shot_key": "S02", "output_key": "b.mp4"},
            {"provider_task_id": "MOCK-1", "shot_key": "S01", "output_key": "a.mp4"},
        ],
        [
            {"shot_key": "S01", "start_ms": 0, "end_ms": 5000},
            {"shot_key": "S02", "start_ms": 5000, "end_ms": 10000},
        ],
        frozen_version_hash="frozen-hash",
    )
    assert result.kind == "partial_preview"
    assert [item["shot_key"] for item in result.segments] == ["S01", "S02"]
    assert result.frozen_version_hash == "frozen-hash"
