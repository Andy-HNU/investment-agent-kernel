from __future__ import annotations

from copy import deepcopy

import pytest

from runtime_optimizer.candidates import ActionType, generate_candidates
from runtime_optimizer.state_builder import build_ev_state
from runtime_optimizer.types import RuntimeOptimizerMode


@pytest.mark.contract
def test_behavior_event_forces_observe_and_blocks_rebalance_full(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
):
    behavior_state = dict(behavior_state_base)
    behavior_state["high_emotion_flag"] = True

    ev_state = build_ev_state(
        solver_output=goal_solver_output_base,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio_base,
        market_state=market_state_base,
        behavior_state=behavior_state,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
    )

    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.EVENT,
        behavior_event=True,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.FREEZE in action_types
    assert ActionType.OBSERVE in action_types
    assert ActionType.REBALANCE_FULL not in action_types
    assert all(
        candidate.cooldown_applicable
        for candidate in candidates
        if candidate.type not in {ActionType.FREEZE, ActionType.OBSERVE}
    )


@pytest.mark.contract
def test_monthly_generation_keeps_safe_actions_but_does_not_add_defense(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
):
    ev_state = build_ev_state(
        solver_output=goal_solver_output_base,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio_base,
        market_state=market_state_base,
        behavior_state=behavior_state_base,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
    )

    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.MONTHLY,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.FREEZE in action_types
    assert ActionType.OBSERVE in action_types
    assert ActionType.ADD_DEFENSE not in action_types


@pytest.mark.contract
def test_drawdown_event_forces_add_defense(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
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

    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.EVENT,
        drawdown_event=True,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.ADD_DEFENSE in action_types
    assert ActionType.OBSERVE in action_types
