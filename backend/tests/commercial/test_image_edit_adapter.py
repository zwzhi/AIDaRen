"""Task 4 contract tests for the fixture-first Image2.6 anchor adapter."""
from __future__ import annotations

import pytest


def _request(**overrides):
    from app.services.providers.atlas.image_edit import ImageEditRequest

    payload = dict(
        source_anchor={"id": 11, "source_asset_id": 101, "shot_key": "hook", "sequence": 0, "time_ms": 1000},
        actor_version={"id": 21, "image_asset_ids": [201]},
        product_version=None,
        product_presence="absent",
        prompt="替换为我方达人，保持构图和动作",
    )
    payload.update(overrides)
    return ImageEditRequest(**payload)


def test_fixture_capabilities_are_unverified_and_never_call_network() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter

    adapter = ImageEditAdapter.from_fixture({"model_id": "image2.6-sandbox"})
    caps = adapter.probe_capabilities()

    assert caps.model_id == "image2.6-sandbox"
    assert caps.capability_verified is False
    assert caps.supports_anchor_reference is True
    assert caps.supports_actor_reference is True


def test_absent_rejects_product_reference() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter, ImageEditInputError

    with pytest.raises(ImageEditInputError) as exc:
        ImageEditAdapter.from_fixture().edit_anchor(
            _request(product_version={"id": 31, "image_asset_ids": [301]})
        )
    assert exc.value.code == "PRODUCT_INPUT_FORBIDDEN"


def test_required_without_product_reference_is_rejected() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter, ImageEditInputError

    with pytest.raises(ImageEditInputError) as exc:
        ImageEditAdapter.from_fixture().edit_anchor(_request(product_presence="required"))
    assert exc.value.code == "PRODUCT_REFERENCE_REQUIRED"


def test_unknown_presence_is_human_review_and_result_is_anchor_candidate() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter

    result = ImageEditAdapter.from_fixture().edit_anchor(_request(product_presence="unknown"))

    assert result.status == "anchor_candidate"
    assert result.review_status == "needs_human_review"
    assert result.needs_human_review is True
    assert result.parent_anchor_id == 11
    assert result.prompt_hash


def test_edit_result_has_complete_lineage_and_no_h3_approval() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter

    result = ImageEditAdapter.from_fixture().edit_anchor(_request())

    assert result.status == "anchor_candidate"
    assert result.review_status == "pending"
    assert result.source_asset_id == 101
    assert result.actor_version_id == 21
    assert result.product_version_id is None
    assert result.model_id
    assert result.model_version
    assert result.edited_asset_payload["source_role"] == "source_derived_anchor_candidate"
    assert result.edited_asset_payload["derived_from_asset_id"] == 101
    assert result.h3_eligible is False


def test_real_unverified_model_is_blocked_before_submit() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter, ImageEditCapabilityError

    adapter = ImageEditAdapter(model_id="image2.6", mode="real")
    with pytest.raises(ImageEditCapabilityError) as exc:
        adapter.edit_anchor(_request())
    assert exc.value.code == "MODEL_CAPABILITY_UNVERIFIED"

