from __future__ import annotations

from copy import deepcopy

import pytest

import goal_solver.engine as goal_solver_engine
from goal_solver.engine import run_goal_solver, run_goal_solver_lightweight
from goal_solver.types import RANKING_MODE_MATRIX, RankingMode, RiskSummary, infer_ranking_mode


def _mode_test_input(goal_solver_input_base: dict) -> dict:
    data = deepcopy(goal_solver_input_base)
    data["goal"]["horizon_months"] = 12
    data["cashflow_plan"]["monthly_contribution"] = 0.0
    data["current_portfolio_value"] = 450_000.0
    data["goal"]["goal_amount"] = 500_000.0
    data["goal"]["success_prob_threshold"] = 0.60
    data["constraints"]["max_drawdown_tolerance"] = 0.35
    data["candidate_allocations"] = [
        {
            "name": "defensive",
            "weights": {"equity_cn": 0.35, "bond_cn": 0.50, "gold": 0.15, "satellite": 0.0},
            "complexity_score": 0.10,
            "description": "defensive candidate",
        },
        {
            "name": "growth",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.0, "satellite": 0.15},
            "complexity_score": 0.20,
            "description": "growth candidate",
        },
    ]
    return data


@pytest.mark.contract
@pytest.mark.parametrize(
    ("priority", "risk_preference", "expected"),
    [
        ("essential", "aggressive", RankingMode.SUFFICIENCY_FIRST),
        ("important", "aggressive", RankingMode.BALANCED),
        ("aspirational", "moderate", RankingMode.PROBABILITY_MAX),
        ("unknown", "unknown", RankingMode.SUFFICIENCY_FIRST),
    ],
)
def test_infer_ranking_mode_follows_profile_matrix(priority, risk_preference, expected):
    if (priority, risk_preference) in RANKING_MODE_MATRIX:
        assert RANKING_MODE_MATRIX[(priority, risk_preference)] == expected
    assert infer_ranking_mode(priority, risk_preference) == expected


@pytest.mark.contract
def test_run_goal_solver_uses_profile_driven_ranking(goal_solver_input_base):
    baseline = _mode_test_input(goal_solver_input_base)

    sufficiency_input = deepcopy(baseline)
    sufficiency_input["goal"]["priority"] = "important"
    sufficiency_input["goal"]["risk_preference"] = "moderate"
    sufficiency_result = run_goal_solver(sufficiency_input)

    probability_input = deepcopy(baseline)
    probability_input["goal"]["priority"] = "aspirational"
    probability_input["goal"]["risk_preference"] = "aggressive"
    probability_result = run_goal_solver(probability_input)

    assert sufficiency_result.ranking_mode_used == RankingMode.SUFFICIENCY_FIRST
    assert sufficiency_result.recommended_allocation.name == "defensive"
    assert probability_result.ranking_mode_used == RankingMode.PROBABILITY_MAX
    assert probability_result.recommended_allocation.name == "growth"
    assert sufficiency_result.solver_notes[0].endswith("source=matrix")


@pytest.mark.contract
def test_run_goal_solver_ranking_override_wins(goal_solver_input_base):
    override_input = _mode_test_input(goal_solver_input_base)
    override_input["goal"]["priority"] = "important"
    override_input["goal"]["risk_preference"] = "moderate"
    override_input["ranking_mode_override"] = "probability_max"

    result = run_goal_solver(override_input)

    assert result.ranking_mode_used == RankingMode.PROBABILITY_MAX
    assert result.recommended_allocation.name == "growth"
    assert "source=override" in result.solver_notes[0]


@pytest.mark.contract
def test_run_goal_solver_emits_no_feasible_fallback_notes(goal_solver_input_base):
    data = deepcopy(goal_solver_input_base)
    data["constraints"]["max_drawdown_tolerance"] = 0.08
    data["candidate_allocations"] = [
        {
            "name": "less_bad",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.15, "satellite": 0.0},
            "complexity_score": 0.10,
            "description": "less bad candidate",
        },
        {
            "name": "worse",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.10, "gold": 0.05, "satellite": 0.15},
            "complexity_score": 0.20,
            "description": "worse candidate",
        },
    ]

    result = run_goal_solver(data)

    assert result.recommended_allocation.name == "less_bad"
    assert result.recommended_result.is_feasible is False
    assert any(note == "warning=no_feasible_allocation" for note in result.solver_notes)
    assert any(note.startswith("fallback=closest_feasible_candidate") for note in result.solver_notes)
    assert all(not item.is_feasible for item in result.all_results)


