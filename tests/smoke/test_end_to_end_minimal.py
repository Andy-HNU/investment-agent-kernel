from __future__ import annotations

import pytest

pytest.importorskip("runtime_optimizer.ev_engine.engine")
pytest.importorskip("decision_card.builder")

from runtime_optimizer.ev_engine.engine import run_ev_engine
from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType


@pytest.mark.smoke
def test_minimal_ev_to_decision_card_smoke(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    candidate_actions_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    # 这是最小冒烟测试：
    # 1. 假设上游已构建好 EVState
    # 2. 直接调用 run_ev_engine
    # 3. 将 EVReport 交给 09 生成 Decision Card
    ev_state = {
        "account": {
            "current_weights": live_portfolio_base["weights"],
            "target_weights": goal_solver_output_base["recommended_allocation"]["weights"],
            "goal_gap": live_portfolio_base["goal_gap"],
            "success_prob_baseline": goal_solver_output_base["recommended_result"]["success_probability"],
            "horizon_months": live_portfolio_base["remaining_horizon_months"],
            "available_cash": live_portfolio_base["available_cash"],
            "total_portfolio_value": live_portfolio_base["total_value"],
            "theme_remaining_budget": goal_solver_output_base["structure_budget"]["theme_remaining_budget"],
        },
        "market": market_state_base,
        "constraints": constraint_state_base,
        "behavior": behavior_state_base,
        "ev_params": ev_params_base,
        "goal_solver_baseline_inp": goal_solver_input_base,
    }

    report = run_ev_engine(
        state=ev_state,
        candidate_actions=candidate_actions_base,
        trigger_type="monthly",
    )

    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.RUNTIME_ACTION,
            workflow_type="monthly",
            run_id="smoke_minimal_ev_card",
            runtime_result={"ev_report": report},
        )
    )

    assert card is not None
