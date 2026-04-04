from __future__ import annotations

from copy import deepcopy

import pytest

import runtime_optimizer.ev_engine.engine as ev_engine_module
import runtime_optimizer.ev_engine.scorer as ev_scorer_module
from runtime_optimizer.candidates import Action, ActionType
from runtime_optimizer.ev_engine.engine import run_ev_engine
from runtime_optimizer.ev_engine.scorer import score_action
from runtime_optimizer.ev_engine.types import EVComponentScore, EVReport, FeasibilityResult


def _ev_state(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    return {
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


def _action(
    action_type: ActionType,
    *,
    target_bucket: str | None = None,
    amount: float | None = 0.0,
    amount_pct: float | None = 0.0,
    from_bucket: str | None = None,
    to_bucket: str | None = None,
    cash_source: str = "new_cash",
    requires_sell: bool = False,
    expected_turnover: float = 0.0,
    cooldown_applicable: bool = False,
) -> Action:
    return Action(
        type=action_type,
        target_bucket=target_bucket,
        amount=amount,
        amount_pct=amount_pct,
        from_bucket=from_bucket,
        to_bucket=to_bucket,
        cash_source=cash_source,
        requires_sell=requires_sell,
        expected_turnover=expected_turnover,
        policy_tag="test",
        cooldown_applicable=cooldown_applicable,
        rationale="test",
        explanation_facts=[],
    )


@pytest.mark.contract
def test_run_ev_engine_returns_typed_report(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    candidate_actions_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
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

    assert isinstance(report, EVReport)
    assert report.trigger_type == "monthly"


@pytest.mark.contract
def test_score_action_add_cash_to_new_bucket_preserves_cash_coverage_without_retargeting(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    monkeypatch,
):
    captured: list[dict[str, float]] = []

    def _fake_run_goal_solver_lightweight(*, weights, baseline_inp):
        captured.append(dict(weights))
        return 0.5, None

    monkeypatch.setattr(ev_scorer_module, "run_goal_solver_lightweight", _fake_run_goal_solver_lightweight)

    live_portfolio_base["weights"] = {"gold": 0.30}
    live_portfolio_base["available_cash"] = 7_000.0
    live_portfolio_base["total_value"] = 10_000.0
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state_base,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )

    score_action(
        _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount=1_000.0, amount_pct=0.10),
        state,
    )

    assert len(captured) >= 2
    assert captured[0]["cash_liquidity"] == pytest.approx(0.70, abs=1e-6)
    assert captured[1]["gold"] == pytest.approx(0.30, abs=1e-6)
    assert captured[1]["cash_liquidity"] == pytest.approx(0.60, abs=1e-6)
    assert captured[1]["equity_cn"] == pytest.approx(0.10, abs=1e-6)


@pytest.mark.contract
def test_run_ev_engine_confidence_uses_thresholds_and_reason_priority(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    monkeypatch,
):
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state_base,
        {
            **ev_params_base,
            "high_confidence_min_diff": 0.02,
            "medium_confidence_min_diff": 0.005,
            "goal_solver_min_delta": 0.001,
        },
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount=5000.0, amount_pct=0.10),
        _action(ActionType.OBSERVE, amount=0.0, amount_pct=0.0),
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
    ]
    score_by_type = {
        ActionType.ADD_CASH_TO_CORE: EVComponentScore(0.08, 0.01, 0.004, 0.002, 0.001, 0.063),
        ActionType.OBSERVE: EVComponentScore(0.01, 0.001, 0.0, 0.0, 0.0, 0.009),
        ActionType.FREEZE: EVComponentScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.001),
    }

    monkeypatch.setattr(
        ev_engine_module,
        "_check_feasibility",
        lambda action, _state: FeasibilityResult(True, []),
    )
    monkeypatch.setattr(
        ev_engine_module,
        "score_action",
        lambda action, _state: score_by_type[action.type],
    )

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert report.confidence_flag == "high"
    assert "high 阈值" in report.confidence_reason
    assert report.recommended_action is not None
    assert report.recommended_action.type == ActionType.ADD_CASH_TO_CORE
    assert report.ranked_actions[0].recommendation_reason == "该动作在提升目标成功概率方面最优，风险与成本可控"


@pytest.mark.contract
def test_run_ev_engine_recommendation_reason_explains_penalty_advantage_over_raw_goal_impact(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    monkeypatch,
):
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state_base,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount=5000.0, amount_pct=0.08),
        _action(
            ActionType.REBALANCE_LIGHT,
            target_bucket="equity_cn",
            amount=5000.0,
            amount_pct=0.08,
            from_bucket="bond_cn",
            to_bucket="equity_cn",
            cash_source="sell_rebalance",
            requires_sell=True,
            expected_turnover=0.08,
        ),
        _action(ActionType.OBSERVE, amount=0.0, amount_pct=0.0),
    ]
    score_by_type = {
        ActionType.ADD_CASH_TO_CORE: EVComponentScore(0.045, 0.004, 0.001, 0.0, 0.001, 0.039),
        ActionType.REBALANCE_LIGHT: EVComponentScore(0.065, 0.014, 0.003, 0.0, 0.010, 0.038),
        ActionType.OBSERVE: EVComponentScore(0.001, 0.0, 0.0, 0.0, 0.0, 0.001),
    }

    monkeypatch.setattr(
        ev_engine_module,
        "_check_feasibility",
        lambda action, _state: FeasibilityResult(True, []),
    )
    monkeypatch.setattr(
        ev_engine_module,
        "score_action",
        lambda action, _state: score_by_type[action.type],
    )

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert report.recommended_action is not None
    assert report.recommended_action.type == ActionType.ADD_CASH_TO_CORE
    assert report.ranked_actions[0].recommendation_reason == "该动作胜在风险惩罚和执行成本更低，尽管目标提升不是最高"


