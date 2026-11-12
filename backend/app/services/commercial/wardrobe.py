"""Shared wardrobe rules and actor-specific look cache keys."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def wardrobe_scope_allows(
    scope: str,
    *,
    owner_user_id: int | None,
    requester_user_id: int,
    wardrobe_team_id: int | None,
    requester_team_id: int | None,
    project_id: int | None = None,
    wardrobe_project_id: int | None = None,
) -> bool:
    scope = str(scope or "personal")
    if scope == "personal":
        return owner_user_id == requester_user_id
    if scope == "team":
        return wardrobe_team_id is not None and wardrobe_team_id == requester_team_id
    if scope == "project":
        return project_id is not None and project_id == wardrobe_project_id
    return False


def actor_wardrobe_look_key(
    actor_version_id: int,
    wardrobe_version_id: int,
    *,
    pose: dict[str, Any] | None = None,
    source_hash: str = "",
) -> str:
    payload = {
        "actor_version_id": int(actor_version_id),
        "wardrobe_version_id": int(wardrobe_version_id),
        "pose": pose or {},
        "source_hash": source_hash,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

