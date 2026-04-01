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
def test_structural_event_soft_deviation_allows_rebalance_full_in_event_mode(
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
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = {
        "equity_cn": 0.43,
        "bond_cn": 0.34,
        "gold": 0.05,
        "satellite": 0.18,
    }
    goal_solver_output["recommended_result"]["weights"] = dict(
        goal_solver_output["recommended_allocation"]["weights"]
    )

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
        structural_event=True,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.REBALANCE_LIGHT in action_types
    assert ActionType.REBALANCE_FULL in action_types


@pytest.mark.contract
def test_monthly_generation_does_not_inject_observe_without_behavior_trigger(
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
    assert ActionType.OBSERVE not in action_types
    assert ActionType.ADD_DEFENSE not in action_types
    assert len(action_types) >= 2


@pytest.mark.contract
def test_monthly_generation_backfills_observe_when_freeze_is_only_candidate(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
):
    live_portfolio = deepcopy(live_portfolio_base)
    live_portfolio["weights"] = dict(goal_solver_output_base["recommended_allocation"]["weights"])
    live_portfolio["available_cash"] = 0.0

    ev_state = build_ev_state(
        solver_output=goal_solver_output_base,
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
        mode=RuntimeOptimizerMode.MONTHLY,
    )
    action_types = [candidate.type for candidate in candidates]

    assert action_types[:2] == [ActionType.FREEZE, ActionType.OBSERVE]


@pytest.mark.contract
def test_monthly_new_cash_candidate_clips_amount_pct_to_cash_budget_and_bucket_deficit(
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
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = {
        "equity_cn": 0.43,
        "bond_cn": 0.34,
        "gold": 0.05,
        "satellite": 0.18,
    }
    goal_solver_output["recommended_result"]["weights"] = dict(
        goal_solver_output["recommended_allocation"]["weights"]
    )

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
        mode=RuntimeOptimizerMode.MONTHLY,
    )
    add_cash_def = next(candidate for candidate in candidates if candidate.type == ActionType.ADD_CASH_TO_DEF)

    cash_budget = live_portfolio_base["available_cash"] * runtime_optimizer_params_base["new_cash_use_pct"]
    deficit_value = (
        goal_solver_output["recommended_allocation"]["weights"]["bond_cn"] - live_portfolio_base["weights"]["bond_cn"]
    ) * live_portfolio_base["total_value"]
    expected_amount_pct = min(cash_budget, deficit_value) / live_portfolio_base["total_value"]

    assert add_cash_def.amount_pct == pytest.approx(expected_amount_pct)
    assert add_cash_def.amount_pct <= runtime_optimizer_params_base["amount_pct_max"]


@pytest.mark.contract
def test_monthly_new_cash_split_buckets_surfaces_multiple_underweight_targets(
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
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = {
        "equity_cn": 0.43,
        "bond_cn": 0.34,
        "gold": 0.05,
        "satellite": 0.18,
    }
    goal_solver_output["recommended_result"]["weights"] = dict(
        goal_solver_output["recommended_allocation"]["weights"]
    )

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
        mode=RuntimeOptimizerMode.MONTHLY,
    )
    add_cash_types = {
        candidate.type
        for candidate in candidates
        if candidate.type in {
            ActionType.ADD_CASH_TO_CORE,
            ActionType.ADD_CASH_TO_DEF,
            ActionType.ADD_CASH_TO_SAT,
        }
    }

    assert add_cash_types == {ActionType.ADD_CASH_TO_DEF, ActionType.ADD_CASH_TO_SAT}


@pytest.mark.contract
def test_monthly_new_cash_skips_satellite_when_satellite_is_already_overweight(
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
    live_portfolio = deepcopy(live_portfolio_base)
    goal_solver_output["recommended_allocation"] = dict(goal_solver_output["recommended_allocation"])
    goal_solver_output["recommended_result"] = dict(goal_solver_output["recommended_result"])
    goal_solver_output["recommended_allocation"]["weights"] = {
        "equity_cn": 0.35,
        "bond_cn": 0.15,
        "gold": 0.05,
        "satellite": 0.45,
    }
    goal_solver_output["recommended_result"]["weights"] = dict(
        goal_solver_output["recommended_allocation"]["weights"]
    )
    live_portfolio["weights"] = {
        "equity_cn": 0.50,
        "bond_cn": 0.10,
        "gold": 0.03,
        "satellite": 0.37,
    }

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
        mode=RuntimeOptimizerMode.MONTHLY,
    )

    add_cash_candidates = [candidate for candidate in candidates if candidate.type.name.startswith("ADD_CASH")]
    assert add_cash_candidates
    assert all(candidate.target_bucket != "satellite" for candidate in add_cash_candidates)
    assert add_cash_candidates[0].type == ActionType.ADD_CASH_TO_DEF
    assert add_cash_candidates[0].target_bucket == "bond_cn"


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

    assert ActionType.FREEZE in action_types
    assert ActionType.ADD_DEFENSE in action_types
    assert ActionType.OBSERVE not in action_types
