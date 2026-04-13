from __future__ import annotations

import pytest

from product_mapping import BucketCardinalityPreference, build_execution_plan, load_builtin_catalog, resolve_bucket_count
from product_mapping.cardinality import BucketCountResolution
from product_mapping.construction import _has_duplicate_exposure_too_high
from product_mapping.relationships import rank_construction_candidates, score_candidate_subset
from product_mapping.types import RuntimeProductCandidate


def test_bucket_count_resolution_prefers_explicit_user_request() -> None:
    resolution = resolve_bucket_count(
        bucket="satellite",
        bucket_weight=0.20,
        horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        explicit_request=BucketCardinalityPreference(
            bucket="satellite",
            mode="target_count",
            target_count=5,
            min_count=None,
            max_count=None,
            source="user_requested",
        ),
        persisted_preference=BucketCardinalityPreference(
            bucket="satellite",
            mode="target_count",
            target_count=2,
            min_count=None,
            max_count=None,
            source="persisted_user",
        ),
    )

    assert resolution.requested_count == 5
    assert resolution.resolved_count == 5
    assert resolution.source == "explicit_user"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "invalid", "target_count": 1, "min_count": None, "max_count": None, "source": "user_requested"}, "invalid mode"),
        ({"mode": "target_count", "target_count": 1, "min_count": None, "max_count": None, "source": "invalid"}, "invalid source"),
        ({"mode": "target_count", "target_count": 0, "min_count": None, "max_count": None, "source": "user_requested"}, "target_count must be >= 1"),
        ({"mode": "count_range", "target_count": None, "min_count": None, "max_count": None, "source": "user_requested"}, "at least one of target_count"),
        ({"mode": "count_range", "target_count": None, "min_count": 4, "max_count": 3, "source": "user_requested"}, "min_count must be <= max_count"),
        ({"mode": "count_range", "target_count": 5, "min_count": 2, "max_count": 4, "source": "user_requested"}, "target_count must fall within min_count and max_count"),
    ],
)
def test_bucket_cardinality_preference_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        BucketCardinalityPreference(bucket="satellite", **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"resolved_count": 0, "source": "auto_policy", "fully_satisfied": True}, "resolved_count must be >= 1"),
        ({"resolved_count": 1, "source": "invalid", "fully_satisfied": True}, "invalid source"),
        ({"resolved_count": 1, "source": "auto_policy", "fully_satisfied": "false"}, "fully_satisfied must be a bool"),
    ],
)
def test_bucket_count_resolution_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        BucketCountResolution(
            bucket="satellite",
            requested_count=1,
            unmet_reasons=[],
            alternative_counts_considered=[],
            **kwargs,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "explicit_request": BucketCardinalityPreference(
                bucket="equity_cn",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        },
        {
            "persisted_preference": BucketCardinalityPreference(
                bucket="bond_cn",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="persisted_user",
            ),
        },
    ],
)
def test_resolve_bucket_count_rejects_bucket_mismatch(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="bucket must match bucket being resolved"):
        resolve_bucket_count(
            bucket="satellite",
            bucket_weight=0.20,
            horizon_months=36,
            risk_preference="moderate",
            max_drawdown_tolerance=0.20,
            current_market_pressure_score=30.0,
            **kwargs,
        )


