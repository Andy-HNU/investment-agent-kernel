from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from goal_solver.engine import run_goal_solver
from goal_solver.types import SimulationMode
from orchestrator.engine import _apply_calibration_to_goal_solver_input
from snapshot_ingestion.engine import build_snapshot_bundle
import snapshot_ingestion.types as snapshot_types
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


def _market_raw_with_distribution_inputs(goal_solver_input_base: dict) -> dict:
    market_raw = _market_raw(goal_solver_input_base)
    panel_cls = getattr(snapshot_types, "HistoricalReturnPanelRaw", dict)
    regime_cls = getattr(snapshot_types, "RegimeFeatureSnapshotRaw", dict)
    jump_cls = getattr(snapshot_types, "JumpEventHistoryRaw", dict)
    proxy_cls = getattr(snapshot_types, "BucketProxyMappingRaw", dict)
    market_raw["historical_return_panel"] = panel_cls(
        dataset_id="panel-20260329",
        version_id="panel-20260329:v1",
        as_of="2026-03-29",
        source_name="fixture_panel",
        lookback_months=36,
        return_series={
            "equity_cn": [0.01, 0.02, -0.01, 0.03],
            "bond_cn": [0.002, 0.004, 0.001, 0.003],
            "gold": [0.006, -0.002, 0.004, 0.003],
            "satellite": [0.015, 0.025, -0.02, 0.03],
        },
        notes=["panel fixture for contract test"],
    )
    market_raw["regime_feature_snapshot"] = regime_cls(
        snapshot_id="regime-20260329",
        as_of="2026-03-29T12:00:00Z",
        feature_values={"inflation": 0.62, "growth": 0.41, "liquidity": 0.35},
        inferred_regime="tightening",
        notes=["policy regime proxy"],
    )
    market_raw["jump_event_history"] = jump_cls(
        history_id="jump-20260329",
        as_of="2026-03-29T12:00:00Z",
        events=[
            {
                "event_id": "evt-1",
                "bucket": "equity_cn",
                "event_type": "policy_shock",
                "magnitude": -0.08,
                "event_date": "2026-02-17",
            }
        ],
        notes=["single event fixture"],
    )
    market_raw["bucket_proxy_mapping"] = proxy_cls(
        mapping_id="proxy-20260329",
        as_of="2026-03-29T12:00:00Z",
        bucket_to_proxy={
            "equity_cn": "000300.SH",
            "bond_cn": "CBA00001.CS",
            "gold": "AU9999.SGE",
            "satellite": "KWEB",
        },
        notes=["proxy fixture"],
    )
    return market_raw


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


@pytest.mark.contract
def test_run_calibration_result_carries_distribution_model_state_payload(
    goal_solver_input_base,
    live_portfolio_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw_with_distribution_inputs(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
        policy_news_signals=[
            {
                "signal_id": "signal-tightening",
                "as_of": "2026-03-29T10:00:00Z",
                "source_type": "analysis",
                "source_refs": ["memo://macro"],
                "policy_regime": "tightening",
                "macro_uncertainty": "high",
                "confidence": 0.88,
            }
        ],
    )

    result = run_calibration(bundle, prior_calibration=None)
    payload = result.to_dict()

    assert "distribution_model_state" in payload
    assert_has_keys(
        payload["distribution_model_state"],
        ["version", "garch_state", "dcc_state", "jump_overlay_state", "is_degraded", "notes"],
    )
    assert payload["distribution_model_state"]["is_degraded"] is True
    assert payload["distribution_model_state"]["garch_state"]["estimation_mode"] == "conservative_fallback"


@pytest.mark.contract
def test_calibration_to_goal_solver_preserves_requested_simulation_mode_and_distribution_state(
    goal_solver_input_base,
    live_portfolio_base,
):
    requested_input = dict(goal_solver_input_base)
    requested_solver_params = dict(goal_solver_input_base["solver_params"])
    requested_solver_params["simulation_mode"] = "garch_t_dcc_jump"
    requested_input["solver_params"] = requested_solver_params

    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw_with_distribution_inputs(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    calibration_result = run_calibration(
        bundle,
        prior_calibration=None,
        default_goal_solver_params=requested_solver_params,
    )
    updated_solver_input = _apply_calibration_to_goal_solver_input(
        requested_input,
        calibration_result.to_dict(),
    )

    solver_output = run_goal_solver(updated_solver_input)

    assert calibration_result.goal_solver_params.simulation_mode == SimulationMode.GARCH_T_DCC_JUMP
    assert calibration_result.goal_solver_params.distribution_input is not None
    assert calibration_result.goal_solver_params.distribution_input.garch_t_state
    assert calibration_result.goal_solver_params.distribution_input.dcc_state
    assert calibration_result.goal_solver_params.distribution_input.jump_state
    assert "correlation_matrix" in calibration_result.goal_solver_params.distribution_input.dcc_state
    assert "bucket_jump_probability_1m" in calibration_result.goal_solver_params.distribution_input.jump_state
    assert solver_output.simulation_mode_used == SimulationMode.GARCH_T_DCC_JUMP
    assert any(
        note
        == "simulation_mode requested=garch_t_dcc_jump used=garch_t_dcc_jump downgrade=false missing=none"
        for note in solver_output.solver_notes
    )
    assert any(
        note
        == "probability_model method=conditional_monte_carlo distribution=garch_t_dcc_jump requested_mode=garch_t_dcc_jump historical_backtest_used=true"
        for note in solver_output.solver_notes
    )


@pytest.mark.contract
def test_calibration_to_goal_solver_downgrades_when_historical_and_jump_inputs_are_missing(
    goal_solver_input_base,
    live_portfolio_base,
):
    requested_input = dict(goal_solver_input_base)
    requested_solver_params = dict(goal_solver_input_base["solver_params"])
    requested_solver_params["simulation_mode"] = "garch_t_dcc_jump"
    requested_input["solver_params"] = requested_solver_params

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

    calibration_result = run_calibration(
        bundle,
        prior_calibration=None,
        default_goal_solver_params=requested_solver_params,
    )
    updated_solver_input = _apply_calibration_to_goal_solver_input(
        requested_input,
        calibration_result.to_dict(),
    )

    solver_output = run_goal_solver(updated_solver_input)

    assert calibration_result.goal_solver_params.simulation_mode == SimulationMode.GARCH_T_DCC_JUMP
    assert calibration_result.goal_solver_params.distribution_input is not None
    assert calibration_result.goal_solver_params.distribution_input.garch_t_state == {}
    assert calibration_result.goal_solver_params.distribution_input.dcc_state == {}
    assert calibration_result.goal_solver_params.distribution_input.jump_state == {}
    assert solver_output.simulation_mode_used == SimulationMode.STATIC_GAUSSIAN
    assert any(
        note
        == "simulation_mode requested=garch_t_dcc_jump used=static_gaussian downgrade=true missing=garch_t_state,dcc_state,jump_state"
        for note in solver_output.solver_notes
    )
