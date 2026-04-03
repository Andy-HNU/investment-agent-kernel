from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest

import orchestrator.engine as orchestrator_engine
from allocation_engine.types import AllocationEngineResult
from decision_card.types import DecisionCardType
from orchestrator.engine import run_orchestrator
from orchestrator.types import OrchestratorResult, WorkflowStatus, WorkflowType
from runtime_optimizer.types import RuntimeOptimizerMode, RuntimeOptimizerResult
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from snapshot_ingestion.real_source_market import build_real_source_market_snapshot


def _minimal_runtime_result(mode: RuntimeOptimizerMode) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_poverty=False,
        mode=mode,
        ev_report={
            "recommended_action": {"type": "observe"},
            "ranked_actions": [
                {
                    "action": {"type": "observe"},
                    "score": {"total": 0.0},
                    "rank": 1,
                    "is_recommended": True,
                    "recommendation_reason": "contract fake runtime result",
                }
            ],
            "confidence_flag": "low",
            "confidence_reason": "contract fake runtime result",
            "goal_solver_baseline": 0.68,
            "goal_solver_after_recommended": 0.68,
        },
        state_snapshot={"mode": mode.value},
        candidates_generated=1,
        candidates_after_filter=1,
        run_timestamp="2026-03-29T12:00:00Z",
        optimizer_params_version="v1.0.0",
        goal_solver_params_version="v4.0.0",
    )


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


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.9,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.6,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
    }


def _account_raw(goal_solver_input_base: dict, live_portfolio_base: dict) -> dict:
    return {
        "weights": live_portfolio_base["weights"],
        "total_value": live_portfolio_base["total_value"],
        "available_cash": live_portfolio_base["available_cash"],
        "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
    }


def _goal_raw(goal_solver_input_base: dict) -> dict:
    return dict(goal_solver_input_base["goal"])


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = dict(goal_solver_input_base["constraints"])
    constraints.update(
        {
            "rebalancing_band": 0.10,
            "forbidden_actions": [],
            "cooling_period_days": 3,
            "soft_preferences": {},
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
            "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
        }
    )
    return constraints


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
def test_run_orchestrator_onboarding_builds_goal_baseline(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_onboarding"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert isinstance(result, OrchestratorResult)
    assert result.workflow_type == WorkflowType.ONBOARDING
    assert result.status == WorkflowStatus.COMPLETED
    assert result.goal_solver_output is not None
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.GOAL_BASELINE


@pytest.mark.contract
def test_run_orchestrator_onboarding_persistence_plan_includes_execution_plan_artifact(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_onboarding_execution_plan"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.persistence_plan is not None
    execution_plan = result.persistence_plan.artifact_records["execution_plan"]

    assert execution_plan is not None
    assert execution_plan["source_run_id"] == "run_onboarding_execution_plan"
    assert execution_plan["source_allocation_id"] == result.goal_solver_output.recommended_allocation.name
    assert execution_plan["plan_version"] == 1
    assert execution_plan["status"] == "draft"
    assert execution_plan["payload"]["plan_id"] == execution_plan["plan_id"]
    assert execution_plan["payload"]["items"]
    assert execution_plan["payload"]["plan_id"] == result.execution_plan.plan_id
    assert result.card_build_input.execution_plan_summary["plan_id"] == result.execution_plan.plan_id
    assert result.decision_card["execution_plan_summary"]["plan_id"] == result.execution_plan.plan_id


@pytest.mark.contract
def test_run_orchestrator_execution_plan_respects_user_restrictions():
    profile = UserOnboardingProfile(
        account_profile_id="orchestrator_plan_restrictions",
        display_name="Restriction User",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=["只接受黄金和现金"],
    )
    bundle = build_user_onboarding_inputs(profile, as_of="2026-03-30T00:00:00Z")
    market_snapshot = build_real_source_market_snapshot(as_of="2026-03-30T00:00:00Z")
    raw_inputs = dict(bundle.raw_inputs)
    raw_inputs["market_raw"] = market_snapshot.market_raw
    raw_inputs["historical_dataset_metadata"] = market_snapshot.historical_dataset_metadata

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_restricted_execution_plan"},
        raw_inputs=raw_inputs,
    )

    assert result.execution_plan is not None
    plan_buckets = {item.asset_bucket for item in result.execution_plan.items}

    assert plan_buckets
    assert plan_buckets.issubset({"gold", "cash_liquidity"})
    assert "equity_cn" not in plan_buckets
    assert "bond_cn" not in plan_buckets


@pytest.mark.contract
def test_run_orchestrator_onboarding_builds_snapshot_and_calibration_from_raw_inputs(
    goal_solver_input_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_raw_onboarding"},
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-03-29T12:00:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio_base),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": {
                "recent_chase_risk": "low",
                "recent_panic_risk": "none",
                "trade_frequency_30d": 1.0,
                "override_count_90d": 0,
                "cooldown_active": False,
                "cooldown_until": None,
                "behavior_penalty_coeff": 0.0,
            },
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert isinstance(result, OrchestratorResult)
    assert result.workflow_type == WorkflowType.ONBOARDING
    assert result.status == WorkflowStatus.COMPLETED
    assert result.snapshot_bundle is not None
    assert result.calibration_result is not None
    assert result.bundle_id == "acc001_20260329T120000Z"
    assert result.calibration_id == "acc001_20260329T120000Z"
    assert result.solver_snapshot_id == "acc001_20260329T120000Z"
    assert result.card_build_input is not None
    assert result.card_build_input.bundle_id == "acc001_20260329T120000Z"
    assert result.card_build_input.calibration_id == "acc001_20260329T120000Z"
    assert result.calibration_result.param_version_meta["updated_reason"] == "onboarding_calibration"


