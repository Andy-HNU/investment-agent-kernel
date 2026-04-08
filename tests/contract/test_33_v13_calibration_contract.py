from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from calibration.types import (
    CalibrationResult,
    CalibrationSummary,
    DistributionModelState,
    ModeResolutionDecision,
    SimulationModeEligibility,
)
from snapshot_ingestion.engine import build_snapshot_bundle


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    historical_equity = [
        0.011,
        -0.018,
        0.014,
        0.009,
        -0.006,
        0.017,
        -0.021,
        0.013,
        0.008,
        -0.004,
        0.019,
        -0.016,
        0.012,
        -0.009,
        0.015,
        0.010,
        -0.007,
        0.016,
        -0.013,
        0.011,
        0.006,
        -0.005,
        0.014,
        -0.012,
        0.010,
        -0.008,
        0.013,
        0.009,
        -0.006,
        0.018,
        -0.014,
        0.012,
        0.007,
        -0.004,
        0.015,
        -0.010,
    ]
    historical_bond = [
        0.0020,
        0.0015,
        0.0018,
        0.0016,
        0.0014,
        0.0017,
        0.0013,
        0.0019,
        0.0015,
        0.0014,
        0.0018,
        0.0012,
        0.0017,
        0.0015,
        0.0016,
        0.0014,
        0.0018,
        0.0013,
        0.0019,
        0.0015,
        0.0014,
        0.0017,
        0.0016,
        0.0013,
        0.0018,
        0.0015,
        0.0016,
        0.0014,
        0.0019,
        0.0013,
        0.0018,
        0.0015,
        0.0017,
        0.0014,
        0.0018,
        0.0015,
    ]
    historical_gold = [
        0.004,
        -0.002,
        0.003,
        0.002,
        -0.001,
        0.005,
        -0.003,
        0.004,
        0.002,
        -0.002,
        0.003,
        -0.001,
        0.004,
        -0.002,
        0.003,
        0.002,
        -0.001,
        0.005,
        -0.002,
        0.004,
        0.002,
        -0.001,
        0.003,
        -0.002,
        0.004,
        -0.001,
        0.003,
        0.002,
        -0.001,
        0.004,
        -0.002,
        0.003,
        0.002,
        -0.001,
        0.004,
        -0.002,
    ]
    historical_satellite = [
        0.021,
        -0.030,
        0.019,
        0.014,
        -0.011,
        0.024,
        -0.028,
        0.020,
        0.013,
        -0.010,
        0.026,
        -0.023,
        0.018,
        -0.015,
        0.022,
        0.016,
        -0.012,
        0.025,
        -0.020,
        0.019,
        0.012,
        -0.009,
        0.021,
        -0.017,
        0.018,
        -0.013,
        0.020,
        0.015,
        -0.011,
        0.024,
        -0.018,
        0.017,
        0.011,
        -0.008,
        0.020,
        -0.014,
    ]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.9,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.6,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
        "correlation_spike_alert": False,
        "historical_dataset": {
            "dataset_id": "contract_history",
            "version_id": "contract_history_v1",
            "as_of": "2026-03-29T12:00:00Z",
            "source_name": "contract_history",
            "source_ref": "contract://historical_dataset",
            "lookback_months": 36,
            "frequency": "monthly",
            "coverage_status": "verified",
            "return_series": {
                "equity_cn": historical_equity,
                "bond_cn": historical_bond,
                "gold": historical_gold,
                "satellite": historical_satellite,
            },
            "audit_window": {
                "start_date": "2023-04-01",
                "end_date": "2026-03-29",
                "trading_days": 756,
                "observed_days": 756,
                "inferred_days": 0,
            },
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
    goal = goal_solver_input_base["goal"]
    return {
        "goal_amount": goal["goal_amount"],
        "horizon_months": goal["horizon_months"],
        "goal_description": goal["goal_description"],
        "success_prob_threshold": goal["success_prob_threshold"],
        "priority": goal["priority"],
        "risk_preference": goal["risk_preference"],
    }


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = goal_solver_input_base["constraints"]
    return {
        **constraints,
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


@pytest.mark.contract
def test_run_calibration_populates_non_gaussian_distribution_state_with_real_calibration_outputs(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert isinstance(result, CalibrationResult)
    assert isinstance(result.distribution_model_state, DistributionModelState)
    assert isinstance(result.calibration_summary, CalibrationSummary)
    assert isinstance(result.distribution_model_state.eligibility_decision, SimulationModeEligibility)
    assert isinstance(result.distribution_model_state.mode_resolution_decision, ModeResolutionDecision)
    assert result.distribution_model_state.simulation_mode != "static_gaussian"
    assert result.distribution_model_state.selected_mode != "static_gaussian"
    assert result.distribution_model_state.mode_resolution_decision.selected_mode == result.distribution_model_state.selected_mode
    assert result.distribution_model_state.mode_resolution_decision.downgraded is False
    assert result.calibration_summary.sample_count >= 24
    assert result.calibration_summary.calibration_quality == "acceptable"
    assert result.calibration_summary.brier_score is not None
    assert result.calibration_summary.reliability_buckets
    assert result.calibration_summary.regime_breakdown
    assert result.calibration_summary.source_ref.endswith(result.distribution_model_state.selected_mode)
    assert result.to_dict()["distribution_model_state"]["selected_mode"] == result.distribution_model_state.selected_mode
    assert result.to_dict()["calibration_summary"]["calibration_quality"] == "acceptable"


@pytest.mark.contract
def test_calibration_result_coerces_nested_distribution_state_and_summary_from_dicts(
    calibration_result_base,
):
    payload = dict(calibration_result_base)
    payload["distribution_model_state"] = {
        "simulation_mode": "historical_block_bootstrap",
        "selected_mode": "historical_block_bootstrap",
        "tail_model": "empirical",
        "regime_sensitive": True,
        "jump_overlay_enabled": False,
        "eligibility_decision": {
            "simulation_mode": "historical_block_bootstrap",
            "minimum_sample_months": 24,
            "minimum_weight_adjusted_coverage": 0.8,
            "requires_regime_stability": True,
            "requires_jump_calibration": False,
            "allowed_result_categories": [
                "formal_independent_result",
                "formal_estimated_result",
                "degraded_formal_result",
            ],
            "downgrade_target": None,
            "ineligibility_action": "mark_unavailable",
        },
        "mode_resolution_decision": {
            "requested_mode": "historical_block_bootstrap",
            "selected_mode": "historical_block_bootstrap",
            "eligible_modes_in_order": ["historical_block_bootstrap", "student_t", "static_gaussian"],
            "ineligibility_action": "mark_unavailable",
            "downgraded": False,
            "downgrade_reason": None,
        },
        "calibration_summary": {
            "sample_count": 36,
            "brier_score": 0.18,
            "reliability_buckets": [{"bucket": "0.4-0.6", "predicted_mean": 0.52, "observed_hit_rate": 0.5, "sample_count": 12}],
            "regime_breakdown": [{"regime": "normal", "sample_count": 24, "brier_score": 0.16}],
            "calibration_quality": "acceptable",
            "source_ref": "bundle_acc001::historical_block_bootstrap",
        },
        "source_ref": "bundle_acc001::historical_block_bootstrap",
        "as_of": "2026-03-29T12:00:00Z",
        "data_status": "observed",
    }
    payload["calibration_summary"] = payload["distribution_model_state"]["calibration_summary"]

    result = CalibrationResult(**payload)

    assert isinstance(result.distribution_model_state, DistributionModelState)
    assert isinstance(result.calibration_summary, CalibrationSummary)
    assert result.distribution_model_state.selected_mode == "historical_block_bootstrap"
    assert result.calibration_summary.calibration_quality == "acceptable"
    assert result.to_dict()["distribution_model_state"]["eligibility_decision"]["simulation_mode"] == "historical_block_bootstrap"
