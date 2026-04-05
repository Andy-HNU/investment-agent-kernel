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


@pytest.mark.contract
def test_run_goal_solver_emits_product_independent_probability_when_series_present(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
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
    ):
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