def test_resolve_bucket_count_uses_auto_policy_branch() -> None:
    resolution = resolve_bucket_count(
        bucket="gold",
        bucket_weight=0.10,
        horizon_months=12,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=10.0,
        required_return_gap=0.0,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count == 1


@pytest.mark.parametrize(
    ("bucket", "bucket_weight", "goal_horizon_months", "risk_preference", "max_drawdown_tolerance", "current_market_pressure_score", "required_return_gap"),
    [
        ("equity_cn", 0.40, 12, "moderate", 0.20, 30.0, 0.00),
        ("equity_cn", 0.40, 18, "moderate", 0.20, 10.0, 0.00),
        ("equity_cn", 0.40, 24, "moderate", 0.20, 30.0, 0.00),
        ("satellite", 0.15, 36, "moderate", 0.20, 10.0, 0.00),
        ("satellite", 0.20, 36, "moderate", 0.20, 10.0, 0.00),
        ("satellite", 0.30, 36, "moderate", 0.20, 10.0, 0.00),
        ("bond_cn", 0.19, 36, "moderate", 0.20, 10.0, 0.00),
        ("bond_cn", 0.20, 24, "moderate", 0.20, 10.0, 0.00),
    ],
)
def test_resolve_bucket_count_returns_positive_auto_seed(
    bucket: str,
    bucket_weight: float,
    goal_horizon_months: int,
    risk_preference: str,
    max_drawdown_tolerance: float,
    current_market_pressure_score: float,
    required_return_gap: float,
) -> None:
    resolution = resolve_bucket_count(
        bucket=bucket,
        bucket_weight=bucket_weight,
        goal_horizon_months=goal_horizon_months,
        horizon_months=goal_horizon_months,
        risk_preference=risk_preference,
        max_drawdown_tolerance=max_drawdown_tolerance,
        current_market_pressure_score=current_market_pressure_score,
        required_return_gap=required_return_gap,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count >= 1


def test_equity_auto_policy_aggressive_high_gap_off_rule_wins_over_light_band() -> None:
    resolution = resolve_bucket_count(
        bucket="equity_cn",
        bucket_weight=0.40,
        goal_horizon_months=18,
        horizon_months=18,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.18,
        current_market_pressure_score=10.0,
        required_return_gap=0.03,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count == 1


def test_equity_auto_policy_ignores_implied_return_when_gap_is_unknown() -> None:
    resolution = resolve_bucket_count(
        bucket="equity_cn",
        bucket_weight=0.40,
        goal_horizon_months=18,
        horizon_months=18,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.18,
        current_market_pressure_score=10.0,
        required_return_gap=None,
        implied_required_annual_return=0.12,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count == 2


def test_build_execution_plan_ignores_implied_return_gap_when_gap_is_unknown() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "equity_cn": 0.40,
            "cash_liquidity": 0.60,
        },
        goal_horizon_months=18,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.18,
        current_market_pressure_score=10.0,
        implied_required_annual_return=0.12,
    )

    equity_items = [item for item in plan.items if item.asset_bucket == "equity_cn"]

    assert len(equity_items) == 3
    assert plan.bucket_construction_explanations["equity_cn"].actual_count == 3


def test_equity_bucket_can_return_two_products_when_requested() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "equity_cn": 0.40,
            "bond_cn": 0.20,
            "gold": 0.10,
            "satellite": 0.20,
            "cash_liquidity": 0.10,
        },
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="equity_cn",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    equity_items = [item for item in plan.items if item.asset_bucket == "equity_cn"]

    assert len(equity_items) == 2
    assert plan.bucket_construction_explanations["equity_cn"].requested_count == 2
    assert "equity_cn" not in plan.bucket_construction_suggestions


def test_satellite_bucket_can_build_requested_five_member_structure_or_flag_unmet_reason() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "satellite": 0.20,
            "cash_liquidity": 0.80,
        },
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="satellite",
                mode="target_count",
                target_count=5,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    satellite_items = [item for item in plan.items if item.asset_bucket == "satellite"]
    explanation = plan.bucket_construction_explanations["satellite"]

    assert len(satellite_items) in {1, 2, 3, 4, 5}
    assert explanation.requested_count == 5
    assert explanation.actual_count == len(satellite_items)
    assert explanation.actual_count == 5 or explanation.unmet_reason is not None


def test_gold_bucket_stays_single_product_even_when_requested_more() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "gold": 0.10,
            "cash_liquidity": 0.90,
        },
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="gold",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    gold_items = [item for item in plan.items if item.asset_bucket == "gold"]

    assert len(gold_items) == 1
    assert plan.bucket_construction_explanations["gold"].actual_count == 1
    assert plan.bucket_construction_suggestions == {}


def test_cash_liquidity_bucket_stays_single_product_even_when_requested_more() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "cash_liquidity": 0.30,
            "equity_cn": 0.70,
        },
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="cash_liquidity",
                mode="target_count",
                target_count=3,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    cash_items = [item for item in plan.items if item.asset_bucket == "cash_liquidity"]

    assert len(cash_items) == 1
    assert plan.bucket_construction_explanations["cash_liquidity"].actual_count == 1
    assert plan.bucket_construction_suggestions == {}


