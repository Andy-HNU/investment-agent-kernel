from __future__ import annotations

from copy import deepcopy

import pytest

import orchestrator.engine as orchestrator_engine
from decision_card.builder import build_decision_card
from orchestrator.engine import run_orchestrator
from runtime_optimizer.types import RuntimeOptimizerMode, RuntimeOptimizerResult
from tests.helpers.contracts import assert_decision_card_is_pure_render


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal_solver_input_base["goal"],
        "cashflow_plan": goal_solver_input_base["cashflow_plan"],
        "constraints": goal_solver_input_base["constraints"],
        "universe": {
            "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": {
                "equity_cn": None,
                "bond_cn": None,
                "gold": None,
                "satellite": "technology",
            },
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def _poverty_runtime_result(mode: RuntimeOptimizerMode) -> RuntimeOptimizerResult:
    return RuntimeOptimizerResult(
        mode=mode,
        ev_report={"ranked_actions": []},
        state_snapshot={"mode": mode.value},
        candidates_generated=1,
        candidates_after_filter=1,
        candidate_poverty=True,
        run_timestamp="2026-03-29T12:00:00Z",
        optimizer_params_version="v1.0.0",
        goal_solver_params_version="v4.0.0",
    )


@pytest.mark.contract
def test_decision_card_contract_shape():
    # 这是结构契约测试：09 必须消费结构化输入生成卡片，不得自行推理策略。
    fake_card = {
        "recommended_action": "freeze",
        "summary": "当前改善空间有限，建议维持现状",
        "reasons": ["冷静期约束生效", "候选动作边际提升有限"],
        "primary_recommendation": "freeze",
        "guardrails": ["cooldown_active=true"],
        "execution_notes": ["trigger_type=monthly"],
        "trace_refs": {"run_id": "test_run"},
    }
    assert_decision_card_is_pure_render(fake_card)


@pytest.mark.contract
def test_orchestrator_runtime_guardrails_flow_into_decision_card(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _fake_runtime_optimizer(**kwargs):
        assert kwargs["mode"] == RuntimeOptimizerMode.MONTHLY
        return _poverty_runtime_result(RuntimeOptimizerMode.MONTHLY)

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "flow_monthly_poverty"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )
    card = build_decision_card(result.card_build_input)

    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert result.decision_card == card
    assert card["recommended_action"] == "freeze"
    assert "candidate_poverty=true" in card["guardrails"]
    assert "forced_safe_action=freeze" in card["guardrails"]
    assert card["trace_refs"]["run_id"] == result.run_id
    assert card["trace_refs"]["bundle_id"] == result.bundle_id
    assert card["trace_refs"]["calibration_id"] == result.calibration_id
    assert card["trace_refs"]["solver_snapshot_id"] == result.solver_snapshot_id
    assert card["trace_refs"]["selected_workflow_type"] == "monthly"
    assert result.card_build_input is not None
    assert result.card_build_input.workflow_decision is not None
    assert result.card_build_input.runtime_restriction is not None
    assert result.card_build_input.audit_record is not None


@pytest.mark.contract
def test_orchestrator_blocked_flow_builds_blocked_decision_card(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "flow_blocked"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {
                "bundle_id": "bundle_acc001_20260329T120000Z",
                "bundle_quality": "degraded",
            },
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert card["card_type"] == "blocked"
    assert card["recommended_action"] == "blocked"
    assert card["primary_recommendation"] == "resolve blockers"
    assert "bundle_quality=degraded" in card["reasons"]
    assert "bundle_quality=degraded" in card["guardrails"]
    assert card["trace_refs"]["run_id"] == result.run_id


@pytest.mark.contract
def test_orchestrator_escalation_context_flows_into_decision_card(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    calibration_result = deepcopy(calibration_result_base)
    calibration_result["behavior_state"] = {
        **calibration_result["behavior_state"],
        "cooldown_active": True,
        "cooldown_until": "2026-04-02T00:00:00Z",
    }
    calibration_result["constraint_state"] = {
        **calibration_result["constraint_state"],
        "cooldown_currently_active": True,
    }

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "flow_manual_review"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result,
            "live_portfolio": live_portfolio_base,
            "control_flags": {"manual_review_requested": True},
            "user_request_context": {"requested_action": "rebalance_full"},
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )
    card = build_decision_card(result.card_build_input)

    assert result.status.value == "escalated"
    assert result.decision_card == card
    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert result.card_build_input is not None
    assert result.card_build_input.audit_record is not None
    assert result.card_build_input.audit_record.control_flags["cooldown_active"] is True
    assert result.card_build_input.audit_record.control_flags["manual_review_requested"] is True
    assert card["card_type"] == "runtime_action"
    assert card["status_badge"] == "degraded"
    assert "cooldown_active" in card["guardrails"]
    assert "high_risk_request=true" in card["guardrails"]
    assert "directive=manual_review_required" in card["execution_notes"]
    assert "cooldown_until=2026-04-02T00:00:00Z" in card["execution_notes"]
