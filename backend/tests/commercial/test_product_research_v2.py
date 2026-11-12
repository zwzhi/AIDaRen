from app.services.commercial.product_research import (
    merge_fact_candidates,
    resolve_product_variant,
    should_refresh,
)


def test_variant_resolution_never_invents_sku():
    assert resolve_product_variant({"candidate_count": 1}).status == "single_variant"
    result = resolve_product_variant({"candidate_count": 3})
    assert result.status == "ambiguous"
    assert result.variant_key == ""


def test_variant_resolution_uses_known_identity_fields():
    result = resolve_product_variant({"sku": "A-01", "shade_code": "001", "spec": "3.5g"})
    assert result.status == "resolved"
    assert result.variant_key == "A-01|001|3.5g"


def test_confirmed_fact_is_not_overwritten_by_refresh():
    merged, conflicts = merge_fact_candidates(
        {"texture": "水状", "size": "30ml"},
        {"texture": "乳状", "color": "透明"},
        locked_fields={"texture", "size"},
    )
    assert merged == {"texture": "水状", "size": "30ml", "color": "透明"}
    assert conflicts["texture"] == {"confirmed": "水状", "candidate": "乳状"}


def test_research_is_reused_until_input_or_ttl_changes():
    assert should_refresh(input_hash="a", stored_input_hash="a") is False
    assert should_refresh(input_hash="b", stored_input_hash="a") is True
    assert should_refresh(input_hash="a", stored_input_hash="a", stale=True) is True
