from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest

import orchestrator.engine as orchestrator_engine
from allocation_engine.types import AllocationEngineResult
from decision_card.types import DecisionCardType
from orchestrator.engine import (
    _apply_progressive_recommendation_expansion,
    _build_persistence_plan,
    _rerank_goal_solver_output_with_v14_primary,
    run_orchestrator,
)
from orchestrator.types import OrchestratorResult, WorkflowStatus, WorkflowType
from probability_engine.contracts import (
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
)
from runtime_optimizer.types import RuntimeOptimizerMode, RuntimeOptimizerResult
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


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


def _probability_result(
    *,
    success_probability: float,
    cagr_p50: float,
    terminal_value_mean: float,
) -> ProbabilityEngineRunResult:
    cagr_low = cagr_p50 - 0.01
    cagr_high = cagr_p50 + 0.01
    terminal_value_p50 = terminal_value_mean
    return ProbabilityEngineRunResult(
        run_outcome_status="success",
        resolved_result_category="formal_strict_result",
        output=ProbabilityEngineOutput(
            primary_result=RecipeSimulationResult(
                recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
                role="primary",
                success_probability=success_probability,
                success_probability_range=(max(success_probability - 0.02, 0.0), min(success_probability + 0.02, 1.0)),
                cagr_range=(cagr_low, cagr_high),
                drawdown_range=(0.02, 0.08),
                sample_count=32,
                path_stats=PathStatsSummary(
                    terminal_value_mean=terminal_value_mean,
                    terminal_value_p05=terminal_value_mean * 0.92,
                    terminal_value_p50=terminal_value_p50,
                    terminal_value_p95=terminal_value_mean * 1.08,
                    cagr_p05=cagr_low,
                    cagr_p50=cagr_p50,
                    cagr_p95=cagr_high,
                    max_drawdown_p05=0.01,
                    max_drawdown_p50=0.04,
                    max_drawdown_p95=0.08,
                    success_count=int(success_probability * 32),
                    path_count=32,
                ),
                calibration_link_ref="evidence://contract/v14",
            ),
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=ProbabilityDisclosurePayload(
                published_point=success_probability,
                published_range=(max(success_probability - 0.02, 0.0), min(success_probability + 0.02, 1.0)),
                disclosure_level="point_and_range",
                confidence_level="medium",
                challenger_gap=None,
                stress_gap=None,
                gap_total=0.0,
                widening_method="contract",
            ),
            evidence_refs=["evidence://contract/v14"],
        ),
        failure_artifact=None,
    )


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
def test_run_orchestrator_blocks_strict_formal_path_without_observed_runtime_inputs(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_onboarding_formal_path_blocked"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "formal_path_required": True,
        },
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.goal_solver_output is None
    assert result.execution_plan is None
    assert any("candidate_product_context" in reason for reason in result.blocking_reasons)
    assert result.run_outcome_status == "blocked"
    assert result.resolved_result_category is None
    assert result.disclosure_decision["disclosure_level"] == "unavailable"


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
def test_execution_plan_payload_comparison_distinguishes_split_bucket_members() -> None:
    active_payload = {
        "items": [
            {
                "asset_bucket": "equity_cn",
                "primary_product_id": "cn_equity_csi300_etf",
                "target_weight": 0.20,
            },
            {
                "asset_bucket": "equity_cn",
                "primary_product_id": "cn_equity_dividend_etf",
                "target_weight": 0.20,
            },
        ]
    }
    pending_payload = {
        "items": [
            {
                "asset_bucket": "equity_cn",
                "primary_product_id": "cn_equity_dividend_etf",
                "target_weight": 0.20,
            },
            {
                "asset_bucket": "equity_cn",
                "primary_product_id": "cn_equity_low_vol_fund",
                "target_weight": 0.20,
            },
        ]
    }

    comparison = orchestrator_engine._compare_execution_plan_payloads(active_payload, pending_payload)

    assert comparison is not None
    assert comparison["changed_bucket_count"] == 2
    assert {item["item_key"] for item in comparison["bucket_changes"]} == {
        "equity_cn::cn_equity_csi300_etf",
        "equity_cn::cn_equity_low_vol_fund",
    }


@pytest.mark.contract
def test_run_orchestrator_attaches_candidate_product_contexts_before_solver(
    goal_solver_input_base,
    calibration_result_base,
    monkeypatch,
):
    monkeypatch.setattr(
        orchestrator_engine,
        "_build_solver_candidate_product_contexts",
        lambda **_kwargs: {
            "balanced_core__moderate__02": {
                "allocation_name": "balanced_core__moderate__02",
                "product_probability_method": "product_proxy_adjustment_estimate",
                "selected_product_ids": ["510300", "511010"],
                "bucket_expected_return_adjustments": {"equity_cn": 0.01},
                "bucket_volatility_multipliers": {"equity_cn": 1.08},
            }
        },
    )

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_onboarding_product_context"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert result.status == WorkflowStatus.COMPLETED
    contexts = result.card_build_input.goal_solver_input["candidate_product_contexts"]
    assert contexts
    for context in contexts.values():
        assert context["product_probability_method"] == "product_proxy_adjustment_estimate"
        assert context["selected_product_ids"]
        assert "bucket_expected_return_adjustments" in context


