from __future__ import annotations

from copy import deepcopy

import pytest

import goal_solver.engine as goal_solver_engine
from goal_solver.engine import run_goal_solver
from goal_solver.types import RiskSummary


@pytest.fixture
def goal_solver_input_base() -> dict[str, object]:
    return {
        "snapshot_id": "snapshot_product_simulation_contract",
        "account_profile_id": "product_simulation_contract_user",
        "goal": {
            "goal_amount": 1_200_000.0,
            "horizon_months": 36,
            "goal_description": "product simulation contract target",
            "success_prob_threshold": 0.70,
            "priority": "important",
            "risk_preference": "moderate",
        },
        "cashflow_plan": {
            "monthly_contribution": 3_000.0,
            "annual_step_up_rate": 0.0,
            "cashflow_events": [],
        },
        "current_portfolio_value": 180_000.0,
        "candidate_allocations": [
            {
                "name": "balanced",
                "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
                "complexity_score": 0.12,
                "description": "balanced candidate",
            }
        ],
        "constraints": {
            "max_drawdown_tolerance": 0.20,
            "ips_bucket_boundaries": {
                "equity_cn": [0.20, 0.70],
                "bond_cn": [0.10, 0.50],
                "gold": [0.00, 0.25],
                "satellite": [0.00, 0.15],
            },
            "satellite_cap": 0.15,
            "theme_caps": {"technology": 0.10},
            "qdii_cap": 0.20,
            "liquidity_reserve_min": 0.05,
        },
        "solver_params": {
            "version": "goal_solver_params_contract",
            "n_paths": 128,
            "n_paths_lightweight": 32,
            "seed": 7,
            "market_assumptions": {
                "expected_returns": {
                    "equity_cn": 0.08,
                    "bond_cn": 0.03,
                    "gold": 0.04,
                    "satellite": 0.10,
                },
                "volatility": {
                    "equity_cn": 0.18,
                    "bond_cn": 0.04,
                    "gold": 0.12,
                    "satellite": 0.24,
                },
                "correlation_matrix": {
                    "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.15, "gold": 0.20, "satellite": 0.75},
                    "bond_cn": {"equity_cn": 0.15, "bond_cn": 1.0, "gold": 0.10, "satellite": 0.15},
                    "gold": {"equity_cn": 0.20, "bond_cn": 0.10, "gold": 1.0, "satellite": 0.15},
                    "satellite": {"equity_cn": 0.75, "bond_cn": 0.15, "gold": 0.15, "satellite": 1.0},
                },
            },
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
def test_run_goal_solver_emits_product_independent_probability_when_series_present(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["solver_params"] = {
        **deepcopy(goal_solver_input_base["solver_params"]),
        "simulation_mode": "historical_block_bootstrap",
        "distribution_input": _historical_distribution_input(),
    }
    solver_input["candidate_product_contexts"] = {
        "balanced": {
            "allocation_name": "balanced",
            "product_probability_method": "product_independent_path",
            "bucket_expected_return_adjustments": {"equity_cn": 0.01},
            "bucket_volatility_multipliers": {"equity_cn": 1.05},
            "selected_product_ids": ["eq_core", "bond_core"],
            "selected_proxy_refs": ["tinyshare://510300.SH", "tinyshare://511010.SH"],
            "product_history_profiles": [],
            "product_simulation_input": {
                "frequency": "daily",
                "simulation_method": "product_independent_path",
                "audit_window": {
                    "start_date": "2025-01-02",
                    "end_date": "2026-04-03",
                    "trading_days": 250,
                    "observed_days": 250,
                    "inferred_days": 0,
                },
                "coverage_summary": {
                    "selected_product_count": 2,
                    "observed_product_count": 2,
                    "missing_product_count": 0,
                },
                "products": [
                    {
                        "product_id": "eq_core",
                        "asset_bucket": "equity_cn",
                        "target_weight": 0.55,
                        "source_ref": "tinyshare://510300.SH",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2025-01-02",
                        "observed_end_date": "2026-04-03",
                        "observed_points": 250,
                        "inferred_points": 0,
                        "observation_dates": ["2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"],
                        "return_series": [0.01, -0.005, 0.007, 0.003],
                    },
                    {
                        "product_id": "bond_core",
                        "asset_bucket": "bond_cn",
                        "target_weight": 0.30,
                        "source_ref": "tinyshare://511010.SH",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2025-01-02",
                        "observed_end_date": "2026-04-03",
                        "observed_points": 250,
                        "inferred_points": 0,
                        "observation_dates": ["2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"],
                        "return_series": [0.002, 0.001, 0.0015, 0.0005],
                    },
                ],
            },
        }
    }

    observed_expected_returns: list[dict[str, float]] = []

    def _fake_run_monte_carlo(
        _weights: dict[str, float],
        _cashflow_schedule: list[float],
        _initial_value: float,
        _goal_amount: float,
        market_state,
        _n_paths: int,
        _seed: int,
        *,
        mode: str = "static_gaussian",
        distribution_input=None,
    ):
        assert mode == "historical_block_bootstrap"
        assert distribution_input is not None
        observed_expected_returns.append(dict(market_state.expected_returns))
        probability = 0.51 if len(observed_expected_returns) == 1 else 0.60
        terminal = 2_100_000.0 if len(observed_expected_returns) == 1 else 2_260_000.0
        drawdown = 0.13 if len(observed_expected_returns) == 1 else 0.16
        return (
            probability,
            {"expected_terminal_value": terminal},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=terminal * 0.8,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.09,
            ),
        )

    def _fake_run_product_independent(*_args, **_kwargs):
        return (
            0.68,
            {"expected_terminal_value": 2_480_000.0},
            RiskSummary(
                max_drawdown_90pct=0.18,
                terminal_value_tail_mean_95=1_980_000.0,
                shortfall_probability=0.32,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)
    monkeypatch.setattr(goal_solver_engine, "_run_product_independent_monte_carlo", _fake_run_product_independent)

    result = run_goal_solver(solver_input)

    assert len(observed_expected_returns) == 2
    assert result.recommended_result.bucket_success_probability == pytest.approx(0.51)
    assert result.recommended_result.product_proxy_adjusted_success_probability == pytest.approx(0.60)
    assert result.recommended_result.product_independent_success_probability == pytest.approx(0.68)
    assert result.recommended_result.product_probability_method == "product_independent_path"
    assert result.recommended_result.success_probability == pytest.approx(0.68)
    assert result.recommended_result.expected_terminal_value == pytest.approx(2_480_000.0)
    assert result.recommended_result.risk_summary.max_drawdown_90pct == pytest.approx(0.18)
    assert result.frontier_analysis is not None
    assert result.frontier_analysis.recommended.product_independent_success_probability == pytest.approx(0.68)
    assert result.frontier_analysis.highest_probability.product_independent_success_probability == pytest.approx(0.68)


@pytest.mark.contract
def test_run_goal_solver_prefers_product_independent_probability_for_frontier_ranking(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["candidate_allocations"] = [
        {
            "name": "balanced",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "balanced candidate",
        },
        {
            "name": "growth",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.18,
            "description": "growth candidate",
        },
    ]
    solver_input["candidate_product_contexts"] = {
        "balanced": {
            "allocation_name": "balanced",
            "product_probability_method": "product_independent_path",
            "product_simulation_input": {
                "frequency": "daily",
                "simulation_method": "product_independent_path",
                "products": [
                    {
                        "product_id": "eq_bal",
                        "asset_bucket": "equity_cn",
                        "target_weight": 0.55,
                        "return_series": [0.01, 0.01],
                        "observation_dates": ["2025-01-03", "2025-01-06"],
                    }
                ],
            },
        },
        "growth": {
            "allocation_name": "growth",
            "product_probability_method": "product_proxy_adjustment_estimate",
        },
    }

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        equity_weight = float(weights.get("equity_cn", 0.0))
        probability = 0.55 if equity_weight > 0.60 else 0.50
        return (
            probability,
            {"expected_terminal_value": 2_000_000.0 + probability * 100_000.0},
            RiskSummary(
                max_drawdown_90pct=0.20,
                terminal_value_tail_mean_95=1_500_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)
    monkeypatch.setattr(
        goal_solver_engine,
        "_run_product_independent_monte_carlo",
        lambda **_kwargs: (
            0.90,
            {"expected_terminal_value": 2_900_000.0},
            RiskSummary(
                max_drawdown_90pct=0.18,
                terminal_value_tail_mean_95=2_000_000.0,
                shortfall_probability=0.10,
                terminal_shortfall_p5_vs_initial=0.05,
            ),
        ),
    )

    result = run_goal_solver(solver_input)

    assert result.recommended_allocation.name == "balanced"
    assert result.recommended_result.product_independent_success_probability == pytest.approx(0.90)
    assert result.frontier_analysis is not None
    assert result.frontier_analysis.highest_probability.allocation_name == "balanced"
    assert result.frontier_diagnostics["frontier_max_effective_success_probability"] == pytest.approx(0.90)
