from __future__ import annotations

import pytest

from calibration.types import BehaviorState, ConstraintState, MarketState
from runtime_optimizer.ev_engine.types import EVState
from runtime_optimizer.state_builder import build_ev_state


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
