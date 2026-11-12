from app.services.commercial.actor_references import rank_actor_references
from app.services.commercial.wardrobe import actor_wardrobe_look_key, wardrobe_scope_allows


def test_reference_retrieval_returns_top_three_only():
    refs = [
        {"sequence": 2, "asset_id": 2, "angle": "front", "shot_scale": "medium", "expression": "smile", "pose": "open", "quality_score": 1},
        {"sequence": 1, "asset_id": 1, "angle": "profile", "shot_scale": "medium", "expression": "neutral", "pose": "side", "quality_score": 1},
        {"sequence": 3, "asset_id": 3, "angle": "front", "shot_scale": "close", "expression": "smile", "pose": "open", "quality_score": 1},
        {"sequence": 4, "asset_id": 4, "angle": "front", "shot_scale": "medium", "expression": "smile", "pose": "open", "quality_score": 0},
    ]
    ranked = rank_actor_references(refs, {"angle": "front", "shot_scale": "medium", "expression": "smile", "pose": "open"})
    assert len(ranked) == 3
    assert ranked[0]["frame"]["asset_id"] == 2


def test_wardrobe_scope_isolated_by_owner_and_team():
    assert wardrobe_scope_allows("personal", owner_user_id=1, requester_user_id=1, wardrobe_team_id=None, requester_team_id=None)
    assert not wardrobe_scope_allows("personal", owner_user_id=1, requester_user_id=2, wardrobe_team_id=None, requester_team_id=None)
    assert wardrobe_scope_allows("team", owner_user_id=1, requester_user_id=2, wardrobe_team_id=9, requester_team_id=9)
    assert not wardrobe_scope_allows("team", owner_user_id=1, requester_user_id=2, wardrobe_team_id=9, requester_team_id=8)


def test_actor_wardrobe_look_cache_is_stable():
    a = actor_wardrobe_look_key(1, 2, pose={"angle": "front"}, source_hash="x")
    b = actor_wardrobe_look_key(1, 2, pose={"angle": "front"}, source_hash="x")
    c = actor_wardrobe_look_key(1, 3, pose={"angle": "front"}, source_hash="x")
    assert a == b and a != c
