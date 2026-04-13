from __future__ import annotations

import pytest

from product_mapping.search_expansion import (
    candidate_pool_limit,
    normalize_search_expansion_level,
    resolve_search_stop_reason,
)
from product_mapping.types import SearchExpansionRecommendation


@pytest.mark.contract
def test_candidate_pool_limit_grows_by_search_expansion_level():
    assert candidate_pool_limit("equity_cn", "L0_compact") == 4
    assert candidate_pool_limit("equity_cn", "L1_expanded") == 6
    assert candidate_pool_limit("satellite", "L1_expanded") == 8
    assert candidate_pool_limit("satellite", "L2_diversified") == 10


@pytest.mark.contract
def test_search_expansion_level_normalization_accepts_exhaustive_level():
    assert normalize_search_expansion_level("L3_exhaustive") == "L3_exhaustive"


@pytest.mark.contract
def test_search_expansion_stop_reason_emits_target_distance_stall():
    reason = resolve_search_stop_reason(
        success_improvement=0.001,
        target_distance_improvement=0.0005,
        drawdown_improvement=0.001,
        hard_stop_reason=None,
        consecutive_small_gain_count=2,
    )
    assert reason == "marginal_target_distance_gain_too_small"


@pytest.mark.contract
def test_search_expansion_result_requires_visible_delta_fields():
    result = SearchExpansionRecommendation(
        search_expansion_level="L1_expanded",
        why_this_level_was_run="user_not_satisfied",
        why_search_stopped="candidate_supply_exhausted",
        new_product_ids_added=["cn_equity_low_vol_fund"],
        products_removed=["cn_equity_dividend_etf"],
    )
    assert result.search_expansion_level == "L1_expanded"
    assert result.new_product_ids_added == ["cn_equity_low_vol_fund"]
