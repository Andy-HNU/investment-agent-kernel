from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from snapshot_ingestion.engine import build_snapshot_bundle
from tests.helpers.contracts import assert_has_keys


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.17,
            "bond_cn": 0.04,
            "gold": 0.10,
            "satellite": 0.21,
        },
        "liquidity_scores": {
            "equity_cn": 0.90,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.60,
        },
        "valuation_z_scores": {
            "equity_cn": 0.1,
            "bond_cn": 0.0,
            "gold": -0.2,
            "satellite": 1.5,
        },
        "expected_returns": {
            **assumptions["expected_returns"],
            "equity_cn": 0.09,
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
def test_calibration_result_contains_goal_solver_payload(calibration_result_base):
    assert_has_keys(
        calibration_result_base,
        [
            "market_assumptions",
            "goal_solver_params",
            "market_state",
            "constraint_state",
            "behavior_state",
            "runtime_optimizer_params",
            "ev_params",
        ],
    )


@pytest.mark.contract
def test_goal_solver_params_embed_market_assumptions(calibration_result_base):
    goal_solver_params = calibration_result_base["goal_solver_params"]
    assert "market_assumptions" in goal_solver_params
    ma = goal_solver_params["market_assumptions"]
    assert "expected_returns" in ma
    assert "volatility" in ma
    assert "correlation_matrix" in ma


@pytest.mark.contract
def test_calibration_param_meta_tracks_goal_solver_versions(calibration_result_base):
    meta = calibration_result_base["param_version_meta"]
    assert meta["goal_solver_params_version"] == calibration_result_base["goal_solver_params"]["version"]
    assert meta["can_be_replayed"] is True


@pytest.mark.contract
def test_run_calibration_preserves_prior_solver_knobs_while_refreshing_market_assumptions(
    goal_solver_input_base,
    live_portfolio_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    prior_params = {
        "version": "goal_solver_params_old",
        "n_paths": 9001,
        "n_paths_lightweight": 1234,
        "seed": 99,
        "ranking_mode_default": "balanced",
        "market_assumptions": goal_solver_input_base["solver_params"]["market_assumptions"],
    }

    result = run_calibration(
        bundle,
        prior_calibration=None,
        default_goal_solver_params=prior_params,
    )

    params = result.goal_solver_params
    assert params.n_paths == 9001
    assert params.n_paths_lightweight == 1234
    assert params.seed == 99
    assert params.ranking_mode_default.value == "balanced"
    assert params.version.startswith("goal_solver_params_")
    assert params.market_assumptions.expected_returns["equity_cn"] == 0.09
    assert params.market_assumptions.expected_returns != prior_params["market_assumptions"]["expected_returns"]