@pytest.mark.contract
def test_build_solver_candidate_product_contexts_defaults_initial_recommendation_to_l0_compact(monkeypatch):
    observed_levels: list[str] = []

    def _fake_build_candidate_product_context(*, source_allocation_id, search_expansion_level="L0_compact", **_kwargs):
        observed_levels.append(search_expansion_level)
        return {
            "allocation_name": source_allocation_id,
            "search_expansion_level": search_expansion_level,
            "selected_product_ids": [f"{source_allocation_id}_{search_expansion_level}"],
        }

    monkeypatch.setattr(orchestrator_engine, "build_candidate_product_context", _fake_build_candidate_product_context)

    compact_contexts = orchestrator_engine._build_solver_candidate_product_contexts(
        candidate_allocations=[
            {"name": "compact_primary", "weights": {"equity_cn": 0.55, "bond_cn": 0.35, "gold": 0.10}},
        ],
        envelope={},
        snapshot_bundle=None,
        formal_path_required=False,
        execution_policy=orchestrator_engine.ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED,
    )
    expanded_contexts = orchestrator_engine._build_solver_candidate_product_contexts(
        candidate_allocations=[
            {"name": "compact_primary", "weights": {"equity_cn": 0.55, "bond_cn": 0.35, "gold": 0.10}},
        ],
        envelope={},
        snapshot_bundle=None,
        formal_path_required=False,
        execution_policy=orchestrator_engine.ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED,
        search_expansion_level="L1_expanded",
    )

    assert compact_contexts["compact_primary"]["search_expansion_level"] == "L0_compact"
    assert expanded_contexts["compact_primary"]["search_expansion_level"] == "L1_expanded"
    assert observed_levels == ["L0_compact", "L1_expanded"]


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

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_restricted_execution_plan"},
        raw_inputs=bundle.raw_inputs,
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


@pytest.mark.contract
def test_run_orchestrator_onboarding_auto_enriches_runtime_product_inputs_without_market_raw(
    goal_solver_input_base,
    calibration_result_base,
    monkeypatch,
):
    goal_solver_input = deepcopy(goal_solver_input_base)
    allocation_result = AllocationEngineResult(
        candidate_set_id="fresh",
        account_profile_id=goal_solver_input_base["account_profile_id"],
        engine_version="v1.0.0",
        candidate_allocations=[
            {
                "name": "fresh_allocation",
                "weights": {"equity_cn": 0.5, "bond_cn": 0.3, "gold": 0.1, "satellite": 0.1},
                "complexity_score": 0.2,
                "description": "fresh allocation from allocation engine",
            }
        ],
        diagnostics=[],
        warnings=[],
    )
    enriched_market_raw = {
        "product_universe_inputs": {"requested": True, "source_kind": "tinyshare_runtime_catalog"},
        "product_universe_result": {
            "source_status": "observed",
            "source_name": "tinyshare_runtime_catalog",
            "source_ref": "tinyshare://runtime_catalog",
            "snapshot_id": "tinyshare_runtime_catalog_2026-04-06",
            "item_count": 1,
            "runtime_candidates": [
                {
                    "product_id": "ts_stock_000001_sz",
                    "product_name": "平安银行",
                    "asset_bucket": "equity_cn",
                    "product_family": "a_share_stock",
                    "wrapper_type": "stock",
                    "provider_source": "tinyshare_stock_basic",
                    "provider_symbol": "000001.SZ",
                    "tags": ["equity", "stock_wrapper", "cn"],
                    "risk_labels": ["个股波动", "集中度"],
                }
            ],
        },
        "product_valuation_inputs": {"requested": True, "source_kind": "tinyshare_runtime_valuation"},
        "product_valuation_result": {
            "source_status": "observed",
            "source_name": "tinyshare_runtime_valuation",
            "source_ref": "tinyshare://daily_basic?trade_date=20260403",
            "products": {},
            },
        }
    captured_build_plan: dict[str, object] = {}
    monkeypatch.setattr(orchestrator_engine, "run_allocation_engine", lambda _inp: allocation_result)
    monkeypatch.setattr(
        orchestrator_engine,
        "enrich_market_raw_with_runtime_product_inputs",
        lambda market_raw, *, as_of, formal_path_required=False, execution_policy=None: enriched_market_raw,
    )

    monkeypatch.setattr(
        orchestrator_engine,
        "run_goal_solver",
        lambda inp: {
            "input_snapshot_id": inp["snapshot_id"],
            "recommended_allocation": {
                "name": "fresh_allocation",
                "weights": {"equity_cn": 0.5, "bond_cn": 0.3, "gold": 0.1, "satellite": 0.1},
            },
        },
    )

    def _fake_build_execution_plan(**kwargs):
        captured_build_plan["kwargs"] = kwargs
        return {
            "product_universe_audit_summary": {"requested": True, "source_status": "observed"},
            "valuation_audit_summary": {"requested": True, "source_status": "observed"},
        }

    monkeypatch.setattr(
        orchestrator_engine,
        "build_execution_plan",
        _fake_build_execution_plan,
    )

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_auto_enrich"},
        raw_inputs={
            "as_of": "2026-04-06T12:00:00Z",
            "account_raw": {
                "weights": {"equity_cn": 0.5, "bond_cn": 0.25, "gold": 0.15, "satellite": 0.10},
                "total_value": 100000.0,
                "available_cash": 5000.0,
                "remaining_horizon_months": 36,
            },
            "control_flags": {"disable_provenance_checks": True},
            "snapshot_bundle": {
                "bundle_id": calibration_result_base["source_bundle_id"],
                "bundle_quality": "full",
            },
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input,
        },
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert captured_build_plan["kwargs"]["product_universe_inputs"]["requested"] is True
    assert captured_build_plan["kwargs"]["product_universe_result"]["source_status"] == "observed"
    assert captured_build_plan["kwargs"]["valuation_inputs"]["requested"] is True