@pytest.mark.contract
def test_run_orchestrator_generated_calibration_honors_manual_override_metadata(
    goal_solver_input_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={
            "workflow_type": "onboarding",
            "run_id": "run_raw_manual_override",
            "manual_override_requested": True,
        },
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-03-29T12:30:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio_base),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": {
                "recent_chase_risk": "low",
                "recent_panic_risk": "none",
                "trade_frequency_30d": 1.0,
                "override_count_90d": 0,
                "cooldown_active": False,
                "cooldown_until": None,
                "behavior_penalty_coeff": 0.0,
            },
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    meta = result.calibration_result.param_version_meta

    assert meta["quality"] == "manual"
    assert meta["updated_reason"] == "manual_review"
    assert meta["is_temporary"] is False
    assert result.audit_record is not None
    assert result.audit_record.control_flags["manual_override_requested"] is True


@pytest.mark.contract
def test_run_orchestrator_generated_calibration_honors_replay_metadata(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_raw_replay_mode"},
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-03-29T12:45:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio_base),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": calibration_result_base["behavior_state"],
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "replay_mode": True,
        },
        prior_calibration=calibration_result_base,
    )

    meta = result.calibration_result.param_version_meta

    assert meta["updated_reason"] == "replay_calibration"
    assert meta["previous_version_id"] == calibration_result_base["param_version_meta"]["version_id"]
    assert meta["can_be_replayed"] is True
    assert any("replay mode calibration metadata applied" in note for note in result.calibration_result.notes)


@pytest.mark.contract
def test_run_orchestrator_generated_calibration_manual_override_beats_replay_and_marks_override_execution(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={
            "workflow_type": "onboarding",
            "run_id": "run_raw_manual_override_and_replay",
            "manual_override_requested": True,
        },
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-03-29T12:50:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio_base),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": calibration_result_base["behavior_state"],
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "replay_mode": True,
        },
        prior_calibration=calibration_result_base,
    )

    meta = result.calibration_result.param_version_meta

    assert meta["updated_reason"] == "manual_review"
    assert meta["quality"] == "manual"
    assert meta["previous_version_id"] == calibration_result_base["param_version_meta"]["version_id"]
    assert result.audit_record is not None
    assert result.persistence_plan is not None
    assert result.audit_record.control_flags["manual_override_requested"] is True
    assert result.persistence_plan.execution_record["user_override_requested"] is True