def test_bond_cn_auto_policy_returns_positive_seed() -> None:
    resolution = resolve_bucket_count(
        bucket="bond_cn",
        bucket_weight=0.20,
        goal_horizon_months=36,
        horizon_months=None,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        required_return_gap=0.03,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count >= 1


def test_explicit_satellite_request_is_not_collapsed_by_minimum_position_rules() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={"satellite": 0.03, "cash_liquidity": 0.97},
        account_total_value=1000.0,
        current_weights={"satellite": 0.03, "cash_liquidity": 0.97},
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="satellite",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    satellite_items = [item for item in plan.items if item.asset_bucket == "satellite"]
    explanation = plan.bucket_construction_explanations["satellite"]

    assert len(satellite_items) == 2
    assert explanation.actual_count == 2
    assert all(item.target_amount is not None for item in satellite_items)
    assert explanation.count_satisfied is False
    assert explanation.unmet_reason is not None
    assert "minimum_weight_breach" in explanation.diagnostic_codes
    assert "count_preference_not_fully_satisfied" in explanation.diagnostic_codes
    assert any("minimum_weight_breach" in reason for reason in explanation.why_split)
    assert plan.bucket_construction_suggestions["satellite"]["member_product_ids"]
    for item in satellite_items:
        assert item.current_weight is None
        assert item.current_amount is None
        assert item.trade_direction is None
        assert item.trade_amount is None
        assert item.estimated_fee is None
        assert item.estimated_slippage is None
    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.amount_closure_delta == 0.0
    assert "account_amount_not_closed" not in plan.execution_realism_summary.reasons


def test_explicit_bond_request_is_not_collapsed_by_minimum_position_rules() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={"bond_cn": 0.09, "cash_liquidity": 0.91},
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="bond_cn",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    bond_items = [item for item in plan.items if item.asset_bucket == "bond_cn"]
    explanation = plan.bucket_construction_explanations["bond_cn"]

    assert len(bond_items) == 2
    assert explanation.actual_count == 2
    assert explanation.count_satisfied is False
    assert explanation.unmet_reason is not None
    assert "minimum_weight_breach" in explanation.diagnostic_codes
    assert "count_preference_not_fully_satisfied" in explanation.diagnostic_codes
    assert plan.bucket_construction_suggestions["bond_cn"]["member_product_ids"]


def test_auto_policy_split_keeps_count_satisfied_despite_advisory_diagnostics() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "satellite": 0.20,
            "cash_liquidity": 0.80,
        },
    )

    explanation = plan.bucket_construction_explanations["satellite"]

    assert explanation.actual_count >= 1
    assert explanation.count_satisfied is True
    assert explanation.unmet_reason is None


def test_auto_policy_stops_satellite_when_next_member_no_longer_improves_subset_score() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "satellite": 0.15,
            "cash_liquidity": 0.85,
        },
    )

    satellite_items = [item for item in plan.items if item.asset_bucket == "satellite"]
    explanation = plan.bucket_construction_explanations["satellite"]

    catalog = {candidate.product_id: candidate for candidate in load_builtin_catalog()}
    ranked = rank_construction_candidates(
        "satellite",
        [
            RuntimeProductCandidate(candidate=catalog["cn_satellite_chip_etf"], registry_index=0),
            RuntimeProductCandidate(candidate=catalog["cn_satellite_robotics_etf"], registry_index=1),
            RuntimeProductCandidate(candidate=catalog["cn_satellite_energy_etf"], registry_index=2),
        ],
    )

    assert len(satellite_items) == 2
    assert explanation.actual_count == 2
    assert explanation.count_satisfied is True
    assert {item.primary_product_id for item in satellite_items} == {
        "cn_satellite_chip_etf",
        "cn_satellite_energy_etf",
    }
    assert score_candidate_subset("satellite", ranked[:2]) > score_candidate_subset("satellite", ranked[:3])


def test_duplicate_exposure_heuristic_uses_family_and_theme_not_wrapper_only() -> None:
    catalog = {candidate.product_id: candidate for candidate in load_builtin_catalog()}
    chip = RuntimeProductCandidate(candidate=catalog["cn_satellite_chip_etf"], registry_index=0)
    robotics = RuntimeProductCandidate(candidate=catalog["cn_satellite_robotics_etf"], registry_index=1)
    energy = RuntimeProductCandidate(candidate=catalog["cn_satellite_energy_etf"], registry_index=2)

    assert _has_duplicate_exposure_too_high([chip, robotics]) is True
    assert _has_duplicate_exposure_too_high([chip, energy]) is False
