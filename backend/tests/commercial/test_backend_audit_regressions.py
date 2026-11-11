from __future__ import annotations

from decimal import Decimal

import pytest


def test_analysis_cache_for_shared_source_is_user_scoped():
    from app.services.commercial.analysis import analysis_cache_key

    assert analysis_cache_key(team_id=None, source_sha256="a" * 64, model_id="m", requested_by=1) != analysis_cache_key(team_id=None, source_sha256="a" * 64, model_id="m", requested_by=2)


def test_budget_pool_rejects_negative_total():
    from app.api.commercial.productions import BudgetPoolBody

    with pytest.raises(Exception):
        BudgetPoolBody(total_usd=Decimal("-1"))


def test_compose_ranges_reject_non_positive_span():
    from app.api.commercial.productions import ComposeSelection

    with pytest.raises(Exception):
        ComposeSelection(attempt_id=1, ranges=[[10, 10]])

