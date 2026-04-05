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
def test_run_goal_solver_emits_dual_probability_and_frontier_diagnostics(goal_solver_input_base, monkeypatch):
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

    assert result.recommended_result.bucket_success_probability == pytest.approx(
        result.recommended_result.success_probability
    )
    assert result.recommended_result.product_proxy_adjusted_success_probability is None
    assert result.recommended_result.product_probability_method == "bucket_only_no_product_proxy_adjustment"
    assert result.recommended_result.implied_required_annual_return is not None
    assert result.recommended_result.expected_annual_return is not None
    assert result.frontier_analysis is not None
    assert result.frontier_analysis.scenario_status["target_return_priority"]["available"] is False
    assert result.frontier_analysis.scenario_status["drawdown_priority"]["available"] is False
    assert result.frontier_analysis.target_return_priority.allocation_name == ""
    assert result.frontier_analysis.drawdown_priority.allocation_name == ""
    assert result.frontier_diagnostics["raw_candidate_count"] == 2
    assert result.frontier_diagnostics["feasible_candidate_count"] == 0
    assert result.frontier_diagnostics["frontier_max_expected_annual_return"] is not None
    assert "expected_return_shrinkage_applied" in result.frontier_diagnostics["structural_limitations"]
    assert result.frontier_diagnostics["candidate_families"] == ["balanced", "defensive"]
    assert result.frontier_diagnostics["binding_constraints"]


@pytest.mark.contract
def test_run_goal_solver_uses_generic_growth_tilt_limitation_label(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["priority"] = "important"
    solver_input["goal"]["risk_preference"] = "moderate"
    solver_input["goal"]["horizon_months"] = 36
    solver_input["candidate_allocations"] = [
        {
            "name": "balanced__moderate__01",
            "weights": {"equity_cn": 0.50, "bond_cn": 0.35, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "balanced candidate",
        }
    ]

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.52,
            {"expected_terminal_value": 1_250_000.0},
            RiskSummary(
                max_drawdown_90pct=0.13,
                terminal_value_tail_mean_95=1_000_000.0,
                shortfall_probability=0.48,
                terminal_shortfall_p5_vs_initial=0.11,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert "return_seeking_families_not_generated_under_current_solver_inputs" in result.frontier_diagnostics[
        "structural_limitations"
    ]
    assert "growth_tilt_template_gated_by_horizon_lt_60_for_moderate" not in result.frontier_diagnostics[
        "structural_limitations"
    ]


@pytest.mark.contract
def test_run_goal_solver_applies_product_proxy_adjustments_when_context_present(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["candidate_allocations"] = [
        {
            "name": "balanced",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "balanced candidate",
        }
    ]
    solver_input["candidate_product_contexts"] = {
        "balanced": {
            "allocation_name": "balanced",
            "product_probability_method": "product_proxy_adjustment_estimate",
            "bucket_expected_return_adjustments": {"equity_cn": 0.02, "satellite": 0.01},
            "bucket_volatility_multipliers": {"equity_cn": 1.10, "satellite": 1.15},
            "selected_product_ids": ["510300", "511010", "518880", "159915"],
            "selected_proxy_refs": ["yfinance:510300.SS", "yfinance:159915.SZ"],
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
        if market_state.expected_returns["equity_cn"] > 0.09:
            probability, terminal, drawdown = 0.63, 2_350_000.0, 0.17
        else:
            probability, terminal, drawdown = 0.51, 2_110_000.0, 0.13
        return (
            probability,
            {"expected_terminal_value": terminal},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=terminal * 0.80,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.09,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert len(observed_expected_returns) == 2
    assert observed_expected_returns[0]["equity_cn"] == pytest.approx(0.08)
    assert observed_expected_returns[1]["equity_cn"] == pytest.approx(0.10)
    assert result.recommended_result.bucket_success_probability == pytest.approx(0.51)
    assert result.recommended_result.product_proxy_adjusted_success_probability == pytest.approx(0.63)
    assert result.recommended_result.product_probability_method == "product_proxy_adjustment_estimate"
    assert result.recommended_result.success_probability == pytest.approx(0.63)
    assert result.recommended_result.expected_terminal_value == pytest.approx(2_350_000.0)
    assert result.recommended_result.expected_annual_return is not None
    assert result.recommended_result.risk_summary.max_drawdown_90pct == pytest.approx(0.17)


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