@pytest.mark.contract
def test_run_ev_engine_low_confidence_reason_explains_mixed_safe_and_active_candidates(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    monkeypatch,
):
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state_base,
        {
            **ev_params_base,
            "high_confidence_min_diff": 0.02,
            "medium_confidence_min_diff": 0.005,
        },
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.OBSERVE, amount=0.0, amount_pct=0.0),
        _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount=4000.0, amount_pct=0.06),
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
    ]
    score_by_type = {
        ActionType.OBSERVE: EVComponentScore(0.012, 0.001, 0.0, 0.0, 0.0, 0.011),
        ActionType.ADD_CASH_TO_CORE: EVComponentScore(0.015, 0.003, 0.0, 0.0, 0.002, 0.008),
        ActionType.FREEZE: EVComponentScore(0.010, 0.0, 0.0, 0.0, 0.0, 0.0075),
    }

    monkeypatch.setattr(
        ev_engine_module,
        "_check_feasibility",
        lambda action, _state: FeasibilityResult(True, []),
    )
    monkeypatch.setattr(
        ev_engine_module,
        "score_action",
        lambda action, _state: score_by_type[action.type],
    )

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert report.confidence_flag == "low"
    assert report.confidence_reason == "top1-top2 分差 0.0030 低于 medium 阈值，且候选同时包含安全动作与主动动作"


@pytest.mark.contract
def test_run_ev_engine_low_confidence_under_emotion_and_cooldown_filters(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    behavior_state = deepcopy(behavior_state_base)
    behavior_state["high_emotion_flag"] = True
    behavior_state["emotion_score"] = 0.9
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
        _action(
            ActionType.ADD_CASH_TO_CORE,
            target_bucket="equity_cn",
            amount=3000.0,
            amount_pct=0.08,
            cooldown_applicable=True,
        ),
        _action(
            ActionType.ADD_DEFENSE,
            target_bucket="bond_cn",
            amount=3000.0,
            amount_pct=0.05,
            cooldown_applicable=True,
        ),
    ]

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="event")

    assert report.confidence_flag == "low"
    assert "情绪标志触发" in report.confidence_reason
    assert len(report.ranked_actions) == 1
    assert len(report.eliminated_actions) == 2
    assert all(
        "当前处于高情绪冷静期，非观察/冻结动作不可执行" in eliminated.fail_reasons
        for _, eliminated in report.eliminated_actions
    )


