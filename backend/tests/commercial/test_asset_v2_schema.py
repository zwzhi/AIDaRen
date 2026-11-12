from app.database import Base
import app.models_commercial_v2  # noqa: F401


def test_v2_asset_tables_are_registered():
    expected = {
        "cv_product_variants",
        "cv_product_research_runs",
        "cv_product_sources",
        "cv_product_fact_candidates",
        "cv_product_states",
        "cv_product_state_assets",
        "cv_product_capabilities",
        "cv_wardrobe_items",
        "cv_wardrobe_versions",
        "cv_wardrobe_sets",
        "cv_actor_wardrobe_looks",
        "cv_actor_reference_sets",
        "cv_actor_reference_frames",
        "cv_voice_sources",
        "cv_workflow_runs",
        "cv_workflow_stage_runs",
    }
    assert expected <= set(Base.metadata.tables)


def test_v2_tables_have_immutable_and_scope_keys():
    variant = Base.metadata.tables["cv_product_variants"]
    assert {"product_id", "variant_key", "resolution_status", "status"} <= set(variant.c.keys())
    assert any(c.name == "uq_cv_product_variant_key" for c in variant.constraints)

    wardrobe = Base.metadata.tables["cv_wardrobe_items"]
    assert {"scope", "team_id", "status"} <= set(wardrobe.c.keys())

    workflow = Base.metadata.tables["cv_workflow_stage_runs"]
    assert {"workflow_run_id", "stage", "status", "attempts"} <= set(workflow.c.keys())
    assert any(c.name == "uq_cv_workflow_stage" for c in workflow.constraints)