@pytest.mark.contract
def test_v14_primary_reranking_prefers_closest_required_return_candidate_and_keeps_highest_success_alternative(monkeypatch):
    goal_solver_input = {
        "candidate_allocations": [
            {"name": "closest_to_target", "weights": {"equity_cn": 0.40, "bond_cn": 0.35, "gold": 0.15, "satellite": 0.10}},
            {"name": "same_distance_higher_success", "weights": {"equity_cn": 0.42, "bond_cn": 0.28, "gold": 0.20, "satellite": 0.10}},
            {"name": "highest_success_farther", "weights": {"equity_cn": 0.60, "bond_cn": 0.15, "gold": 0.10, "satellite": 0.15}},
        ]
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "highest_success_farther",
            "weights": {"equity_cn": 0.60, "bond_cn": 0.15, "gold": 0.10, "satellite": 0.15},
        },
        "recommended_result": {
            "allocation_name": "highest_success_farther",
            "implied_required_annual_return": 0.06,
            "success_probability": 0.82,
            "expected_annual_return": 0.085,
        },
        "all_results": [
            {
                "allocation_name": "closest_to_target",
                "implied_required_annual_return": 0.06,
                "success_probability": 0.68,
                "expected_annual_return": 0.061,
                "max_drawdown_p95": 0.06,
                "terminal_value_p50": 120500.0,
            },
            {
                "allocation_name": "same_distance_higher_success",
                "implied_required_annual_return": 0.06,
                "success_probability": 0.79,
                "expected_annual_return": 0.059,
                "max_drawdown_p95": 0.05,
                "terminal_value_p50": 120100.0,
            },
            {
                "allocation_name": "highest_success_farther",
                "implied_required_annual_return": 0.06,
                "success_probability": 0.91,
                "expected_annual_return": 0.085,
                "max_drawdown_p95": 0.03,
                "terminal_value_p50": 126000.0,
            },
        ],
        "frontier_analysis": {
            "recommended": {"label": "highest_success_farther", "allocation_name": "highest_success_farther"},
            "highest_probability": {"label": "highest_success_farther", "allocation_name": "highest_success_farther"},
            "target_return_priority": {"label": "same_distance_higher_success", "allocation_name": "same_distance_higher_success"},
        },
        "solver_notes": [],
    }

    def _fake_build(**kwargs):  # type: ignore[no-untyped-def]
        allocation_name = kwargs.get("allocation_name")
        return ({"evidence_bundle_ref": f"evidence://contract/{allocation_name}"}, {})

    def _fake_probability_engine(sim_input):  # type: ignore[no-untyped-def]
        if str(sim_input["evidence_bundle_ref"]).endswith("/closest_to_target"):
            return _probability_result(success_probability=0.68, cagr_p50=0.061, terminal_value_mean=120500.0)
        if str(sim_input["evidence_bundle_ref"]).endswith("/same_distance_higher_success"):
            return _probability_result(success_probability=0.79, cagr_p50=0.059, terminal_value_mean=120100.0)
        return _probability_result(success_probability=0.91, cagr_p50=0.085, terminal_value_mean=126000.0)

    monkeypatch.setattr(orchestrator_engine, "_build_probability_engine_run_input", _fake_build)
    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _fake_probability_engine)

    updated_output, probability_input, probability_result = _rerank_goal_solver_output_with_v14_primary(
        run_id="contract_rerank_target",
        envelope={},
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
    )

    assert updated_output["recommended_result"]["allocation_name"] == "same_distance_higher_success"
    assert updated_output["recommended_allocation"]["name"] == "same_distance_higher_success"
    assert updated_output["frontier_analysis"]["recommended"]["allocation_name"] == "same_distance_higher_success"
    assert updated_output["frontier_analysis"]["target_return_priority"]["allocation_name"] == "closest_to_target"
    assert updated_output["frontier_analysis"]["highest_probability"]["allocation_name"] == "highest_success_farther"
    assert updated_output["frontier_analysis"]["scenario_status"]["target_return_priority"]["reason"] == "selected_meets_required_annual_return"
    assert probability_input["evidence_bundle_ref"].endswith("/same_distance_higher_success")
    assert probability_result.output is not None
    assert updated_output["v14_candidate_probability_ranking"]["same_distance_higher_success"]["success_probability"] == pytest.approx(0.79)


