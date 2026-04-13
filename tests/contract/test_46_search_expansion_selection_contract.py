from __future__ import annotations

import pytest

from product_mapping.cardinality import BucketCountResolution
from product_mapping.construction import build_bucket_subset
from product_mapping.search_expansion import (
    candidate_pool_limit,
    normalize_search_expansion_level,
    resolve_search_stop_reason,
)
from product_mapping.types import (
    ProductCandidate,
    ProductPolicyNewsAudit,
    RuntimeProductCandidate,
    SearchExpansionRecommendation,
)


@pytest.mark.contract
def test_candidate_pool_limit_grows_by_search_expansion_level():
    assert candidate_pool_limit("equity_cn", "L0_compact") == 4
    assert candidate_pool_limit("equity_cn", "L1_expanded") == 6
    assert candidate_pool_limit("satellite", "L1_expanded") == 8
    assert candidate_pool_limit("satellite", "L2_diversified") == 10
    assert candidate_pool_limit("bond_cn", "L3_exhaustive") == 4
    assert candidate_pool_limit("equity_cn", "L3_exhaustive") == 10


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


@pytest.mark.contract
@pytest.mark.parametrize("bucket", [None, "mystery_bucket"])
def test_candidate_pool_limit_rejects_invalid_bucket(bucket):
    with pytest.raises(ValueError, match="invalid bucket"):
        candidate_pool_limit(bucket, "L0_compact")


def test_l1_expanded_considers_more_satellite_candidates_than_l0() -> None:
    candidates = [
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_chip_etf",
                product_name="Chip ETF",
                asset_bucket="satellite",
                product_family="theme_etf_chip",
                wrapper_type="etf",
                provider_source="test",
                liquidity_tier="high",
                fee_tier="low",
                tags=["satellite", "technology", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=0,
        ),
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_robotics_etf",
                product_name="Robotics ETF",
                asset_bucket="satellite",
                product_family="theme_etf_robotics",
                wrapper_type="etf",
                provider_source="test",
                liquidity_tier="medium",
                fee_tier="low",
                tags=["satellite", "technology", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=1,
        ),
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_ai_etf",
                product_name="AI ETF",
                asset_bucket="satellite",
                product_family="theme_etf_ai",
                wrapper_type="etf",
                provider_source="test",
                liquidity_tier="medium",
                fee_tier="low",
                tags=["satellite", "technology", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=2,
        ),
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_cloud_etf",
                product_name="Cloud ETF",
                asset_bucket="satellite",
                product_family="theme_etf_cloud",
                wrapper_type="etf",
                provider_source="test",
                liquidity_tier="medium",
                fee_tier="low",
                tags=["satellite", "technology", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=3,
        ),
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_semiconductor_etf",
                product_name="Semiconductor ETF",
                asset_bucket="satellite",
                product_family="theme_etf_semiconductor",
                wrapper_type="etf",
                provider_source="test",
                liquidity_tier="medium",
                fee_tier="low",
                tags=["satellite", "technology", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=4,
        ),
        RuntimeProductCandidate(
            candidate=ProductCandidate(
                product_id="satellite_energy_fund",
                product_name="Energy Fund",
                asset_bucket="satellite",
                product_family="theme_fund_energy",
                wrapper_type="fund",
                provider_source="test",
                liquidity_tier="medium",
                fee_tier="low",
                tags=["satellite", "cyclical", "cn"],
                risk_labels=["主题波动", "权益波动"],
            ),
            registry_index=5,
            policy_news_audit=ProductPolicyNewsAudit(
                status="observed",
                realtime_eligible=True,
                influence_scope="satellite_dynamic",
                score=0.95,
                dominant_direction="positive",
                matched_signal_ids=["policy-energy-1"],
                matched_tags=["cyclical", "energy"],
            ),
        ),
    ]
    resolution = BucketCountResolution(
        bucket="satellite",
        requested_count=2,
        resolved_count=2,
        source="explicit_user",
        fully_satisfied=True,
        unmet_reasons=[],
        alternative_counts_considered=[],
    )

    compact_selected = build_bucket_subset(
        bucket="satellite",
        bucket_weight=0.20,
        requested_resolution=resolution,
        candidates=candidates,
        search_expansion_level="L0_compact",
        required_annual_return=0.14,
        goal_horizon_months=48,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.28,
        market_pressure_score=18.0,
    )
    expanded_selected = build_bucket_subset(
        bucket="satellite",
        bucket_weight=0.20,
        requested_resolution=resolution,
        candidates=candidates,
        search_expansion_level="L1_expanded",
        required_annual_return=0.14,
        goal_horizon_months=48,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.28,
        market_pressure_score=18.0,
    )

    compact_ids = {candidate.candidate.product_id for candidate in compact_selected}
    expanded_ids = {candidate.candidate.product_id for candidate in expanded_selected}

    assert "satellite_chip_etf" in compact_ids
    assert "satellite_energy_fund" not in compact_ids
    assert expanded_ids == {"satellite_chip_etf", "satellite_energy_fund"}
    assert compact_ids != expanded_ids
