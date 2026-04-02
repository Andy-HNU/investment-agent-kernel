from __future__ import annotations

import pytest

from calibration.types import BehaviorState, ConstraintState, MarketState
from runtime_optimizer.ev_engine.types import EVState
from runtime_optimizer.state_builder import build_ev_state, validate_ev_state_inputs


@pytest.mark.contract
def test_build_ev_state_returns_typed_ev_state(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
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

    assert isinstance(ev_state, EVState)
    assert isinstance(ev_state.market, MarketState)
    assert isinstance(ev_state.constraints, ConstraintState)
    assert isinstance(ev_state.behavior, BehaviorState)


@pytest.mark.contract
def test_validate_ev_state_inputs_uses_snapshot_id_date_not_runtime_clock(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    constraint_state_base,
    runtime_optimizer_params_base,
):
    goal_solver_output_base["generated_at"] = "2026-04-02T00:00:00Z"
    live_portfolio_base["as_of_date"] = "2026-03-29"

    validate_ev_state_inputs(
        live_portfolio=live_portfolio_base,
        constraint_state=constraint_state_base,
        solver_output=goal_solver_output_base,
        solver_baseline_inp=goal_solver_input_base,
        optimizer_params=runtime_optimizer_params_base,
    )