@pytest.mark.contract
def test_run_goal_solver_lightweight_uses_lightweight_path_count(goal_solver_input_base, monkeypatch):
    captured: dict[str, int] = {}

    def _fake_run_monte_carlo(
        weights: dict[str, float],
        cashflow_schedule: list[float],
        initial_value: float,
        goal_amount: float,
        market_state,
        n_paths: int,
        seed: int,
    ):
        del weights, cashflow_schedule, initial_value, goal_amount, market_state
        captured["n_paths"] = n_paths
        captured["seed"] = seed
        return 0.55, {"expected_terminal_value": 1_000_000.0}, RiskSummary(
            max_drawdown_90pct=0.12,
            terminal_value_tail_mean_95=800_000.0,
            shortfall_probability=0.45,
            terminal_shortfall_p5_vs_initial=0.10,
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    probability, risk = run_goal_solver_lightweight(
        weights=goal_solver_input_base["candidate_allocations"][0]["weights"],
        baseline_inp=goal_solver_input_base,
    )

    assert probability == 0.55
    assert risk.max_drawdown_90pct == 0.12
    assert captured["n_paths"] == goal_solver_input_base["solver_params"]["n_paths_lightweight"]
    assert captured["seed"] == goal_solver_input_base["solver_params"]["seed"]


@pytest.mark.contract
def test_run_goal_solver_emits_context_and_threshold_gap_notes(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["success_prob_threshold"] = 0.72
    solver_input["solver_params"]["n_paths"] = 321
    solver_input["solver_params"]["seed"] = 11
    solver_input["candidate_allocations"] = [
        {
            "name": "steady",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "steady candidate",
        }
    ]

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.64,
            {"expected_terminal_value": 2_150_000.0},
            RiskSummary(
                max_drawdown_90pct=0.11,
                terminal_value_tail_mean_95=1_600_000.0,
                shortfall_probability=0.36,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(note == "monte_carlo paths=321 seed=11 horizon_months=144" for note in result.solver_notes)
    assert any(
        note == "success_threshold threshold=0.7200 recommended=0.6400 gap=0.0800 met=false"
        for note in result.solver_notes
    )
    assert any(
        note == "warning=success_probability_below_threshold threshold=0.7200 recommended=0.6400"
        for note in result.solver_notes
    )


@pytest.mark.contract
def test_run_goal_solver_threshold_warning_uses_effective_success_probability(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["success_prob_threshold"] = 0.60
    solver_input["candidate_allocations"] = [
        {
            "name": "steady",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "steady candidate",
        }
    ]

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.64,
            {"expected_terminal_value": 2_150_000.0},
            RiskSummary(
                max_drawdown_90pct=0.11,
                terminal_value_tail_mean_95=1_600_000.0,
                shortfall_probability=0.36,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)
    monkeypatch.setattr(goal_solver_engine, "_effective_success_probability", lambda _result: 0.58)

    result = run_goal_solver(solver_input)

    assert any(
        note == "success_threshold threshold=0.6000 recommended=0.5800 gap=0.0200 met=false"
        for note in result.solver_notes
    )
    assert any(
        note == "warning=success_probability_below_threshold threshold=0.6000 recommended=0.5800"
        for note in result.solver_notes
    )


@pytest.mark.contract
def test_run_goal_solver_marks_unavailable_frontier_constraints(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["goal_amount"] = 2_500_000.0
    solver_input["goal"]["success_prob_threshold"] = 0.80
    solver_input["constraints"]["max_drawdown_tolerance"] = 0.05
    solver_input["candidate_allocations"] = [
        {
            "name": "defensive",
            "weights": {"equity_cn": 0.30, "bond_cn": 0.55, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.08,
            "description": "defensive candidate",
        },
        {
            "name": "balanced",
            "weights": {"equity_cn": 0.45, "bond_cn": 0.35, "gold": 0.10, "satellite": 0.10},
            "complexity_score": 0.12,
            "description": "balanced candidate",
        },
    ]

    def _fake_run_monte_carlo(
        weights: dict[str, float],
        *_args,
        **_kwargs,
    ):
        if weights["equity_cn"] == 0.30:
            probability, terminal, drawdown = 0.42, 780_000.0, 0.09
        else:
            probability, terminal, drawdown = 0.48, 860_000.0, 0.12
        return (
            probability,
            {"expected_terminal_value": terminal},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=terminal * 0.82,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.18,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert result.frontier_analysis is not None
    assert result.frontier_analysis.scenario_status["target_return_priority"]["available"] is False
    assert result.frontier_analysis.scenario_status["drawdown_priority"]["available"] is False
    assert result.frontier_analysis.target_return_priority.allocation_name == ""
    assert result.frontier_analysis.drawdown_priority.allocation_name == ""


@pytest.mark.contract
def test_run_goal_solver_emits_model_honesty_notes(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["goal_amount_basis"] = "real"
    solver_input["goal"]["goal_amount_scope"] = "incremental_gain"
    solver_input["goal"]["tax_assumption"] = "after_tax"
    solver_input["goal"]["fee_assumption"] = "management_fee_plus_transaction_cost"
    solver_input["goal"]["contribution_commitment_confidence"] = 0.66
    solver_input["solver_params"]["shrinkage_factor"] = 0.91

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.68,
            {"expected_terminal_value": 2_050_000.0},
            RiskSummary(
                max_drawdown_90pct=0.14,
                terminal_value_tail_mean_95=1_550_000.0,
                shortfall_probability=0.32,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(
        note == "probability_model method=parametric_monte_carlo distribution=normal historical_backtest_used=false"
        for note in result.solver_notes
    )
    assert any(
        note
        == "monte_carlo_limitations shrinkage_factor=0.9100 limitation=static_parametric_inputs_non_historical"
        for note in result.solver_notes
    )
    assert any(
        note == "goal_semantics basis=real scope=incremental_gain tax=after_tax fee=management_fee_plus_transaction_cost"
        for note in result.solver_notes
    )
    assert any(
        note == "contribution_confidence value=0.6600 absorbed_into_solver=false"
        for note in result.solver_notes
    )


@pytest.mark.contract
def test_run_goal_solver_emits_historical_cycle_metadata_in_honesty_notes(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["solver_params"]["market_assumptions"].update(
        {
            "source_name": "baostock",
            "dataset_version": "baostock:sh.600000:20260404",
            "frequency": "daily",
            "lookback_days": 2520,
            "lookback_months": 120,
            "historical_backtest_used": True,
            "coverage_status": "cycle_insufficient",
            "cycle_reasons": ["missing_downcycle", "missing_high_volatility"],
            "observed_history_days": 2520,
            "inferred_history_days": 365,
            "inference_method": "index_proxy",
        }
    )

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.68,
            {"expected_terminal_value": 2_050_000.0},
            RiskSummary(
                max_drawdown_90pct=0.14,
                terminal_value_tail_mean_95=1_550_000.0,
                shortfall_probability=0.32,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(
        note
        == "historical_dataset source=baostock version=baostock:sh.600000:20260404 frequency=daily lookback_days=2520 lookback_months=120"
        for note in result.solver_notes
    )
    assert any(
        note
        == "historical_dataset_cycle coverage_status=cycle_insufficient observed_history_days=2520 inferred_history_days=365 inference_method=index_proxy cycle_reasons=missing_downcycle,missing_high_volatility"
        for note in result.solver_notes
    )


@pytest.mark.contract
def test_run_monte_carlo_respects_seed_and_path_count(goal_solver_input_base):
    normalized = goal_solver_engine._goal_solver_input_from_any(goal_solver_input_base)
    weights = normalized.candidate_allocations[0].weights
    market_state = normalized.solver_params.market_assumptions
    schedule = goal_solver_engine._build_cashflow_schedule(
        normalized.cashflow_plan,
        normalized.goal.horizon_months,
    )

    same_a = goal_solver_engine._run_monte_carlo(
        weights,
        schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        128,
        7,
    )
    same_b = goal_solver_engine._run_monte_carlo(
        weights,
        schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        128,
        7,
    )
    diff_seed = goal_solver_engine._run_monte_carlo(
        weights,
        schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        128,
        8,
    )
    diff_paths = goal_solver_engine._run_monte_carlo(
        weights,
        schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        512,
        7,
    )

    assert same_a[0] == same_b[0]
    assert same_a[1]["expected_terminal_value"] == same_b[1]["expected_terminal_value"]
    assert same_a[2].max_drawdown_90pct == same_b[2].max_drawdown_90pct
    assert (
        diff_seed[0] != same_a[0]
        or diff_seed[1]["expected_terminal_value"] != same_a[1]["expected_terminal_value"]
        or diff_seed[2].max_drawdown_90pct != same_a[2].max_drawdown_90pct
    )
    assert (
        diff_paths[0] != same_a[0]
        or diff_paths[1]["expected_terminal_value"] != same_a[1]["expected_terminal_value"]
        or diff_paths[2].max_drawdown_90pct != same_a[2].max_drawdown_90pct
    )


@pytest.mark.contract
def test_run_monte_carlo_preserves_basic_monotonicity(goal_solver_input_base):
    normalized = goal_solver_engine._goal_solver_input_from_any(goal_solver_input_base)
    weights = normalized.candidate_allocations[0].weights
    market_state = normalized.solver_params.market_assumptions
    low_schedule = [5_000.0] * normalized.goal.horizon_months
    high_schedule = [10_000.0] * normalized.goal.horizon_months

    low_prob, low_extra, _low_risk = goal_solver_engine._run_monte_carlo(
        weights,
        low_schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        2048,
        42,
    )
    high_prob, high_extra, _high_risk = goal_solver_engine._run_monte_carlo(
        weights,
        high_schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount,
        market_state,
        2048,
        42,
    )
    harder_goal_prob, _harder_goal_extra, _harder_goal_risk = goal_solver_engine._run_monte_carlo(
        weights,
        high_schedule,
        normalized.current_portfolio_value,
        normalized.goal.goal_amount * 1.2,
        market_state,
        2048,
        42,
    )

    assert high_extra["expected_terminal_value"] >= low_extra["expected_terminal_value"]
    assert high_prob >= low_prob
    assert harder_goal_prob <= high_prob


@pytest.mark.contract
def test_run_monte_carlo_handles_empty_weight_set_in_advanced_mode(goal_solver_input_base):
    normalized = goal_solver_engine._goal_solver_input_from_any(goal_solver_input_base)
    market_state = normalized.solver_params.market_assumptions
    schedule = [5_000.0] * 12

    probability, extra, risk = goal_solver_engine._run_monte_carlo(
        {},
        schedule,
        35_000.0,
        100_000.0,
        market_state,
        256,
        42,
        simulation_mode="garch_t",
        distribution_model_state=None,
    )

    assert probability == 0.0
    assert extra["expected_terminal_value"] == pytest.approx(35_000.0 + sum(schedule))
    assert risk.max_drawdown_90pct == pytest.approx(0.0)


@pytest.mark.contract
def test_run_goal_solver_builds_frontier_analysis_scenarios(goal_solver_input_base, monkeypatch):
    solver_input = _mode_test_input(goal_solver_input_base)
    solver_input["goal"]["goal_amount"] = 590_000.0
    solver_input["goal"]["success_prob_threshold"] = 0.60
    solver_input["constraints"]["max_drawdown_tolerance"] = 0.10
    solver_input["candidate_allocations"] = [
        {
            "name": "defensive",
            "weights": {"equity_cn": 0.30, "bond_cn": 0.55, "gold": 0.15, "satellite": 0.0},
            "complexity_score": 0.10,
            "description": "defensive candidate",
        },
        {
            "name": "balanced",
            "weights": {"equity_cn": 0.45, "bond_cn": 0.35, "gold": 0.15, "satellite": 0.05},
            "complexity_score": 0.15,
            "description": "balanced candidate",
        },
        {
            "name": "growth",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.10, "gold": 0.05, "satellite": 0.15},
            "complexity_score": 0.20,
            "description": "growth candidate",
        },
    ]

    result_map = {
        "defensive": (
            0.62,
            530_000.0,
            0.07,
        ),
        "balanced": (
            0.66,
            575_000.0,
            0.11,
        ),
        "growth": (
            0.69,
            610_000.0,
            0.23,
        ),
    }

    def _fake_run_monte_carlo(
        weights: dict[str, float],
        cashflow_schedule: list[float],
        initial_value: float,
        goal_amount: float,
        market_state,
        n_paths: int,
        seed: int,
        simulation_mode: str = "static_gaussian",
        distribution_model_state=None,
    ):
        del cashflow_schedule, initial_value, goal_amount, market_state, n_paths, seed, simulation_mode, distribution_model_state
        if weights["equity_cn"] == 0.30:
            scenario = "defensive"
        elif weights["equity_cn"] == 0.45:
            scenario = "balanced"
        else:
            scenario = "growth"
        probability, expected_terminal_value, max_drawdown = result_map[scenario]
        return (
            probability,
            {"expected_terminal_value": expected_terminal_value},
            RiskSummary(
                max_drawdown_90pct=max_drawdown,
                terminal_value_tail_mean_95=expected_terminal_value * 0.82,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert result.recommended_allocation.name == "defensive"
    assert result.frontier_analysis is not None
    assert result.frontier_analysis.recommended.allocation_name == "defensive"
    assert result.frontier_analysis.highest_probability.allocation_name == "growth"
    assert result.frontier_analysis.target_return_priority.allocation_name == "growth"
    assert result.frontier_analysis.drawdown_priority.allocation_name == "defensive"
    assert result.frontier_analysis.balanced_tradeoff.allocation_name == "balanced"
    assert result.frontier_analysis.recommended.meets_success_threshold is True
    assert result.frontier_analysis.drawdown_priority.drawdown_gap == pytest.approx(0.0)
    assert result.frontier_analysis.target_return_priority.target_return_gap == pytest.approx(0.0)

    result_dict = result.to_dict()
    assert result_dict["frontier_analysis"] is not None
    assert result_dict["frontier_analysis"]["highest_probability"]["allocation_name"] == "growth"
    assert result_dict["frontier_analysis"]["balanced_tradeoff"]["allocation_name"] == "balanced"
