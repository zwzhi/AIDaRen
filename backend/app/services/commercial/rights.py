"""权利证据和真实模型调用硬门。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable


@dataclass(frozen=True)
class RightsEvidence:
    subject_type: str
    subject_id: int
    scope: str
    territory: str
    channels: tuple[str, ...]
    valid_until: datetime | None
    revoked_at: datetime | None
    verified: bool


@dataclass(frozen=True)
class RightsDecision:
    allowed: bool
    reason_code: str
    reasons: tuple[str, ...] = ()


def evaluate_rights_gate(
    evidence: Iterable[RightsEvidence], *, now: datetime | None = None,
) -> RightsDecision:
    records = tuple(evidence)
    if not records:
        return RightsDecision(False, "RIGHTS_MISSING", ("缺少权利证据",))
    current = now or datetime.now(UTC)
    for item in records:
        if not item.verified:
            return RightsDecision(False, "RIGHTS_UNVERIFIED", (f"{item.subject_type}:{item.subject_id}",))
        if item.revoked_at is not None and item.revoked_at <= current:
            return RightsDecision(False, "RIGHTS_REVOKED", (f"{item.subject_type}:{item.subject_id}",))
        if item.valid_until is not None:
            expiry = item.valid_until if item.valid_until.tzinfo else item.valid_until.replace(tzinfo=UTC)
            if expiry <= current:
                return RightsDecision(False, "RIGHTS_EXPIRED", (f"{item.subject_type}:{item.subject_id}",))
    return RightsDecision(True, "OK")