@pytest.mark.contract
def test_v14_primary_reranking_uses_closest_required_return_before_success_probability(monkeypatch):
    key = orchestrator_engine._candidate_probability_ranking_key
    required_return = 0.06
    summaries = {
        "closest_lower_success": {
            "run_outcome_status": "success",
            "resolved_result_category": "formal_strict_result",
            "success_probability": 0.62,
            "cagr_p50": 0.061,
            "max_drawdown_p95": 0.06,
            "terminal_value_p50": 120200.0,
        },
        "same_distance_higher_success": {
            "run_outcome_status": "success",
            "resolved_result_category": "formal_strict_result",
            "success_probability": 0.80,
            "cagr_p50": 0.059,
            "max_drawdown_p95": 0.05,
            "terminal_value_p50": 120000.0,
        },
        "highest_success_farther": {
            "run_outcome_status": "success",
            "resolved_result_category": "formal_strict_result",
            "success_probability": 0.95,
            "cagr_p50": 0.085,
            "max_drawdown_p95": 0.03,
            "terminal_value_p50": 126000.0,
        },
    }

    ranked = sorted(summaries, key=lambda name: key(summaries[name], required_return=required_return), reverse=True)

    assert ranked == [
        "same_distance_higher_success",
        "closest_lower_success",
        "highest_success_farther",
    ]


@pytest.mark.contract
def test_v14_primary_reranking_falls_back_to_highest_success_when_required_return_is_missing(monkeypatch):
    goal_solver_input = {
        "candidate_allocations": [
            {"name": "balanced", "weights": {"equity_cn": 0.45, "bond_cn": 0.30, "gold": 0.15, "satellite": 0.10}},
            {"name": "high_success", "weights": {"equity_cn": 0.35, "bond_cn": 0.40, "gold": 0.15, "satellite": 0.10}},
        ]
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "balanced",
            "weights": {"equity_cn": 0.45, "bond_cn": 0.30, "gold": 0.15, "satellite": 0.10},
        },
        "recommended_result": {
            "allocation_name": "balanced",
            "implied_required_annual_return": None,
            "success_probability": 0.60,
            "expected_annual_return": 0.05,
        },
        "all_results": [
            {
                "allocation_name": "balanced",
                "implied_required_annual_return": None,
                "success_probability": 0.60,
                "expected_annual_return": 0.05,
            },
            {
                "allocation_name": "high_success",
                "implied_required_annual_return": None,
                "success_probability": 0.72,
                "expected_annual_return": 0.04,
            },
        ],
        "frontier_analysis": {
            "recommended": {"label": "balanced", "allocation_name": "balanced"},
            "highest_probability": {"label": "high_success", "allocation_name": "high_success"},
            "target_return_priority": {"label": "", "allocation_name": ""},
            "scenario_status": {
                "target_return_priority": {"available": False, "reason": "required_annual_return_not_provided"}
            },
        },
        "solver_notes": [],
    }

    def _fake_build(**kwargs):  # type: ignore[no-untyped-def]
        allocation_name = kwargs.get("allocation_name")
        return ({"evidence_bundle_ref": f"evidence://contract/{allocation_name}"}, {})

    def _fake_probability_engine(sim_input):  # type: ignore[no-untyped-def]
        if str(sim_input["evidence_bundle_ref"]).endswith("/balanced"):
            return _probability_result(success_probability=0.61, cagr_p50=0.051, terminal_value_mean=118000.0)
        return _probability_result(success_probability=0.73, cagr_p50=0.041, terminal_value_mean=116500.0)

    monkeypatch.setattr(orchestrator_engine, "_build_probability_engine_run_input", _fake_build)
    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _fake_probability_engine)

    updated_output, _, _ = _rerank_goal_solver_output_with_v14_primary(
        run_id="contract_rerank_no_required_return",
        envelope={},
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
    )

    assert updated_output["recommended_result"]["allocation_name"] == "high_success"
    assert updated_output["frontier_analysis"]["highest_probability"]["allocation_name"] == "high_success"
    assert updated_output["frontier_analysis"]["scenario_status"]["target_return_priority"]["reason"] == "required_annual_return_not_provided"