@pytest.mark.contract
def test_run_orchestrator_monthly_replay_and_manual_override_escalates_to_safe_action(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    live_portfolio = deepcopy(live_portfolio_base)
    live_portfolio["available_cash"] = 15_000.0
    live_portfolio["remaining_horizon_months"] = 143

    result = run_orchestrator(
        trigger={
            "workflow_type": "monthly",
            "run_id": "run_monthly_replay_manual_override",
            "manual_override_requested": True,
        },
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-04-29T12:00:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": {
                "recent_chase_risk": "low",
                "recent_panic_risk": "none",
                "trade_frequency_30d": 1.0,
                "override_count_90d": 1,
                "cooldown_active": False,
                "cooldown_until": None,
                "behavior_penalty_coeff": 0.0,
            },
            "remaining_horizon_months": 143,
            "live_portfolio": live_portfolio,
            "replay_mode": True,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
        prior_calibration=calibration_result_base,
    )

    meta = result.calibration_result.param_version_meta

    assert result.status == WorkflowStatus.ESCALATED
    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert result.decision_card is not None
    assert result.decision_card["recommended_action"] == "freeze"
    assert "manual_review" in result.decision_card["next_steps"]
    assert meta["updated_reason"] == "manual_review"
    assert meta["previous_version_id"] == calibration_result_base["param_version_meta"]["version_id"]
    assert result.audit_record is not None
    assert result.audit_record.control_flags["manual_override_requested"] is True
    assert result.persistence_plan is not None
    assert result.persistence_plan.execution_record["user_override_requested"] is True


