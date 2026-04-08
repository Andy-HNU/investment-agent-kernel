from __future__ import annotations

from copy import deepcopy

import pytest

import goal_solver.engine as goal_solver_engine
from goal_solver.engine import infer_ranking_mode, run_goal_solver, run_goal_solver_lightweight
from goal_solver.types import RankingMode, RiskSummary


@pytest.mark.contract
def test_infer_ranking_mode_matches_doc_matrix():
    assert infer_ranking_mode("essential", "conservative") == RankingMode.SUFFICIENCY_FIRST
    assert infer_ranking_mode("important", "aggressive") == RankingMode.BALANCED
    assert infer_ranking_mode("aspirational", "moderate") == RankingMode.PROBABILITY_MAX
    assert infer_ranking_mode("unknown", "unknown") == RankingMode.SUFFICIENCY_FIRST


@pytest.mark.contract
def test_run_goal_solver_uses_inferred_balanced_mode_for_important_aggressive(
    goal_solver_input_base,
    monkeypatch,
):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["priority"] = "important"
    solver_input["goal"]["risk_preference"] = "aggressive"
    solver_input["candidate_allocations"] = [
        {
            "name": "high_prob_high_dd",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.40,
            "description": "higher probability but riskier",
        },
        {
            "name": "balanced_pick",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.20,
            "description": "slightly lower probability but much lower drawdown",
        },
    ]

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):
        if weights["equity_cn"] >= 0.70:
            probability = 0.74
            drawdown = 0.20
        else:
            probability = 0.72
            drawdown = 0.10
        return (
            probability,
            {"expected_terminal_value": 2_600_000.0},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=1_900_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.05,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert result.ranking_mode_used == RankingMode.BALANCED
    assert result.recommended_allocation.name == "balanced_pick"


@pytest.mark.contract
def test_run_goal_solver_respects_ranking_mode_override(
    goal_solver_input_base,
    monkeypatch,
):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["priority"] = "important"
    solver_input["goal"]["risk_preference"] = "aggressive"
    solver_input["ranking_mode_override"] = "probability_max"
    solver_input["candidate_allocations"] = [
        {
            "name": "high_prob_high_dd",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.40,
            "description": "higher probability but riskier",
        },
        {
            "name": "balanced_pick",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.20,
            "description": "slightly lower probability but much lower drawdown",
        },
    ]

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):
        if weights["equity_cn"] >= 0.70:
            probability = 0.74
            drawdown = 0.20
        else:
            probability = 0.72
            drawdown = 0.10
        return (
            probability,
            {"expected_terminal_value": 2_600_000.0},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=1_900_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.05,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert result.ranking_mode_used == RankingMode.PROBABILITY_MAX
    assert result.recommended_allocation.name == "high_prob_high_dd"
    assert any("source=override" in note and "probability_max" in note for note in result.solver_notes)


@pytest.mark.contract
def test_run_goal_solver_handles_no_feasible_allocation_with_solver_notes(
    goal_solver_input_base,
    monkeypatch,
):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["constraints"]["max_drawdown_tolerance"] = 0.05
    solver_input["constraints"]["satellite_cap"] = 0.05
    solver_input["candidate_allocations"] = [
        {
            "name": "too_risky_a",
            "weights": {"equity_cn": 0.80, "bond_cn": 0.05, "gold": 0.00, "satellite": 0.15},
            "complexity_score": 0.40,
            "description": "violates constraints",
        },
        {
            "name": "too_risky_b",
            "weights": {"equity_cn": 0.75, "bond_cn": 0.10, "gold": 0.00, "satellite": 0.15},
            "complexity_score": 0.30,
            "description": "violates constraints",
        },
    ]

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):
        probability = 0.60 if weights["equity_cn"] > 0.78 else 0.58
        return (
            probability,
            {"expected_terminal_value": 2_300_000.0},
            RiskSummary(
                max_drawdown_90pct=0.20,
                terminal_value_tail_mean_95=1_700_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.10,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    with pytest.raises(ValueError, match="goal solver produced no feasible allocations"):
        run_goal_solver(solver_input)


@pytest.mark.contract
def test_run_goal_solver_summarizes_no_feasible_pressure(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["constraints"]["max_drawdown_tolerance"] = 0.05
    solver_input["constraints"]["liquidity_reserve_min"] = 0.40
    solver_input["candidate_allocations"] = [
        {
            "name": "too_risky_a",
            "weights": {"equity_cn": 0.82, "bond_cn": 0.08, "gold": 0.05, "satellite": 0.05},
            "complexity_score": 0.40,
            "description": "violates drawdown and liquidity",
        },
        {
            "name": "too_risky_b",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.30,
            "description": "violates drawdown and liquidity less severely",
        },
    ]

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):
        drawdown = 0.18 if weights["equity_cn"] > 0.75 else 0.12
        probability = 0.61 if weights["equity_cn"] > 0.75 else 0.58
        return (
            probability,
            {"expected_terminal_value": 2_300_000.0},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=1_700_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.10,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    with pytest.raises(ValueError, match="goal solver produced no feasible allocations"):
        run_goal_solver(solver_input)


@pytest.mark.contract
def test_run_goal_solver_lightweight_uses_lightweight_paths_and_seed(
    goal_solver_input_base,
    monkeypatch,
):
    captured: dict[str, int] = {}

    def _fake_run_monte_carlo(
        weights,
        cashflow_schedule,
        initial_value,
        goal_amount,
        market_state,
        n_paths,
        seed,
        *,
        mode="static_gaussian",
        distribution_input=None,
    ):
        del weights, cashflow_schedule, initial_value, goal_amount, market_state, mode, distribution_input
        captured["n_paths"] = n_paths
        captured["seed"] = seed
        return (
            0.66,
            {"expected_terminal_value": 2_450_000.0},
            RiskSummary(
                max_drawdown_90pct=0.18,
                terminal_value_tail_mean_95=1_850_000.0,
                shortfall_probability=0.34,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    probability, risk = run_goal_solver_lightweight(
        weights=goal_solver_input_base["candidate_allocations"][0]["weights"],
        baseline_inp=goal_solver_input_base,
    )

    assert probability == 0.66
    assert risk.max_drawdown_90pct == 0.18
    assert captured["n_paths"] == goal_solver_input_base["solver_params"]["n_paths_lightweight"]
    assert captured["seed"] == goal_solver_input_base["solver_params"]["seed"]
