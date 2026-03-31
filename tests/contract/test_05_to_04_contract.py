from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from snapshot_ingestion.engine import build_snapshot_bundle
from tests.helpers.contracts import assert_has_keys


def _market_raw() -> dict:
    return {
        "raw_volatility": {
            "equity_cn": 0.30,
            "bond_cn": 0.16,
            "gold": 0.22,
            "satellite": 0.28,
        },
        "liquidity_scores": {
            "equity_cn": 0.90,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.60,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": {
            "equity_cn": 0.08,
            "bond_cn": 0.03,
            "gold": 0.025,
            "satellite": 0.10,
        },
    }


def _account_raw(goal_solver_input_base: dict, live_portfolio_base: dict) -> dict:
    return {
        "weights": live_portfolio_base["weights"],
        "total_value": live_portfolio_base["total_value"],
        "available_cash": live_portfolio_base["available_cash"],
        "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
    }


def _goal_raw(goal_solver_input_base: dict) -> dict:
    return dict(goal_solver_input_base["goal"])


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = dict(goal_solver_input_base["constraints"])
    constraints.update(
        {
            "rebalancing_band": 0.10,
            "forbidden_actions": [],
            "cooling_period_days": 3,
            "soft_preferences": {},
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": {
                "equity_cn": None,
                "bond_cn": None,
                "gold": None,
                "satellite": "technology",
            },
            "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
        }
    )
    return constraints


@pytest.mark.contract
def test_05_exports_runtime_consumable_states(calibration_result_base):
    assert_has_keys(
        calibration_result_base["market_state"],
        [
            "risk_environment",
            "volatility_regime",
            "liquidity_status",
            "valuation_positions",
            "correlation_spike_alert",
        ],
    )
    assert_has_keys(
        calibration_result_base["constraint_state"],
        [
            "ips_bucket_boundaries",
            "satellite_cap",
            "effective_drawdown_threshold",
            "bucket_category",
            "bucket_to_theme",
        ],
    )
    assert_has_keys(
        calibration_result_base["behavior_state"],
        [
            "behavior_penalty_coeff",
            "recent_chasing_flag",
            "high_emotion_flag",
            "panic_flag",
        ],
    )


@pytest.mark.contract
def test_05_exports_runtime_params(calibration_result_base):
    rp = calibration_result_base["runtime_optimizer_params"]
    assert_has_keys(
        rp,
        [
            "deviation_soft_threshold",
            "deviation_hard_threshold",
            "satellite_overweight_threshold",
            "drawdown_event_threshold",
            "min_candidates",
            "max_candidates",
        ],
    )


@pytest.mark.contract
def test_run_calibration_propagates_runtime_semantics_to_04_inputs(
    goal_solver_input_base,
    live_portfolio_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw={
            "recent_chase_risk": "moderate",
            "recent_panic_risk": "low",
            "trade_frequency_30d": 4.0,
            "override_count_90d": 2,
            "cooldown_active": True,
            "cooldown_until": "2026-04-02T00:00:00Z",
            "behavior_penalty_coeff": 0.5,
            "high_emotion_flag": True,
        },
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert result.market_state.risk_environment == "high"
    assert result.behavior_state.cooldown_active is True
    assert result.constraint_state.cooldown_currently_active is True
    assert (
        result.constraint_state.effective_drawdown_threshold
        < result.constraint_state.max_drawdown_tolerance
    )
    assert result.market_state.source_bundle_id == result.source_bundle_id
    assert result.constraint_state.source_bundle_id == result.source_bundle_id
    assert result.behavior_state.source_bundle_id == result.source_bundle_id
    assert result.runtime_optimizer_params.version.startswith("runtime_params_")