@pytest.mark.contract
def test_run_orchestrator_monthly_builds_runtime_action(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_monthly"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert isinstance(result, OrchestratorResult)
    assert result.workflow_type == WorkflowType.MONTHLY
    assert result.status in {WorkflowStatus.COMPLETED, WorkflowStatus.DEGRADED}
    assert result.runtime_result is not None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.RUNTIME_ACTION


@pytest.mark.contract
def test_run_orchestrator_can_disable_provenance_checks_and_continue_runtime_flow(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_provenance_relaxed"},
        raw_inputs={
            "bundle_id": "bundle_raw_relaxed",
            "snapshot_bundle": {"bundle_id": "bundle_snapshot_relaxed"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
            "control_flags": {"disable_provenance_checks": True},
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status in {WorkflowStatus.COMPLETED, WorkflowStatus.DEGRADED}
    assert result.runtime_result is not None
    assert "bundle_id mismatch between raw_inputs and snapshot_bundle" not in result.blocking_reasons
    assert "calibration.source_bundle_id mismatch with bundle_id" not in result.blocking_reasons
    assert result.audit_record is not None
    assert result.audit_record.control_flags["enforce_provenance_checks"] is False


@pytest.mark.contract
def test_run_orchestrator_defaults_to_monthly_and_generates_run_id(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def _fake_runtime_optimizer(**kwargs):
        captured.update(kwargs)
        return _minimal_runtime_result(kwargs["mode"])

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.workflow_type == WorkflowType.MONTHLY
    assert result.run_id.startswith("monthly_")
    assert result.workflow_decision is not None
    assert result.workflow_decision.auto_selected is True
    assert result.workflow_decision.selection_reason == "default_monthly_with_prior_baseline"
    assert result.card_build_input is not None
    assert result.card_build_input.run_id == result.run_id
    assert captured["mode"] == RuntimeOptimizerMode.MONTHLY


@pytest.mark.contract
def test_run_orchestrator_blocks_on_degraded_bundle(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_blocked_bundle"},
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

    assert result.status == WorkflowStatus.BLOCKED
    assert result.goal_solver_output is None
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert "bundle_quality=degraded" in result.blocking_reasons


@pytest.mark.contract
def test_run_orchestrator_partial_calibration_marks_degraded(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    calibration_result = dict(calibration_result_base)
    calibration_result["calibration_quality"] = "partial"

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_partial_calibration"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status == WorkflowStatus.DEGRADED
    assert result.runtime_result is not None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.RUNTIME_ACTION
    assert "calibration_quality=partial" in result.degraded_notes


@pytest.mark.contract
def test_run_orchestrator_monthly_candidate_poverty_degrades_without_escalation(
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
        trigger={"workflow_type": "monthly", "run_id": "run_monthly_poverty"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status == WorkflowStatus.DEGRADED
    assert result.degraded_notes == ["candidate_poverty=true"]
    assert result.escalation_reasons == []
    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.RUNTIME_ACTION
    assert "forced_safe_action=freeze" in result.card_build_input.control_directives


@pytest.mark.contract
def test_run_orchestrator_blocks_when_allocation_engine_returns_no_candidates(
    goal_solver_input_base,
    calibration_result_base,
    monkeypatch,
):
    def _fake_allocation_engine(_allocation_input_value):
        return AllocationEngineResult(
            candidate_set_id="empty",
            account_profile_id=goal_solver_input_base["account_profile_id"],
            engine_version="v1.0.0",
            candidate_allocations=[],
            diagnostics=[],
            warnings=["candidate count below min_candidates: 0 < 4"],
        )

    monkeypatch.setattr(orchestrator_engine, "run_allocation_engine", _fake_allocation_engine)
    result = orchestrator_engine.run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_empty_allocs"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.goal_solver_output is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert "allocation_engine returned no candidates" in result.blocking_reasons


@pytest.mark.contract
def test_run_orchestrator_quarterly_candidate_poverty_escalates(
    goal_solver_input_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _fake_runtime_optimizer(**kwargs):
        assert kwargs["mode"] == RuntimeOptimizerMode.QUARTERLY
        return _poverty_runtime_result(RuntimeOptimizerMode.QUARTERLY)

    monkeypatch.setattr(
        orchestrator_engine,
        "run_runtime_optimizer",
        _fake_runtime_optimizer,
    )
    result = orchestrator_engine.run_orchestrator(
        trigger={"workflow_type": "quarterly", "run_id": "run_quarterly_poverty"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "live_portfolio": live_portfolio_base,
        },
    )

    assert result.workflow_type == WorkflowType.QUARTERLY
    assert result.status == WorkflowStatus.ESCALATED
    assert result.goal_solver_output is not None
    assert result.runtime_result is not None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.QUARTERLY_REVIEW
    assert "candidate_poverty=true" in result.degraded_notes
    assert "quarterly_candidate_poverty" in result.escalation_reasons


@pytest.mark.contract
def test_run_orchestrator_quarterly_builds_review_card(
    goal_solver_input_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "quarterly", "run_id": "run_quarterly"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "live_portfolio": live_portfolio_base,
        },
    )

    assert isinstance(result, OrchestratorResult)
    assert result.workflow_type == WorkflowType.QUARTERLY
    assert result.status == WorkflowStatus.COMPLETED
    assert result.goal_solver_output is not None
    assert result.runtime_result is not None
    assert result.runtime_result.mode == RuntimeOptimizerMode.QUARTERLY
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.QUARTERLY_REVIEW
    assert result.solver_snapshot_id == result.goal_solver_output.input_snapshot_id


@pytest.mark.contract
def test_run_orchestrator_blocks_on_degraded_calibration_without_running_runtime(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    calibration_result = deepcopy(calibration_result_base)
    calibration_result["calibration_quality"] = "degraded"

    def _unexpected_runtime(**_kwargs):
        raise AssertionError("runtime optimizer should not run when calibration is degraded")

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _unexpected_runtime)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_blocked_calibration"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert result.blocking_reasons == ["calibration_quality=degraded"]


@pytest.mark.contract
def test_run_orchestrator_blocks_on_prior_solver_baseline_version_mismatch(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    goal_solver_output = deepcopy(goal_solver_output_base)
    goal_solver_output["input_snapshot_id"] = "snapshot_mismatch"
    goal_solver_output["params_version"] = "v9.9.9"

    def _unexpected_runtime(**_kwargs):
        raise AssertionError("runtime optimizer should not run on baseline mismatch")

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _unexpected_runtime)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_baseline_mismatch"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert "prior solver baseline snapshot mismatch" in result.blocking_reasons
    assert "prior solver baseline params_version mismatch" in result.blocking_reasons


@pytest.mark.contract
def test_run_orchestrator_blocks_on_raw_and_snapshot_bundle_mismatch(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _unexpected_runtime(**_kwargs):
        raise AssertionError("runtime optimizer should not run on provenance mismatch")

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _unexpected_runtime)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_bundle_mismatch"},
        raw_inputs={
            "bundle_id": "bundle_raw",
            "snapshot_bundle": {"bundle_id": "bundle_snapshot"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert "bundle_id mismatch between raw_inputs and snapshot_bundle" in result.blocking_reasons
    assert "calibration.source_bundle_id mismatch with bundle_id" in result.blocking_reasons
    assert "param_version_meta.source_bundle_id mismatch with bundle_id" in result.blocking_reasons
    assert "market_state.source_bundle_id mismatch with bundle_id" in result.blocking_reasons


@pytest.mark.contract
def test_run_orchestrator_can_disable_provenance_checks_for_replay_like_flow(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def _fake_runtime_optimizer(**kwargs):
        captured.update(kwargs)
        return _minimal_runtime_result(kwargs["mode"])

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_provenance_disabled"},
        raw_inputs={
            "bundle_id": "bundle_runtime_new",
            "snapshot_bundle": {"bundle_id": "bundle_runtime_new"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
            "control_flags": {"disable_provenance_checks": True},
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.status in {WorkflowStatus.COMPLETED, WorkflowStatus.DEGRADED}
    assert result.runtime_result is not None
    assert result.audit_record is not None
    assert result.audit_record.control_flags["enforce_provenance_checks"] is False
    assert captured["mode"] == RuntimeOptimizerMode.MONTHLY
    assert "calibration.source_bundle_id mismatch with bundle_id" not in result.blocking_reasons


@pytest.mark.contract
def test_run_orchestrator_monthly_uses_prior_calibration_and_marks_partial_as_degraded(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    prior_calibration = deepcopy(calibration_result_base)
    prior_calibration["calibration_id"] = "acc001_prior_partial"
    prior_calibration["calibration_quality"] = "partial"
    captured: dict[str, object] = {}

    def _fake_runtime_optimizer(**kwargs):
        captured.update(kwargs)
        return _minimal_runtime_result(kwargs["mode"])

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_prior_partial"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
        prior_calibration=prior_calibration,
    )

    assert result.status == WorkflowStatus.DEGRADED
    assert result.calibration_id == "acc001_prior_partial"
    assert result.degraded_notes == ["calibration_quality=partial"]
    assert result.runtime_result is not None
    assert captured["mode"] == RuntimeOptimizerMode.MONTHLY
    assert captured["market_state"] == prior_calibration["market_state"]
    assert captured["behavior_state"] == prior_calibration["behavior_state"]
    assert captured["constraint_state"] == prior_calibration["constraint_state"]
    assert captured["ev_params"] == prior_calibration["ev_params"]
    assert captured["optimizer_params"] == prior_calibration["runtime_optimizer_params"]


@pytest.mark.contract
def test_run_orchestrator_event_escalates_behavior_candidate_poverty_and_forwards_flags(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def _fake_runtime_optimizer(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(candidate_poverty=True, mode=kwargs["mode"])

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={
            "workflow_type": "event",
            "run_id": "run_event_behavior",
            "structural_event": True,
            "behavior_event": True,
            "drawdown_event": True,
            "satellite_event": True,
        },
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    assert result.workflow_type == WorkflowType.EVENT
    assert result.status == WorkflowStatus.ESCALATED
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.RUNTIME_ACTION
    assert result.degraded_notes == ["candidate_poverty=true"]
    assert result.escalation_reasons == ["behavior_event_with_candidate_poverty"]
    assert captured["mode"] == RuntimeOptimizerMode.EVENT
    assert captured["structural_event"] is True
    assert captured["behavior_event"] is True
    assert captured["drawdown_event"] is True
    assert captured["satellite_event"] is True


@pytest.mark.contract
def test_run_orchestrator_monthly_requires_prior_solver_baseline(
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _unexpected_runtime(**_kwargs):
        raise AssertionError("runtime optimizer should not run without a solver baseline")

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _unexpected_runtime)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_missing_baseline"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.goal_solver_output is None
    assert result.runtime_result is None
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.BLOCKED
    assert result.blocking_reasons == ["prior solver baseline is required"]


@pytest.mark.contract
def test_orchestrator_result_to_dict_keeps_audit_trace_fields(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "run_monthly_audit"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )

    data = result.to_dict()

    assert data["run_id"] == "run_monthly_audit"
    assert data["workflow_type"] == "monthly"
    assert data["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert data["calibration_id"] == calibration_result_base["calibration_id"]
    assert data["solver_snapshot_id"] == goal_solver_output_base["input_snapshot_id"]
    assert data["snapshot_bundle"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert data["goal_solver_output"]["input_snapshot_id"] == goal_solver_output_base["input_snapshot_id"]
    assert data["runtime_result"]["mode"] == "monthly"
    assert data["card_build_input"]["run_id"] == "run_monthly_audit"
    assert data["card_build_input"]["workflow_type"] == "monthly"
    assert data["card_build_input"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert data["card_build_input"]["calibration_id"] == calibration_result_base["calibration_id"]
    assert data["decision_card"]["trace_refs"]["run_id"] == "run_monthly_audit"
    assert data["decision_card"]["trace_refs"]["selected_workflow_type"] == "monthly"
    assert data["workflow_decision"]["selected_workflow_type"] == "monthly"
    assert data["workflow_decision"]["selection_reason"] == "explicit_monthly_request"
    assert data["audit_record"]["version_refs"]["run_id"] == "run_monthly_audit"
    assert data["audit_record"]["version_refs"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert data["audit_record"]["artifact_refs"]["has_runtime_result"] is True
    assert data["audit_record"]["artifact_refs"]["has_decision_card"] is True
    assert data["audit_record"]["artifact_refs"]["has_persistence_plan"] is True
    assert data["audit_record"]["artifact_refs"]["snapshot_bundle_origin"] == "provided"
    assert data["audit_record"]["artifact_refs"]["calibration_origin"] == "provided"
    assert data["persistence_plan"]["run_record"]["run_id"] == "run_monthly_audit"
    assert data["persistence_plan"]["run_record"]["status"] == "completed"
    assert data["persistence_plan"]["artifact_records"]["snapshot_bundle"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert data["persistence_plan"]["artifact_records"]["decision_card"]["run_id"] == "run_monthly_audit"
    assert data["persistence_plan"]["execution_record"]["user_executed"] is None
    assert data["persistence_plan"]["execution_record"]["user_override_requested"] is False


@pytest.mark.contract
def test_orchestrator_result_to_dict_is_json_safe_for_datetime_and_namespace_payloads():
    result = OrchestratorResult(
        run_id="run_json_safe",
        workflow_type=WorkflowType.MONTHLY,
        status=WorkflowStatus.DEGRADED,
        snapshot_bundle={
            "created_at": datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
            "effective_date": date(2026, 3, 29),
            "labels": {"beta", "alpha"},
        },
        runtime_result=SimpleNamespace(
            mode="monthly",
            generated_at=datetime(2026, 3, 29, 12, 5, tzinfo=timezone.utc),
            flags={"cooldown"},
        ),
    )

    payload = result.to_dict()
    json.loads(json.dumps(payload, ensure_ascii=False))

    assert payload["snapshot_bundle"]["created_at"] == "2026-03-29T12:00:00Z"
    assert payload["snapshot_bundle"]["effective_date"] == "2026-03-29"
    assert payload["snapshot_bundle"]["labels"] == ["alpha", "beta"]
    assert payload["runtime_result"]["mode"] == "monthly"
    assert payload["runtime_result"]["generated_at"] == "2026-03-29T12:05:00Z"
    assert payload["runtime_result"]["flags"] == ["cooldown"]


@pytest.mark.contract
def test_run_orchestrator_blocked_flow_emits_ledger_ready_audit_and_persistence(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_blocked_ledger"},
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

    assert result.status == WorkflowStatus.BLOCKED
    assert result.audit_record is not None
    assert result.persistence_plan is not None
    assert result.audit_record.selected_workflow_type == "onboarding"
    assert result.audit_record.selection_reason == "missing_prior_baseline"
    assert result.audit_record.version_refs["run_id"] == "run_blocked_ledger"
    assert result.audit_record.version_refs["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert result.audit_record.version_refs["calibration_id"] == calibration_result_base["calibration_id"]
    assert result.audit_record.artifact_refs["has_goal_solver_output"] is False
    assert result.audit_record.artifact_refs["has_runtime_result"] is False
    assert result.audit_record.artifact_refs["has_card_build_input"] is True
    assert result.audit_record.artifact_refs["has_decision_card"] is True
    assert result.audit_record.outcome["status"] == "blocked"
    assert result.audit_record.outcome["blocking_reasons"] == ["bundle_quality=degraded"]
    assert result.persistence_plan.run_record["status"] == "blocked"
    assert result.persistence_plan.run_record["workflow_type"] == "onboarding"
    assert result.persistence_plan.artifact_records["goal_solver_output"] is None
    assert result.persistence_plan.artifact_records["runtime_result"] is None
    assert result.persistence_plan.artifact_records["decision_card"]["run_id"] == "run_blocked_ledger"


@pytest.mark.contract
def test_run_orchestrator_onboarding_replaces_candidates_and_fills_snapshot_from_bundle(
    goal_solver_input_base,
    calibration_result_base,
    monkeypatch,
):
    goal_solver_input = deepcopy(goal_solver_input_base)
    goal_solver_input.pop("snapshot_id")
    goal_solver_input["candidate_allocations"] = [
        {
            "name": "stale_allocation",
            "weights": {"equity_cn": 0.6, "bond_cn": 0.2, "gold": 0.1, "satellite": 0.1},
            "complexity_score": 0.9,
            "description": "stale allocation that should be replaced",
        }
    ]
    bundle_id = "bundle_from_snapshot_only"
    calibration_result = deepcopy(calibration_result_base)
    calibration_result["source_bundle_id"] = bundle_id
    calibration_result["param_version_meta"] = {
        **calibration_result["param_version_meta"],
        "source_bundle_id": bundle_id,
    }
    calibration_result["market_state"] = {
        **calibration_result["market_state"],
        "source_bundle_id": bundle_id,
    }
    calibration_result["constraint_state"] = {
        **calibration_result["constraint_state"],
        "source_bundle_id": bundle_id,
    }
    calibration_result["behavior_state"] = {
        **calibration_result["behavior_state"],
        "source_bundle_id": bundle_id,
    }
    fresh_allocations = [
        {
            "name": "fresh_allocation",
            "weights": {"equity_cn": 0.5, "bond_cn": 0.3, "gold": 0.1, "satellite": 0.1},
            "complexity_score": 0.2,
            "description": "fresh allocation from allocation engine",
        }
    ]
    captured: dict[str, object] = {}

    def _fake_allocation_engine(_inp):
        return AllocationEngineResult(
            candidate_set_id="fresh",
            account_profile_id=goal_solver_input_base["account_profile_id"],
            engine_version="v1.0.0",
            candidate_allocations=fresh_allocations,
            diagnostics=[],
            warnings=[],
        )

    def _fake_goal_solver(inp):
        captured["solver_input"] = inp
        return {"input_snapshot_id": inp["snapshot_id"]}

    monkeypatch.setattr(orchestrator_engine, "run_allocation_engine", _fake_allocation_engine)
    monkeypatch.setattr(orchestrator_engine, "run_goal_solver", _fake_goal_solver)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_bundle_binding"},
        raw_inputs={
            "snapshot_bundle": {"bundle_id": bundle_id},
            "calibration_result": calibration_result,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input,
        },
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.bundle_id == bundle_id
    assert result.solver_snapshot_id == bundle_id
    assert captured["solver_input"]["snapshot_id"] == bundle_id
    assert captured["solver_input"]["candidate_allocations"] == fresh_allocations
    assert result.card_build_input is not None
    assert result.card_build_input.card_type == DecisionCardType.GOAL_BASELINE
    assert result.card_build_input.bundle_id == bundle_id
