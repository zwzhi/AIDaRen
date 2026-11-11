"""复刻项目状态和报价接受的确定性规则。"""
from __future__ import annotations


class InvalidReplicationTransition(ValueError):
    pass


class QuoteStateError(ValueError):
    pass


REPLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"analyzing", "cancelled"}),
    "analyzing": frozenset({"analyzed", "failed", "cancelled"}),
    "analyzed": frozenset({"script_review", "failed", "cancelled"}),
    "script_review": frozenset({"anchor_review", "failed", "cancelled"}),
    "anchor_review": frozenset({"voice_ready", "failed", "cancelled"}),
    "voice_ready": frozenset({"preview_ready", "failed", "cancelled"}),
    "preview_ready": frozenset({"finalizing", "failed", "cancelled"}),
    "finalizing": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"analyzing", "cancelled"}),
    "cancelled": frozenset(),
}

QUOTE_STATES = frozenset({"draft", "pending_user_acceptance", "accepted", "expired", "settled", "disputed"})


def transition_status(current: str, target: str) -> str:
    if target not in REPLICATION_TRANSITIONS.get(current, frozenset()):
        raise InvalidReplicationTransition(f"不允许从 {current} 转移到 {target}")
    return target


def accept_quote(status: str) -> str:
    if status != "pending_user_acceptance":
        raise QuoteStateError("只有待用户确认的报价可以接受")
    return "accepted"
