from __future__ import annotations

import pytest

import runtime_optimizer.engine as runtime_optimizer_engine
from runtime_optimizer.candidates import Action, ActionType
from runtime_optimizer.engine import run_runtime_optimizer
from runtime_optimizer.ev_engine.types import EVComponentScore, EVReport, EVResult
from runtime_optimizer.types import RuntimeOptimizerMode


def _action(
    action_type: ActionType,
    *,
    target_bucket: str | None = None,
    amount_pct: float = 0.0,
    cash_source: str = "new_cash",
    requires_sell: bool = False,
) -> Action:
    return Action(
        type=action_type,
        target_bucket=target_bucket,
        amount=0.0,
        amount_pct=amount_pct,
        from_bucket=None,
        to_bucket=target_bucket,
        cash_source=cash_source,
        requires_sell=requires_sell,
        expected_turnover=amount_pct,
        policy_tag="test",
        cooldown_applicable=False,
        rationale="test",
        explanation_facts=[],
    )


def _report(
    action: Action,
    *,
    score_total: float,
    confidence_flag: str = "medium",
    confidence_reason: str = "top1-top2 unavailable",
) -> EVReport:
    score = EVComponentScore(
        goal_impact=0.04,
        risk_penalty=0.01,
        soft_constraint_penalty=0.0,
        behavior_penalty=0.0,
        execution_penalty=0.0,
        total=score_total,
    )
    return EVReport(
        trigger_type="monthly",
        generated_at="2026-04-01T12:00:00Z",
        state_snapshot_id="snapshot_1",
        ranked_actions=[
            EVResult(
                action=action,
                score=score,
                rank=1,
                is_recommended=True,
                recommendation_reason="test recommendation",
            )
        ],
        eliminated_actions=[],
        recommended_action=action,
        recommended_score=score,
        confidence_flag=confidence_flag,
        confidence_reason=confidence_reason,
        goal_solver_baseline=0.42,
        goal_solver_after_recommended=0.51,
        params_version="ev_params_v1",
    )


@pytest.mark.contract
def test_run_runtime_optimizer_poverty_protocol_clears_unsafe_recommendation(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
    monkeypatch,
):
    unsafe_action = _action(ActionType.ADD_CASH_TO_CORE, target_bucket="equity_cn", amount_pct=0.08)

    monkeypatch.setattr(
        runtime_optimizer_engine,
        "generate_candidates",
        lambda **_kwargs: [unsafe_action],
    )
    monkeypatch.setattr(
        runtime_optimizer_engine,
        "run_ev_engine",
        lambda **_kwargs: _report(unsafe_action, score_total=0.06),
    )

    result = run_runtime_optimizer(
        solver_output=goal_solver_output_base,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio_base,
        market_state=market_state_base,
        behavior_state=behavior_state_base,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
        optimizer_params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.MONTHLY,
    )

    assert result.candidate_poverty is True
    assert result.ev_report.recommended_action is None
    assert result.ev_report.recommended_score is None
    assert result.ev_report.goal_solver_after_recommended == pytest.approx(0.42)
    assert result.ev_report.confidence_flag == "low"
    assert "候选通过过滤数量过少" in result.ev_report.confidence_reason


@pytest.mark.contract
def test_run_runtime_optimizer_poverty_protocol_keeps_safe_action_when_available(
    goal_solver_output_base,
    goal_solver_input_base,
    live_portfolio_base,
    market_state_base,
    behavior_state_base,
    constraint_state_base,
    ev_params_base,
    runtime_optimizer_params_base,
    monkeypatch,
):
    safe_action = _action(ActionType.FREEZE, amount_pct=0.0)

    monkeypatch.setattr(
        runtime_optimizer_engine,
        "generate_candidates",
        lambda **_kwargs: [safe_action],
    )
    monkeypatch.setattr(
        runtime_optimizer_engine,
        "run_ev_engine",
        lambda **_kwargs: _report(safe_action, score_total=0.0, confidence_flag="medium"),
    )

    result = run_runtime_optimizer(
        solver_output=goal_solver_output_base,
        solver_baseline_inp=goal_solver_input_base,
        live_portfolio=live_portfolio_base,
        market_state=market_state_base,
        behavior_state=behavior_state_base,
        constraint_state=constraint_state_base,
        ev_params=ev_params_base,
        optimizer_params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.MONTHLY,
    )

    assert result.candidate_poverty is True
    assert result.ev_report.recommended_action is not None
    assert result.ev_report.recommended_action.type == ActionType.FREEZE
    assert result.ev_report.recommended_score is not None
    assert result.ev_report.goal_solver_after_recommended == pytest.approx(0.42)
    assert result.ev_report.confidence_flag == "low"
    assert result.ev_report.confidence_reason == "候选通过过滤数量过少，已降级为安全动作优先"
