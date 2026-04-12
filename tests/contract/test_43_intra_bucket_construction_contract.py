from __future__ import annotations

import pytest

from product_mapping import BucketCardinalityPreference, build_execution_plan, resolve_bucket_count
from product_mapping.cardinality import BucketCountResolution


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
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count == 1


def test_resolve_bucket_count_responds_to_real_goal_context_inputs() -> None:
    low_context = resolve_bucket_count(
        bucket="equity_cn",
        bucket_weight=0.40,
        goal_horizon_months=12,
        horizon_months=None,
        risk_preference="conservative",
        max_drawdown_tolerance=0.10,
        current_market_pressure_score=5.0,
        implied_required_annual_return=0.03,
    )
    high_context = resolve_bucket_count(
        bucket="equity_cn",
        bucket_weight=0.40,
        goal_horizon_months=36,
        horizon_months=None,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.35,
        current_market_pressure_score=40.0,
        implied_required_annual_return=0.10,
    )

    assert low_context.resolved_count < high_context.resolved_count
    assert low_context.resolved_count == 1
    assert high_context.resolved_count >= 2


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


def test_bond_cn_auto_policy_caps_to_two_products() -> None:
    resolution = resolve_bucket_count(
        bucket="bond_cn",
        bucket_weight=0.20,
        goal_horizon_months=36,
        horizon_months=None,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        implied_required_annual_return=0.09,
    )

    assert resolution.source == "auto_policy"
    assert resolution.resolved_count == 2


def test_explicit_satellite_request_is_not_collapsed_by_minimum_position_rules() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "satellite": 0.04,
            "cash_liquidity": 0.96,
        },
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="satellite",
                mode="target_count",
                target_count=3,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    satellite_items = [item for item in plan.items if item.asset_bucket == "satellite"]
    explanation = plan.bucket_construction_explanations["satellite"]

    assert len(satellite_items) == 3
    assert explanation.actual_count == 3
    assert explanation.unmet_reason is None
    assert any("minimum_position_guidance" in reason for reason in explanation.why_split)


def test_explicit_bond_request_is_not_collapsed_by_minimum_position_rules() -> None:
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={
            "bond_cn": 0.10,
            "cash_liquidity": 0.90,
        },
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
    assert explanation.unmet_reason is None
