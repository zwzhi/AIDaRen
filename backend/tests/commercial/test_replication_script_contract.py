"""TDD contract tests for Gemini shot graph and replication scripts."""
from __future__ import annotations

import pytest


def test_shot_graph_schema_carries_product_evidence_and_anchor_candidates() -> None:
    from app.schemas_commercial import ShotGraphPayload

    payload = ShotGraphPayload.model_validate(
        {
            "shots": [
                {
                    "shot_key": "hook",
                    "start": 0,
                    "end": 1800,
                    "purpose": "hook",
                    "camera": {"shot": "close_up"},
                    "composition": {"layout": "center"},
                    "action": {"actor": "raises product"},
                    "emotion": {"label": "curious"},
                    "product_presence": "required",
                    "product_confidence": 0.91,
                    "product_evidence": [{"kind": "visual", "span": [900, 1300]}],
                    "anchor_candidates": [{"time_ms": 1100, "role": "hero"}],
                    "source_span": {"start": 0, "end": 1800},
                }
            ],
            "duration_ms": 1800,
        }
    )
    shot = payload.shots[0]
    assert shot.shot_key == "hook"
    assert shot.start == 0 and shot.end == 1800
    assert shot.product_confidence == pytest.approx(0.91)
    assert shot.anchor_candidates[0]["time_ms"] == 1100


def test_fixture_gemini_adapter_returns_structured_data_without_network() -> None:
    from app.services.providers.atlas.gemini import GeminiAdapter

    adapter = GeminiAdapter.from_fixture(
        {
            "duration_ms": 2000,
            "shots": [
                {
                    "shot_key": "s1",
                    "start": 0,
                    "end": 2000,
                    "purpose": "proof",
                    "product_presence": "optional",
                    "product_confidence": 0.4,
                    "product_evidence": [{"kind": "visual"}],
                    "anchor_candidates": [{"time_ms": 900}],
                    "source_span": {"start": 0, "end": 2000},
                }
            ],
        }
    )
    result = adapter.analyze_video({"duration_ms": 2000})
    assert result.shots[0].shot_key == "s1"
    assert result.shots[0].review_status == "needs_human_review"


def test_script_claim_ids_must_be_from_catalog_and_high_fidelity_locks_duration() -> None:
    from app.schemas_commercial import ScriptVersionPayload
    from app.services.commercial.replication import (
        ScriptContractError,
        validate_script_contract,
    )

    script = ScriptVersionPayload(
        mode="high_fidelity",
        dialogue="清爽不粘腻",
        visual_prompt="close product shot",
        action_prompt="hold product",
        product_presence="required",
        claim_ids=["c-approved"],
        duration_ms=1800,
        CTA="立即了解",
        shot_key="s1",
    )
    validate_script_contract(script, catalog_claim_ids={"c-approved"}, locked_durations={"s1": 1800})
    with pytest.raises(ScriptContractError):
        validate_script_contract(
            script.model_copy(update={"claim_ids": ["unknown"]}),
            catalog_claim_ids={"c-approved"},
            locked_durations={"s1": 1800},
        )
    with pytest.raises(ScriptContractError):
        validate_script_contract(
            script.model_copy(update={"duration_ms": 1700}),
            catalog_claim_ids={"c-approved"},
            locked_durations={"s1": 1800},
        )


def test_structural_rewrite_can_change_duration_within_shot_bound() -> None:
    from app.schemas_commercial import ScriptVersionPayload
    from app.services.commercial.replication import validate_script_contract

    script = ScriptVersionPayload(
        mode="structural_rewrite",
        dialogue="试试看",
        visual_prompt="product",
        action_prompt="show",
        product_presence="optional",
        claim_ids=[],
        duration_ms=1500,
        CTA="点击查看",
        shot_key="s1",
    )
    validate_script_contract(script, catalog_claim_ids=set(), locked_durations={"s1": 1800})