@pytest.mark.contract
def test_progressive_recommendation_expansion_adds_expanded_alternatives_without_overwriting_compact_primary(
    monkeypatch,
):
    goal_solver_input = {
        "candidate_allocations": [
            {"name": "compact_primary", "weights": {"equity_cn": 0.55, "bond_cn": 0.35, "gold": 0.10}},
            {"name": "higher_success_alt", "weights": {"equity_cn": 0.60, "bond_cn": 0.25, "gold": 0.15}},
        ],
        "candidate_product_contexts": {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l0", "bond_l0"],
            },
            "higher_success_alt": {
                "allocation_name": "higher_success_alt",
                "selected_product_ids": ["equity_alt_l0", "bond_alt_l0"],
            },
        },
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "compact_primary",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.35, "gold": 0.10},
        },
        "recommended_result": {
            "allocation_name": "compact_primary",
            "success_probability": 0.67,
            "expected_annual_return": 0.056,
            "implied_required_annual_return": 0.06,
        },
        "all_results": [
            {
                "allocation_name": "compact_primary",
                "success_probability": 0.67,
                "expected_annual_return": 0.056,
                "implied_required_annual_return": 0.06,
            },
            {
                "allocation_name": "higher_success_alt",
                "success_probability": 0.72,
                "expected_annual_return": 0.071,
                "implied_required_annual_return": 0.06,
            },
        ],
        "frontier_analysis": {
            "recommended": {"allocation_name": "compact_primary"},
            "highest_probability": {"allocation_name": "higher_success_alt"},
            "target_return_priority": {"allocation_name": "compact_primary"},
            "scenario_status": {},
        },
        "solver_notes": [],
    }

    monkeypatch.setattr(
        orchestrator_engine,
        "_build_solver_candidate_product_contexts",
        lambda **_kwargs: {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l1", "bond_l0", "gold_l1"],
            },
            "higher_success_alt": {
                "allocation_name": "higher_success_alt",
                "selected_product_ids": ["equity_alt_l1", "bond_alt_l0", "gold_alt_l1"],
            },
        },
    )
    monkeypatch.setattr(
        orchestrator_engine,
        "_rerank_goal_solver_output_with_v14_primary",
        lambda **_kwargs: (
            {
                "recommended_allocation": {
                    "name": "compact_primary",
                    "weights": {"equity_cn": 0.55, "bond_cn": 0.35, "gold": 0.10},
                },
                "recommended_result": {
                    "allocation_name": "compact_primary",
                    "success_probability": 0.69,
                    "expected_annual_return": 0.058,
                    "implied_required_annual_return": 0.06,
                },
                "all_results": [
                    {
                        "allocation_name": "compact_primary",
                        "success_probability": 0.69,
                        "expected_annual_return": 0.058,
                        "implied_required_annual_return": 0.06,
                    },
                    {
                        "allocation_name": "higher_success_alt",
                        "success_probability": 0.74,
                        "expected_annual_return": 0.072,
                        "implied_required_annual_return": 0.06,
                    },
                ],
                "frontier_analysis": {
                    "recommended": {"allocation_name": "compact_primary"},
                    "highest_probability": {"allocation_name": "higher_success_alt"},
                    "target_return_priority": {"allocation_name": "compact_primary"},
                    "scenario_status": {},
                },
            },
            {"evidence_bundle_ref": "evidence://contract/compact_primary"},
            _probability_result(success_probability=0.69, cagr_p50=0.058, terminal_value_mean=121000.0),
        ),
    )

    updated_output, recommendation_expansion = _apply_progressive_recommendation_expansion(
        run_id="contract_progressive_expansion",
        envelope={"search_expansion_level": "L1_expanded", "why_this_level_was_run": "user_requested_deeper_search"},
        snapshot_bundle=None,
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
        formal_path_required=False,
        execution_policy="formal_estimation_allowed",
    )

    expansion = updated_output["frontier_diagnostics"]["recommendation_expansion"]

    assert updated_output["recommended_result"]["allocation_name"] == "compact_primary"
    assert recommendation_expansion["requested_search_expansion_level"] == "L1_expanded"
    assert recommendation_expansion["why_this_level_was_run"] == "user_requested_deeper_search"
    assert recommendation_expansion["new_product_ids_added"] == ["equity_l1", "gold_l1"]
    assert recommendation_expansion["products_removed"] == ["equity_l0"]
    assert expansion["search_expansion_level"] == "L0_compact"
    assert expansion["requested_search_expansion_level"] == "L1_expanded"
    assert expansion["alternatives"][0]["recommended_result"]["allocation_name"] == "compact_primary"
    assert expansion["alternatives"][0]["new_product_ids_added"] == ["equity_l1", "gold_l1"]
    assert expansion["alternatives"][0]["difference_basis"]["comparison_scope"] == "same_allocation_search_expansion"
    assert expansion["alternatives"][0]["difference_basis"]["reference_search_expansion_level"] == "L0_compact"


