from __future__ import annotations

from copy import deepcopy

import pytest

pytest.importorskip("runtime_optimizer.ev_engine.engine")

from goal_solver.engine import (
    build_account_state_baseline,
    run_goal_solver,
    run_goal_solver_lightweight,
)
from runtime_optimizer.candidates import ActionType, generate_candidates
from runtime_optimizer.ev_engine.engine import run_ev_engine
from runtime_optimizer.state_builder import build_ev_state
from runtime_optimizer.types import RuntimeOptimizerMode


@pytest.mark.smoke
def test_goal_solver_output_can_feed_ev_engine_smoke(
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    candidate_actions_base,
):
    solver_output = run_goal_solver(goal_solver_input_base)
    account_state = build_account_state_baseline(
        solver_output=solver_output,
        live_portfolio=live_portfolio_base,
        current_portfolio_value=live_portfolio_base["total_value"],
    )

    report = run_ev_engine(
        state={
            "account": account_state,
            "market": market_state_base,
            "constraints": constraint_state_base,
            "behavior": behavior_state_base,
            "ev_params": ev_params_base,
            "goal_solver_baseline_inp": goal_solver_input_base,
        },
        candidate_actions=candidate_actions_base,
        trigger_type="monthly",
    )
    expected_baseline, _risk = run_goal_solver_lightweight(
        weights=account_state["current_weights"],
        baseline_inp=goal_solver_input_base,
    )

    assert report.trigger_type == "monthly"
    assert report.state_snapshot_id == goal_solver_input_base["snapshot_id"]
    assert report.goal_solver_baseline == expected_baseline
    assert account_state["success_prob_baseline"] == solver_output.recommended_result.success_probability


@pytest.mark.smoke
def test_goal_solver_fallback_output_still_builds_ev_smoke(
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    candidate_actions_base,
):
    goal_solver_input = deepcopy(goal_solver_input_base)
    goal_solver_input["candidate_allocations"] = []

    solver_output = run_goal_solver(goal_solver_input)
    account_state = build_account_state_baseline(
        solver_output=solver_output,
        live_portfolio=live_portfolio_base,
        current_portfolio_value=live_portfolio_base["total_value"],
    )

    report = run_ev_engine(
        state={
            "account": account_state,
            "market": market_state_base,
            "constraints": constraint_state_base,
            "behavior": behavior_state_base,
            "ev_params": ev_params_base,
            "goal_solver_baseline_inp": goal_solver_input,
        },
        candidate_actions=candidate_actions_base,
        trigger_type="monthly",
    )
    expected_baseline, _risk = run_goal_solver_lightweight(
        weights=account_state["current_weights"],
        baseline_inp=goal_solver_input,
    )

    assert solver_output.recommended_allocation.name == "fallback"
    assert "technology" in account_state["theme_remaining_budget"]
    assert solver_output.solver_notes
    assert any("synthetic_fallback_used" in note for note in solver_output.solver_notes)
    assert report.trigger_type == "monthly"
    assert report.goal_solver_baseline == expected_baseline
    assert account_state["success_prob_baseline"] == solver_output.recommended_result.success_probability


@pytest.mark.smoke
def test_goal_solver_output_filters_add_defense_to_event_drawdown_path(
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
):
    goal_solver_output = deepcopy(goal_solver_output_base)
    allocation_weights = {"equity_cn": 0.45, "bond_cn": 0.32, "gold": 0.10, "satellite": 0.13}
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = dict(allocation_weights)
    goal_solver_output["recommended_result"]["weights"] = dict(allocation_weights)

    ev_state = build_ev_state(
        solver_output=goal_solver_output,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio_base,
        market_state=market_state_base,
        behavior_state=behavior_state_base,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
    )

    quarterly_candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.QUARTERLY,
        drawdown_event=True,
    )
    event_candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.EVENT,
        drawdown_event=True,
    )

    quarterly_types = {candidate.type for candidate in quarterly_candidates}
    event_types = {candidate.type for candidate in event_candidates}

    assert ActionType.ADD_DEFENSE not in quarterly_types
    assert ActionType.ADD_DEFENSE in event_types


@pytest.mark.smoke
def test_goal_solver_output_event_drawdown_add_defense_selects_dynamic_defense_bucket(
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
):
    goal_solver_output = deepcopy(goal_solver_output_base)
    live_portfolio = deepcopy(live_portfolio_base)

    allocation_weights = {"equity_cn": 0.45, "bond_cn": 0.32, "gold": 0.10, "satellite": 0.13}
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = dict(allocation_weights)
    goal_solver_output["recommended_result"]["weights"] = dict(allocation_weights)
    live_portfolio["available_cash"] = 30_000.0

    ev_state = build_ev_state(
        solver_output=goal_solver_output,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio,
        market_state=market_state_base,
        behavior_state=behavior_state_base,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
    )

    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.EVENT,
        drawdown_event=True,
    )
    add_defense = next(candidate for candidate in candidates if candidate.type == ActionType.ADD_DEFENSE)

    assert add_defense.target_bucket == "gold"
    assert add_defense.to_bucket == "gold"
