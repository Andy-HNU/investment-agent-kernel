from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import orchestrator.engine as orchestrator_engine
import goal_solver.engine as goal_solver_engine
from goal_solver.engine import run_goal_solver
from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal_solver_input_base["goal"],
        "cashflow_plan": goal_solver_input_base["cashflow_plan"],
        "constraints": goal_solver_input_base["constraints"],
        "universe": {
            "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
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
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def _estimated_candidate_context() -> dict[str, object]:
    return {
        "allocation_name": "base_allocation",
        "product_probability_method": "product_proxy_adjustment_estimate",
        "bucket_expected_return_adjustments": {"equity_cn": 0.01},
        "bucket_volatility_multipliers": {"equity_cn": 1.05},
        "selected_product_ids": ["eq_core"],
        "selected_proxy_refs": ["tinyshare://510300.SH"],
        "product_simulation_input": {
            "frequency": "daily",
            "simulation_method": "product_estimated_path",
            "coverage_summary": {
                "selected_product_count": 2,
                "observed_product_count": 1,
                "inferred_product_count": 1,
                "missing_product_count": 0,
                "weight_adjusted_coverage": 0.75,
                "distribution_ready_coverage": 0.60,
                "explanation_ready_coverage": 0.50,
            },
            "products": [],
        },
        "formal_path_preflight": {
            "formal_path_required": True,
            "execution_policy": "formal_estimation_allowed",
            "run_outcome_status": "degraded",
            "degradation_reasons": ["product_independent_coverage_incomplete"],
            "blocking_predicates": [],
            "estimation_basis": "proxy_path",
        },
    }


def _historical_distribution_input() -> dict[str, object]:
    return {
        "frequency": "monthly",
        "historical_return_series": {
            "equity_cn": [0.012, -0.015, 0.011, 0.009, -0.006, 0.014, -0.012, 0.010, 0.008, -0.004, 0.013, -0.009],
            "bond_cn": [0.002, 0.001, 0.002, 0.001, 0.001, 0.002, 0.001, 0.002, 0.001, 0.001, 0.002, 0.001],
            "gold": [0.004, -0.002, 0.003, 0.002, -0.001, 0.004, -0.002, 0.003, 0.002, -0.001, 0.004, -0.002],
            "satellite": [0.020, -0.026, 0.018, 0.013, -0.010, 0.022, -0.019, 0.016, 0.011, -0.008, 0.020, -0.014],
        },
        "regime_series": ["normal", "stress", "normal", "normal", "stress", "normal", "stress", "normal", "normal", "stress", "normal", "normal"],
        "tail_df": 7.0,
    }


@pytest.mark.contract
def test_run_goal_solver_surfaces_success_event_spec_formal_estimated_result_spec_and_expected_return_decomposition(
    goal_solver_input_base,
    monkeypatch,
):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["solver_params"]["simulation_mode"] = "historical_block_bootstrap"
    solver_input["solver_params"]["distribution_input"] = _historical_distribution_input()
    solver_input["candidate_product_contexts"] = {
        "base_allocation": _estimated_candidate_context(),
    }

    def _fake_run_monte_carlo(
        _weights: dict[str, float],
        _cashflow_schedule: list[float],
        _initial_value: float,
        _goal_amount: float,
        _market_state,
        _n_paths: int,
        _seed: int,
        *,
        mode: str = "static_gaussian",
        distribution_input=None,
    ):
        assert mode == "historical_block_bootstrap"
        assert distribution_input is not None
        return (
            0.61,
            {"expected_terminal_value": 2_750_000.0},
            goal_solver_engine.RiskSummary(
                max_drawdown_90pct=0.12,
                terminal_value_tail_mean_95=2_020_000.0,
                shortfall_probability=0.39,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)
    recommended = result.recommended_result
    frontier_recommended = result.frontier_analysis.recommended if result.frontier_analysis is not None else None

    assert recommended.success_event_spec is not None
    assert recommended.success_event_spec.to_dict()["horizon_months"] == solver_input["goal"]["horizon_months"]
    assert recommended.success_event_spec.to_dict()["target_type"] == "goal_amount"
    assert recommended.success_event_spec.to_dict()["target_value"] == pytest.approx(solver_input["goal"]["goal_amount"])
    assert recommended.success_event_spec.to_dict()["contribution_policy"] == "continue_monthly_contribution"
    assert recommended.success_event_spec.to_dict()["rebalancing_policy"] == "not_explicitly_modeled"
    assert recommended.success_event_spec.to_dict()["return_basis"] == "nominal"
    assert recommended.success_event_spec.to_dict()["fee_basis"] == "transaction_cost_only"
    assert recommended.formal_estimated_result_spec is not None
    assert recommended.formal_estimated_result_spec.to_dict()["estimation_basis"] == "proxy_path"
    assert recommended.formal_estimated_result_spec.to_dict()["minimum_estimated_weight_adjusted_coverage"] == pytest.approx(0.75)
    assert recommended.formal_estimated_result_spec.to_dict()["minimum_explanation_ready_coverage"] == pytest.approx(0.50)
    assert recommended.expected_return_decomposition is not None
    decomposition = recommended.expected_return_decomposition.to_dict()
    component_total = sum(float(value) for value in decomposition["component_contributions"].values())
    assert result.simulation_mode_used == "historical_block_bootstrap"
    assert decomposition["decomposition_basis"] == "weighted_bucket_expected_return"
    assert decomposition["additivity_convention"] == "simple_sum"
    assert decomposition["residual"] == pytest.approx(recommended.expected_annual_return - component_total)
    assert frontier_recommended is not None
    assert frontier_recommended.success_event_spec.to_dict()["horizon_months"] == solver_input["goal"]["horizon_months"]
    assert frontier_recommended.expected_return_decomposition.to_dict()["additivity_convention"] == "simple_sum"


@pytest.mark.contract
def test_run_orchestrator_serializes_goal_solver_payload_contract_fields_through_live_result(
    goal_solver_input_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _fake_run_monte_carlo(
        _weights: dict[str, float],
        _cashflow_schedule: list[float],
        _initial_value: float,
        _goal_amount: float,
        _market_state,
        _n_paths: int,
        _seed: int,
        *,
        mode: str = "static_gaussian",
        distribution_input=None,
    ):
        assert mode == "historical_block_bootstrap"
        assert distribution_input is not None
        return (
            0.61,
            {"expected_terminal_value": 2_750_000.0},
            goal_solver_engine.RiskSummary(
                max_drawdown_90pct=0.12,
                terminal_value_tail_mean_95=2_020_000.0,
                shortfall_probability=0.39,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    solver_input = {
        **deepcopy(goal_solver_input_base),
        "solver_params": {
            **deepcopy(goal_solver_input_base["solver_params"]),
            "simulation_mode": "historical_block_bootstrap",
            "distribution_input": _historical_distribution_input(),
        },
        "candidate_product_contexts": {
            "base_allocation": _estimated_candidate_context(),
        },
    }
    goal_solver_output = run_goal_solver(solver_input)

    def _fake_runtime_optimizer(**kwargs):
        return SimpleNamespace(
            candidate_poverty=False,
            mode=kwargs["mode"],
            ev_report={
                "recommended_action": {"type": "observe"},
                "ranked_actions": [
                    {
                        "action": {"type": "observe"},
                        "score": {"total": 0.0},
                        "rank": 1,
                        "is_recommended": True,
                        "recommendation_reason": "contract fake runtime result",
                    }
                ],
                "confidence_flag": "low",
                "confidence_reason": "contract fake runtime result",
                "goal_solver_baseline": goal_solver_output.recommended_result.success_probability,
                "goal_solver_after_recommended": goal_solver_output.recommended_result.success_probability,
            },
            state_snapshot={"mode": kwargs["mode"].value},
            candidates_generated=1,
            candidates_after_filter=1,
            run_timestamp="2026-03-29T12:00:00Z",
            optimizer_params_version="v1.0.0",
            goal_solver_params_version=goal_solver_output.params_version,
        )

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "v13_package3_orchestrator"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output,
        prior_solver_input=solver_input,
    )

    payload = result.to_dict()

    assert result.status == WorkflowStatus.COMPLETED
    assert result.run_outcome_status == "degraded"
    assert result.resolved_result_category == "degraded_formal_result"
    assert result.disclosure_decision["disclosure_level"] == "range_only"
    assert result.goal_solver_output is not None
    assert result.goal_solver_output.simulation_mode_used == "historical_block_bootstrap"
    assert result.goal_solver_output.recommended_result.success_event_spec is not None
    assert result.goal_solver_output.recommended_result.formal_estimated_result_spec is not None
    assert result.goal_solver_output.recommended_result.expected_return_decomposition is not None
    assert payload["goal_solver_output"]["recommended_result"]["success_event_spec"]["horizon_months"] == goal_solver_input_base["goal"]["horizon_months"]
    assert payload["goal_solver_output"]["recommended_result"]["formal_estimated_result_spec"]["estimation_basis"] == "proxy_path"
    assert payload["goal_solver_output"]["recommended_result"]["expected_return_decomposition"]["additivity_convention"] == "simple_sum"
    assert payload["goal_solver_output"]["simulation_mode_used"] == "historical_block_bootstrap"
    assert payload["goal_solver_output"]["frontier_analysis"]["recommended"]["success_event_spec"]["horizon_months"] == goal_solver_input_base["goal"]["horizon_months"]
