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
def test_run_calibration_populates_conservative_static_gaussian_distribution_state(
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
    assert result.distribution_model_state.simulation_mode == "static_gaussian"
    assert result.distribution_model_state.selected_mode == "static_gaussian"
    assert result.distribution_model_state.mode_resolution_decision.selected_mode == "static_gaussian"
    assert result.distribution_model_state.mode_resolution_decision.downgraded is False
    assert result.calibration_summary.sample_count == 0
    assert result.calibration_summary.calibration_quality == "acceptable"
    assert result.calibration_summary.source_ref == f"{bundle.bundle_id}::static_gaussian"
    assert result.to_dict()["distribution_model_state"]["selected_mode"] == "static_gaussian"
    assert result.to_dict()["calibration_summary"]["calibration_quality"] == "acceptable"


@pytest.mark.contract
def test_calibration_result_coerces_nested_distribution_state_and_summary_from_dicts(
    calibration_result_base,
):
    payload = dict(calibration_result_base)
    payload["distribution_model_state"] = {
        "simulation_mode": "static_gaussian",
        "selected_mode": "static_gaussian",
        "tail_model": None,
        "regime_sensitive": False,
        "jump_overlay_enabled": False,
        "eligibility_decision": {
            "simulation_mode": "static_gaussian",
            "minimum_sample_months": 0,
            "minimum_weight_adjusted_coverage": 0.0,
            "requires_regime_stability": False,
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
            "requested_mode": "static_gaussian",
            "selected_mode": "static_gaussian",
            "eligible_modes_in_order": ["static_gaussian"],
            "ineligibility_action": "mark_unavailable",
            "downgraded": False,
            "downgrade_reason": None,
        },
        "calibration_summary": {
            "sample_count": 0,
            "brier_score": None,
            "reliability_buckets": [],
            "regime_breakdown": [],
            "calibration_quality": "insufficient_sample",
            "source_ref": "bundle_acc001::static_gaussian",
        },
        "source_ref": "bundle_acc001::static_gaussian",
        "as_of": "2026-03-29T12:00:00Z",
        "data_status": "observed",
    }
    payload["calibration_summary"] = payload["distribution_model_state"]["calibration_summary"]

    result = CalibrationResult(**payload)

    assert isinstance(result.distribution_model_state, DistributionModelState)
    assert isinstance(result.calibration_summary, CalibrationSummary)
    assert result.distribution_model_state.selected_mode == "static_gaussian"
    assert result.calibration_summary.calibration_quality == "insufficient_sample"
    assert result.to_dict()["distribution_model_state"]["eligibility_decision"]["simulation_mode"] == "static_gaussian"