@pytest.mark.contract
def test_progressive_recommendation_expansion_uses_no_delta_stop_reason_for_requested_level_no_product_delta(
    monkeypatch,
):
    goal_solver_input = {
        "candidate_allocations": [{"name": "compact_primary", "weights": {"equity_cn": 0.55, "bond_cn": 0.35}}],
        "candidate_product_contexts": {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l0", "bond_l0"],
            }
        },
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "compact_primary",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.35},
        },
        "recommended_result": {
            "allocation_name": "compact_primary",
            "success_probability": 0.67,
            "expected_annual_return": 0.056,
            "implied_required_annual_return": 0.06,
        },
        "all_results": [
            {
                "allocation_name": "compact_primary",
                "success_probability": 0.67,
                "expected_annual_return": 0.056,
                "implied_required_annual_return": 0.06,
            }
        ],
        "frontier_analysis": {
            "recommended": {"allocation_name": "compact_primary"},
            "highest_probability": {"allocation_name": "compact_primary"},
            "target_return_priority": {"allocation_name": "compact_primary"},
            "scenario_status": {},
        },
        "solver_notes": [],
    }

    monkeypatch.setattr(
        orchestrator_engine,
        "_build_solver_candidate_product_contexts",
        lambda **_kwargs: {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l0", "bond_l0"],
            }
        },
    )
    monkeypatch.setattr(
        orchestrator_engine,
        "_rerank_goal_solver_output_with_v14_primary",
        lambda **_kwargs: (
            {
                "recommended_allocation": {
                    "name": "compact_primary",
                    "weights": {"equity_cn": 0.55, "bond_cn": 0.35},
                },
                "recommended_result": {
                    "allocation_name": "compact_primary",
                    "success_probability": 0.67,
                    "expected_annual_return": 0.056,
                    "implied_required_annual_return": 0.06,
                },
                "all_results": [
                    {
                        "allocation_name": "compact_primary",
                        "success_probability": 0.67,
                        "expected_annual_return": 0.056,
                        "implied_required_annual_return": 0.06,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {"allocation_name": "compact_primary"},
                    "highest_probability": {"allocation_name": "compact_primary"},
                    "target_return_priority": {"allocation_name": "compact_primary"},
                    "scenario_status": {},
                },
            },
            {"evidence_bundle_ref": "evidence://contract/compact_primary"},
            _probability_result(success_probability=0.67, cagr_p50=0.056, terminal_value_mean=120000.0),
        ),
    )

    updated_output, recommendation_expansion = _apply_progressive_recommendation_expansion(
        run_id="contract_progressive_no_delta",
        envelope={"search_expansion_level": "L1_expanded", "why_this_level_was_run": "user_requested_deeper_search"},
        snapshot_bundle=None,
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
        formal_path_required=False,
        execution_policy="formal_estimation_allowed",
    )

    expansion = updated_output["frontier_diagnostics"]["recommendation_expansion"]

    assert recommendation_expansion["requested_search_expansion_level"] == "L1_expanded"
    assert recommendation_expansion["why_search_stopped"] == "no_new_products_found_at_requested_level"
    assert recommendation_expansion["new_product_ids_added"] == []
    assert recommendation_expansion["products_removed"] == []
    assert recommendation_expansion["expanded_alternatives"] == []
    assert expansion["why_search_stopped"] == "no_new_products_found_at_requested_level"
    assert expansion["new_product_ids_added"] == []
    assert expansion["products_removed"] == []
    assert expansion["expanded_alternatives"] == []


@pytest.mark.contract
def test_progressive_recommendation_expansion_does_not_collapse_mixed_delta_requested_level(
    monkeypatch,
):
    goal_solver_input = {
        "candidate_allocations": [
            {"name": "compact_primary", "weights": {"equity_cn": 0.55, "bond_cn": 0.35}},
            {"name": "higher_success_alt", "weights": {"equity_cn": 0.60, "bond_cn": 0.25}},
        ],
        "candidate_product_contexts": {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l0", "bond_l0"],
            },
            "higher_success_alt": {
                "allocation_name": "higher_success_alt",
                "selected_product_ids": ["equity_l1", "bond_l0"],
            },
        },
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "compact_primary",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.35},
        },
        "recommended_result": {
            "allocation_name": "compact_primary",
            "success_probability": 0.67,
            "expected_annual_return": 0.056,
            "implied_required_annual_return": 0.06,
        },
        "all_results": [
            {
                "allocation_name": "compact_primary",
                "success_probability": 0.67,
                "expected_annual_return": 0.056,
                "implied_required_annual_return": 0.06,
            },
            {
                "allocation_name": "higher_success_alt",
                "success_probability": 0.72,
                "expected_annual_return": 0.071,
                "implied_required_annual_return": 0.06,
            },
        ],
        "frontier_analysis": {
            "recommended": {"allocation_name": "compact_primary"},
            "highest_probability": {"allocation_name": "higher_success_alt"},
            "target_return_priority": {"allocation_name": "compact_primary"},
            "scenario_status": {},
        },
        "solver_notes": [],
    }

    monkeypatch.setattr(
        orchestrator_engine,
        "_build_solver_candidate_product_contexts",
        lambda **_kwargs: {
            "compact_primary": {
                "allocation_name": "compact_primary",
                "selected_product_ids": ["equity_l0", "bond_l0"],
            },
            "higher_success_alt": {
                "allocation_name": "higher_success_alt",
                "selected_product_ids": ["equity_l1", "bond_l0"],
            },
        },
    )
    monkeypatch.setattr(
        orchestrator_engine,
        "_rerank_goal_solver_output_with_v14_primary",
        lambda **_kwargs: (
            {
                "recommended_allocation": {
                    "name": "compact_primary",
                    "weights": {"equity_cn": 0.55, "bond_cn": 0.35},
                },
                "recommended_result": {
                    "allocation_name": "compact_primary",
                    "success_probability": 0.67,
                    "expected_annual_return": 0.056,
                    "implied_required_annual_return": 0.06,
                },
                "all_results": [
                    {
                        "allocation_name": "compact_primary",
                        "success_probability": 0.67,
                        "expected_annual_return": 0.056,
                        "implied_required_annual_return": 0.06,
                    },
                    {
                        "allocation_name": "higher_success_alt",
                        "success_probability": 0.72,
                        "expected_annual_return": 0.071,
                        "implied_required_annual_return": 0.06,
                    },
                ],
                "frontier_analysis": {
                    "recommended": {"allocation_name": "compact_primary"},
                    "highest_probability": {"allocation_name": "higher_success_alt"},
                    "target_return_priority": {"allocation_name": "compact_primary"},
                    "scenario_status": {},
                },
            },
            {"evidence_bundle_ref": "evidence://contract/compact_primary"},
            _probability_result(success_probability=0.67, cagr_p50=0.056, terminal_value_mean=120000.0),
        ),
    )

    updated_output, recommendation_expansion = _apply_progressive_recommendation_expansion(
        run_id="contract_progressive_mixed_delta",
        envelope={"search_expansion_level": "L1_expanded", "why_this_level_was_run": "user_requested_deeper_search"},
        snapshot_bundle=None,
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
        formal_path_required=False,
        execution_policy="formal_estimation_allowed",
    )

    expansion = updated_output["frontier_diagnostics"]["recommendation_expansion"]

    assert recommendation_expansion["why_search_stopped"] != "no_new_products_found_at_requested_level"
    assert recommendation_expansion["expanded_alternatives"]
    assert recommendation_expansion["new_product_ids_added"] == ["equity_l1"]
    assert recommendation_expansion["products_removed"] == ["equity_l0"]
    assert expansion["why_search_stopped"] != "no_new_products_found_at_requested_level"
    assert expansion["expanded_alternatives"]
    assert expansion["new_product_ids_added"] == ["equity_l1"]
    assert expansion["products_removed"] == ["equity_l0"]
    assert expansion["alternatives"][0]["recommended_result"]["allocation_name"] == "compact_primary"
    assert expansion["alternatives"][0]["new_product_ids_added"] == []
    assert expansion["alternatives"][1]["recommended_result"]["allocation_name"] == "higher_success_alt"
    assert expansion["alternatives"][1]["new_product_ids_added"] == ["equity_l1"]