@pytest.mark.contract
def test_run_ev_engine_respects_calibrated_cooldown_state_without_emotion_flags(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    behavior_state = deepcopy(behavior_state_base)
    behavior_state["high_emotion_flag"] = False
    behavior_state["panic_flag"] = False
    behavior_state["cooldown_active"] = True

    constraint_state = deepcopy(constraint_state_base)
    constraint_state["cooldown_currently_active"] = True

    state = _ev_state(
        market_state_base,
        constraint_state,
        behavior_state,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
        _action(
            ActionType.ADD_CASH_TO_CORE,
            target_bucket="equity_cn",
            amount=3000.0,
            amount_pct=0.08,
            cooldown_applicable=True,
        ),
    ]

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert len(report.ranked_actions) == 1
    assert report.ranked_actions[0].action.type == ActionType.FREEZE
    assert any(
        "当前处于高情绪冷静期，非观察/冻结动作不可执行" in eliminated.fail_reasons
        for _, eliminated in report.eliminated_actions
    )


@pytest.mark.contract
def test_run_ev_engine_feasibility_reports_qdii_and_cash_fail_reasons(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    constraint_state = deepcopy(constraint_state_base)
    constraint_state["qdii_available"] = 100.0
    constraint_state["bucket_category"] = {
        **constraint_state["bucket_category"],
        "equity_qdii": "qdii",
    }
    live_portfolio = deepcopy(live_portfolio_base)
    live_portfolio["available_cash"] = 500.0
    state = _ev_state(
        market_state_base,
        constraint_state,
        behavior_state_base,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio,
    )
    actions = [
        _action(
            ActionType.ADD_CASH_TO_CORE,
            target_bucket="equity_qdii",
            amount=2000.0,
            amount_pct=0.10,
        ),
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
    ]

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert len(report.eliminated_actions) == 1
    fail_reasons = report.eliminated_actions[0][1].fail_reasons
    assert any("QDII 配额不足" in reason for reason in fail_reasons)
    assert any("资金不足" in reason for reason in fail_reasons)
    assert report.recommended_action is not None
    assert report.recommended_action.type == ActionType.FREEZE


@pytest.mark.contract
def test_run_ev_engine_feasibility_blocks_constraint_forbidden_actions(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    constraint_state = deepcopy(constraint_state_base)
    constraint_state["forbidden_actions"] = ["rebalance_full"]

    state = _ev_state(
        market_state_base,
        constraint_state,
        behavior_state_base,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(
            ActionType.REBALANCE_FULL,
            amount=5000.0,
            amount_pct=0.08,
            from_bucket="bond_cn",
            to_bucket="equity_cn",
            cash_source="sell_rebalance",
            requires_sell=True,
            expected_turnover=0.08,
        ),
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
    ]

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert len(report.eliminated_actions) == 1
    assert report.eliminated_actions[0][0].type == ActionType.REBALANCE_FULL
    assert any("约束层显式禁用" in reason for reason in report.eliminated_actions[0][1].fail_reasons)
    assert report.recommended_action is not None
    assert report.recommended_action.type == ActionType.FREEZE


@pytest.mark.contract
def test_run_ev_engine_uses_documented_action_priority_for_equal_scores(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
    monkeypatch,
):
    state = _ev_state(
        market_state_base,
        constraint_state_base,
        behavior_state_base,
        ev_params_base,
        goal_solver_input_base,
        goal_solver_output_base,
        live_portfolio_base,
    )
    actions = [
        _action(ActionType.ADD_DEFENSE, target_bucket="bond_cn", amount=3000.0, amount_pct=0.05),
        _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount=3000.0, amount_pct=0.05),
        _action(ActionType.OBSERVE, amount=0.0, amount_pct=0.0),
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
    ]
    tied_score = EVComponentScore(0.01, 0.001, 0.0, 0.0, 0.0, 0.009)

    monkeypatch.setattr(
        ev_engine_module,
        "_check_feasibility",
        lambda action, _state: FeasibilityResult(True, []),
    )
    monkeypatch.setattr(
        ev_engine_module,
        "score_action",
        lambda action, _state: tied_score,
    )

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert [item.action.type for item in report.ranked_actions] == [
        ActionType.FREEZE,
        ActionType.OBSERVE,
        ActionType.ADD_CASH_TO_CORE,
        ActionType.ADD_DEFENSE,
    ]
    assert report.recommended_action is not None
    assert report.recommended_action.type == ActionType.FREEZE


@pytest.mark.contract
def test_score_action_uses_evparams_for_all_penalty_components(
    market_state_base,
    constraint_state_base,
    behavior_state_base,
    ev_params_base,
    goal_solver_input_base,
    goal_solver_output_base,
    live_portfolio_base,
):
    market_state = deepcopy(market_state_base)
    market_state["correlation_spike_alert"] = True
    market_state["liquidity_flag"] = {
        **market_state["liquidity_flag"],
        "satellite": True,
    }
    market_state["valuation_positions"] = {
        **market_state["valuation_positions"],
        "satellite": "rich",
    }
    constraint_state = deepcopy(constraint_state_base)
    constraint_state["theme_caps"] = {"technology": 0.08}
    constraint_state["premium_discount"] = {"satellite": 0.03}
    constraint_state["transaction_fee_rate"] = {"satellite": 0.004}
    behavior_state = deepcopy(behavior_state_base)
    behavior_state["recent_chasing_flag"] = True
    behavior_state["action_frequency_30d"] = 6
    behavior_state["panic_flag"] = True
    behavior_state["behavior_penalty_coeff"] = 0.8
    state = ev_engine_module.EVState.from_any(
        _ev_state(
            market_state,
            constraint_state,
            behavior_state,
            {
                **ev_params_base,
                "goal_impact_weight": 1.0,
                "risk_penalty_weight": 0.25,
                "soft_constraint_weight": 0.15,
                "behavior_penalty_weight": 0.10,
                "execution_penalty_weight": 0.10,
                "volatility_penalty_coeff": 0.3,
                "drawdown_penalty_coeff": 0.4,
                "ips_headroom_warning_threshold": 0.6,
                "theme_budget_warning_pct": 0.8,
                "concentration_headroom_threshold": 0.5,
                "emotion_score_threshold": 0.2,
                "action_frequency_threshold": 4,
                "transaction_cost_rate": 0.002,
            },
            goal_solver_input_base,
            goal_solver_output_base,
            live_portfolio_base,
        )
    )
    action = _action(
        ActionType.REBALANCE_LIGHT,
        target_bucket="satellite",
        amount=5000.0,
        amount_pct=0.12,
        from_bucket="bond_cn",
        to_bucket="satellite",
        cash_source="sell_rebalance",
        requires_sell=True,
        expected_turnover=0.12,
    )

    score = score_action(action, state)

    assert score.risk_penalty > 0.0
    assert score.soft_constraint_penalty > 0.0
    assert score.behavior_penalty > 0.0
    assert score.execution_penalty > 0.0
