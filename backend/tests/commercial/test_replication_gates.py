from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def _evidence(**overrides):
    from app.services.commercial.rights import RightsEvidence

    values = {
        "subject_type": "source_video",
        "subject_id": 1,
        "scope": "adapt_and_generate",
        "territory": "CN",
        "channels": ("douyin",),
        "valid_until": None,
        "revoked_at": None,
        "verified": True,
    }
    values.update(overrides)
    return RightsEvidence(**values)


def test_verified_rights_allow_high_fidelity_generation():
    from app.services.commercial.rights import evaluate_rights_gate

    decision = evaluate_rights_gate([_evidence()])

    assert decision.allowed is True
    assert decision.reason_code == "OK"


def test_expired_or_revoked_rights_block_high_fidelity_generation():
    from app.services.commercial.rights import evaluate_rights_gate

    expired = _evidence(valid_until=datetime.now(UTC) - timedelta(seconds=1))
    revoked = _evidence(revoked_at=datetime.now(UTC))

    assert evaluate_rights_gate([expired]).reason_code == "RIGHTS_EXPIRED"
    assert evaluate_rights_gate([revoked]).reason_code == "RIGHTS_REVOKED"


def test_missing_verified_rights_block_generation():
    from app.services.commercial.rights import evaluate_rights_gate

    decision = evaluate_rights_gate([_evidence(verified=False)])

    assert decision.allowed is False
    assert decision.reason_code == "RIGHTS_UNVERIFIED"


def test_replication_status_transitions_reject_invalid_edges():
    from app.services.commercial.replication import InvalidReplicationTransition, transition_status

    assert transition_status("draft", "analyzing") == "analyzing"
    assert transition_status("script_review", "anchor_review") == "anchor_review"
    with pytest.raises(InvalidReplicationTransition):
        transition_status("draft", "completed")


def test_quote_acceptance_requires_pending_user_acceptance():
    from app.services.commercial.replication import QuoteStateError, accept_quote

    assert accept_quote("pending_user_acceptance") == "accepted"
    with pytest.raises(QuoteStateError):
        accept_quote("draft")