@pytest.mark.contract
def test_progressive_recommendation_expansion_keeps_closest_target_primary_and_highest_success_as_alternative_when_no_candidate_meets_return(
    monkeypatch,
):
    goal_solver_input = {
        "candidate_allocations": [
            {"name": "closest_to_target", "weights": {"equity_cn": 0.40, "bond_cn": 0.35, "gold": 0.15, "satellite": 0.10}},
            {"name": "highest_success", "weights": {"equity_cn": 0.60, "bond_cn": 0.20, "gold": 0.10, "satellite": 0.10}},
        ],
        "candidate_product_contexts": {
            "closest_to_target": {
                "allocation_name": "closest_to_target",
                "selected_product_ids": ["closest_l0"],
                "product_simulation_input": {"coverage_summary": {}},
            },
            "highest_success": {
                "allocation_name": "highest_success",
                "selected_product_ids": ["highest_l0"],
                "product_simulation_input": {"coverage_summary": {}},
            },
        },
    }
    goal_solver_output = {
        "recommended_allocation": {
            "name": "closest_to_target",
            "weights": {"equity_cn": 0.40, "bond_cn": 0.35, "gold": 0.15, "satellite": 0.10},
        },
        "recommended_result": {
            "allocation_name": "closest_to_target",
            "implied_required_annual_return": 0.06,
            "success_probability": 0.66,
            "expected_annual_return": 0.057,
        },
        "all_results": [
            {
                "allocation_name": "closest_to_target",
                "implied_required_annual_return": 0.06,
                "success_probability": 0.66,
                "expected_annual_return": 0.057,
                "max_drawdown_p95": 0.06,
                "terminal_value_p50": 120000.0,
            },
            {
                "allocation_name": "highest_success",
                "implied_required_annual_return": 0.06,
                "success_probability": 0.78,
                "expected_annual_return": 0.075,
                "max_drawdown_p95": 0.04,
                "terminal_value_p50": 126000.0,
            },
        ],
        "frontier_analysis": {
            "recommended": {"allocation_name": "closest_to_target"},
            "highest_probability": {"allocation_name": "highest_success"},
            "target_return_priority": {"allocation_name": "closest_to_target"},
            "scenario_status": {},
        },
        "solver_notes": [],
    }

    monkeypatch.setattr(
        orchestrator_engine,
        "_build_solver_candidate_product_contexts",
        lambda **_kwargs: {
            "closest_to_target": {
                "allocation_name": "closest_to_target",
                "selected_product_ids": ["closest_l1"],
                "product_simulation_input": {"coverage_summary": {}},
            },
            "highest_success": {
                "allocation_name": "highest_success",
                "selected_product_ids": ["highest_l1"],
                "product_simulation_input": {"coverage_summary": {}},
            },
        },
    )

    def _fake_build(**kwargs):  # type: ignore[no-untyped-def]
        allocation_name = kwargs.get("allocation_name")
        return ({"evidence_bundle_ref": f"evidence://contract/{allocation_name}"}, {})

    def _fake_probability_engine(sim_input):  # type: ignore[no-untyped-def]
        if str(sim_input["evidence_bundle_ref"]).endswith("/closest_to_target"):
            return _probability_result(success_probability=0.68, cagr_p50=0.058, terminal_value_mean=120500.0)
        return _probability_result(success_probability=0.80, cagr_p50=0.076, terminal_value_mean=126500.0)

    monkeypatch.setattr(orchestrator_engine, "_build_probability_engine_run_input", _fake_build)
    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _fake_probability_engine)

    updated_output, recommendation_expansion = _apply_progressive_recommendation_expansion(
        run_id="contract_progressive_no_target_match",
        envelope={"search_expansion_level": "L1_expanded", "why_this_level_was_run": "user_requested_deeper_search"},
        snapshot_bundle=None,
        calibration_result={},
        goal_solver_input=goal_solver_input,
        goal_solver_output=goal_solver_output,
        formal_path_required=False,
        execution_policy="formal_estimation_allowed",
    )

    expansion = updated_output["frontier_diagnostics"]["recommendation_expansion"]
    alternative_names = [item["recommended_result"]["allocation_name"] for item in expansion["alternatives"]]
    highest_success_alternative = expansion["alternatives"][1]

    assert updated_output["recommended_result"]["allocation_name"] == "closest_to_target"
    assert recommendation_expansion["requested_search_expansion_level"] == "L1_expanded"
    assert alternative_names == ["closest_to_target", "highest_success"]
    assert highest_success_alternative["difference_basis"]["comparison_scope"] == "cross_allocation_vs_compact_primary"
    assert highest_success_alternative["difference_basis"]["reference_allocation_name"] == "closest_to_target"
    assert highest_success_alternative["new_product_ids_added"] == ["highest_l1"]
    assert highest_success_alternative["products_removed"] == ["closest_l0"]


@pytest.mark.contract
def test_build_persistence_plan_carries_execution_plan_summary_recommendation_expansion_fields():
    execution_plan = {
        "plan_id": "plan_progressive",
        "plan_version": 1,
        "source_run_id": "run_progressive",
        "source_allocation_id": "compact_primary",
        "status": "draft",
        "search_expansion_level": "L0_compact",
        "recommendation_expansion": {
            "requested_search_expansion_level": "L1_expanded",
            "why_this_level_was_run": "user_requested_deeper_search",
            "why_search_stopped": "level_limit_requested_search_expansion_reached",
            "new_product_ids_added": ["equity_l1"],
            "products_removed": ["equity_l0"],
            "expanded_alternatives": [
                {
                    "allocation_name": "compact_primary",
                    "difference_basis": {
                        "comparison_scope": "same_allocation_search_expansion",
                        "reference_allocation_name": "compact_primary",
                        "reference_search_expansion_level": "L0_compact",
                    },
                }
            ],
        },
        "items": [],
    }

    persistence_plan = _build_persistence_plan(
        run_id="run_progressive",
        requested_workflow=WorkflowType.ONBOARDING,
        workflow_type=WorkflowType.ONBOARDING,
        status=WorkflowStatus.COMPLETED,
        bundle_id="bundle_progressive",
        calibration_id="calibration_progressive",
        solver_snapshot_id="snapshot_progressive",
        snapshot_bundle={},
        calibration_result={},
        goal_solver_output={},
        runtime_result=None,
        execution_plan=execution_plan,
        decision_card={},
        workflow_decision=orchestrator_engine.WorkflowDecision(
            requested_workflow_type=WorkflowType.ONBOARDING,
            selected_workflow_type=WorkflowType.ONBOARDING,
        ),
        runtime_restriction=orchestrator_engine.RuntimeRestriction(),
        blocking_reasons=[],
        degraded_notes=[],
        escalation_reasons=[],
        control_flags={"manual_override_requested": False, "manual_review_requested": False},
    )

    persisted_summary = persistence_plan.artifact_records["execution_plan"]["summary"]

    assert persisted_summary["search_expansion_level"] == "L0_compact"
    assert persisted_summary["recommendation_expansion"]["requested_search_expansion_level"] == "L1_expanded"
    assert persisted_summary["recommendation_expansion"]["expanded_alternatives"][0]["difference_basis"][
        "comparison_scope"
    ] == "same_allocation_search_expansion"
