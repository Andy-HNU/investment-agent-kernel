from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import orchestrator.engine as orchestrator_engine
from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType
from frontdesk.service import _frontdesk_summary
from orchestrator.engine import run_orchestrator
from probability_engine.contracts import (
    FailureArtifact,
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
)
from shared.audit import RunOutcomeStatus
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.formal_snapshot_helpers import build_formal_snapshot_payload


def _profile(*, account_profile_id: str = "v14_formal_daily_contract") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="FormalDailyContract",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )


def _allocation_input(goal_solver_input: dict[str, object]) -> dict[str, object]:
    goal = dict(goal_solver_input["goal"])
    constraints = dict(goal_solver_input["constraints"])
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input["account_profile_id"],
            "risk_preference": goal["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal,
        "cashflow_plan": dict(goal_solver_input["cashflow_plan"]),
        "constraints": constraints,
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


def _formal_onboarding_raw_inputs(*, account_profile_id: str) -> dict[str, object]:
    profile = _profile(account_profile_id=account_profile_id)
    bundle = build_user_onboarding_inputs(profile, as_of="2026-04-07T00:00:00Z")
    snapshot = build_formal_snapshot_payload(profile, as_of="2026-04-07T00:00:00Z")
    raw_inputs = deepcopy(bundle.raw_inputs)
    raw_inputs["market_raw"] = deepcopy(snapshot["market_raw"])
    raw_inputs["account_raw"] = deepcopy(snapshot["account_raw"])
    raw_inputs["behavior_raw"] = deepcopy(snapshot["behavior_raw"])
    raw_inputs["live_portfolio"] = deepcopy(snapshot["live_portfolio"])
    raw_inputs["input_provenance"] = deepcopy(snapshot["input_provenance"])
    raw_inputs["snapshot_primary_formal_path"] = True
    raw_inputs["formal_path_required"] = True
    raw_inputs["execution_policy"] = "formal_estimation_allowed"
    raw_inputs["allocation_engine_input"] = _allocation_input(raw_inputs["goal_solver_input"])
    return raw_inputs


def _probability_result(
    *,
    run_outcome_status: str,
    resolved_result_category: str,
    disclosure_level: str,
    confidence_level: str,
) -> ProbabilityEngineRunResult:
    primary = RecipeSimulationResult(
        recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
        role="primary",
        success_probability=0.62,
        success_probability_range=(0.58, 0.66),
        cagr_range=(0.04, 0.08),
        drawdown_range=(0.08, 0.16),
        sample_count=128,
        path_stats=PathStatsSummary(
            terminal_value_mean=121_000.0,
            terminal_value_p05=95_000.0,
            terminal_value_p50=119_000.0,
            terminal_value_p95=140_000.0,
            cagr_p05=0.03,
            cagr_p50=0.05,
            cagr_p95=0.07,
            max_drawdown_p05=0.05,
            max_drawdown_p50=0.10,
            max_drawdown_p95=0.16,
            success_count=79,
            path_count=128,
        ),
        calibration_link_ref="evidence://contract/v14",
    )
    current_market_pressure = {
        "scenario_kind": "current_market",
        "market_pressure_score": 43.0,
        "market_pressure_level": "L1_中性偏紧",
        "current_regime": "risk_off",
    }
    scenario_comparison = [
        {
            "scenario_kind": "historical_replay",
            "label": "历史回测",
            "pressure": None,
            "recipe_result": primary,
        },
        {
            "scenario_kind": "current_market",
            "label": "当前市场延续",
            "pressure": current_market_pressure,
            "recipe_result": primary,
        },
        {
            "scenario_kind": "deteriorated_mild",
            "label": "若市场轻度恶化",
            "pressure": {
                "scenario_kind": "deteriorated_mild",
                "market_pressure_score": 57.0,
                "market_pressure_level": "L2_风险偏高",
                "current_regime": "risk_off",
            },
            "recipe_result": primary,
        },
        {
            "scenario_kind": "deteriorated_moderate",
            "label": "若市场中度恶化",
            "pressure": {
                "scenario_kind": "deteriorated_moderate",
                "market_pressure_score": 68.0,
                "market_pressure_level": "L2_风险偏高",
                "current_regime": "stress",
            },
            "recipe_result": primary,
        },
        {
            "scenario_kind": "deteriorated_severe",
            "label": "若市场重度恶化",
            "pressure": {
                "scenario_kind": "deteriorated_severe",
                "market_pressure_score": 87.0,
                "market_pressure_level": "L3_高压",
                "current_regime": "stress",
            },
            "recipe_result": primary,
        },
    ]
    return ProbabilityEngineRunResult(
        run_outcome_status=run_outcome_status,
        resolved_result_category=resolved_result_category,
        output=ProbabilityEngineOutput(
            primary_result=primary,
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=ProbabilityDisclosurePayload(
                published_point=0.62 if disclosure_level == "point_and_range" else None,
                published_range=(0.58, 0.66),
                disclosure_level=disclosure_level,
                confidence_level=confidence_level,
                challenger_gap=None,
                stress_gap=None,
                gap_total=None,
                widening_method="contract_fixture",
            ),
            evidence_refs=["evidence://contract/v14"],
            current_market_pressure=current_market_pressure,
            scenario_comparison=scenario_comparison,
        ),
        failure_artifact=None,
    )


def test_orchestrator_top_level_surface_tracks_bridged_probability_result_when_eligible(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_estimated_result",
            disclosure_level="range_only",
            confidence_level="medium",
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.COMPLETED)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_eligible"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_eligible"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "completed"
    assert result["resolved_result_category"] == "formal_estimated_result"
    assert set(result["bucket_construction_explanations"]) >= {"equity_cn", "bond_cn", "gold", "satellite"}
    assert result["product_explanations"]
    assert result["product_group_explanations"]
    assert result["disclosure_decision"]["confidence_level"] == "medium"
    assert result["evidence_bundle"]["run_outcome_status"] == "completed"
    assert result["evidence_bundle"]["resolved_result_category"] == "formal_estimated_result"
    assert result["runtime_telemetry"]["path_horizon_days"] > 20
    assert result["runtime_telemetry"]["path_count_primary"] == 128
    assert result["runtime_telemetry"]["path_count_challenger"] == 0
    assert result["runtime_telemetry"]["path_count_stress"] == 0


def test_probability_truth_view_prefers_probability_engine_result_when_formal_semantics_are_degraded() -> None:
    truth_view = orchestrator_engine._probability_truth_view(
        probability_engine_result={
            "run_outcome_status": "degraded",
            "resolved_result_category": "degraded_formal_result",
        },
        run_outcome_status="degraded",
        resolved_result_category="degraded_formal_result",
        disclosure_decision={
            "result_category": "degraded_formal_result",
            "disclosure_level": "range_only",
            "confidence_level": "medium",
        },
        evidence_bundle={
            "monthly_fallback_used": False,
            "bucket_fallback_used": False,
            "coverage_summary": {
                "selected_product_count": 3,
                "independent_weight_adjusted_coverage": 1.0,
                "independent_horizon_complete_coverage": 1.0,
                "distribution_ready_coverage": 1.0,
            },
        },
    )

    assert truth_view["product_probability_method"] == "product_estimated_path"


def test_orchestrator_marks_formal_surface_unavailable_when_probability_engine_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="probability_engine",
                failure_code="primary_daily_engine_failed",
                message="synthetic contract failure",
                diagnostic_refs=["diag://probability_engine_failed"],
                trustworthy_partial_diagnostics=False,
            ),
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.COMPLETED)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_failure_bridge"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_failure_bridge"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "unavailable"
    assert result["resolved_result_category"] is None
    assert result["evidence_bundle"]["run_outcome_status"] == "unavailable"


def test_orchestrator_marks_degraded_gate1_surface_unavailable_when_probability_engine_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="probability_engine",
                failure_code="primary_daily_engine_failed",
                message="synthetic degraded contract failure",
                diagnostic_refs=["diag://probability_engine_failed"],
                trustworthy_partial_diagnostics=False,
            ),
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.DEGRADED)
    monkeypatch.setattr(orchestrator_engine, "_gate1_resolved_result_category", lambda **kwargs: "degraded_formal_result")

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_failure_bridge_degraded"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_failure_bridge_degraded"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "unavailable"
    assert result["resolved_result_category"] is None
    assert result["evidence_bundle"]["run_outcome_status"] == "unavailable"


def test_orchestrator_maps_internal_formal_strict_result_to_v13_independent_surface(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_strict_result",
            disclosure_level="point_and_range",
            confidence_level="medium",
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.COMPLETED)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_strict"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_strict"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "completed"
    assert result["resolved_result_category"] == "formal_independent_result"
    assert result["evidence_bundle"]["resolved_result_category"] == "formal_independent_result"
    assert result["evidence_bundle"]["simulation_mode"] == "primary_daily_factor_garch_dcc_jump_regime_v1"


def test_orchestrator_uses_product_level_factor_betas_from_snapshot_mapping_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}
    raw_inputs = _formal_onboarding_raw_inputs(account_profile_id="v14_contract_mapping_payload")
    mapping_products = {
        str(item["product_id"]): dict(item)
        for item in list(raw_inputs["market_raw"]["probability_engine"]["factor_mapping"]["products"])
    }

    def _capture(sim_input: dict[str, object]) -> ProbabilityEngineRunResult:
        incoming_products = list(sim_input.get("products") or [])
        captured_products = list(captured.get("products") or [])
        if not captured or len(incoming_products) > len(captured_products):
            captured.clear()
            captured.update(deepcopy(sim_input))
        return _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_strict_result",
            disclosure_level="point_and_range",
            confidence_level="high",
        )

    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _capture)
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.COMPLETED)

    run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_mapping_payload"},
        raw_inputs=raw_inputs,
    ).to_dict()

    products = {
        str(item["product_id"]): dict(item)
        for item in list(captured.get("products") or [])
    }
    assert products
    for product_id, expected_payload in mapping_products.items():
        assert products[product_id]["factor_betas"] == expected_payload["factor_betas"]


def test_orchestrator_exposes_probability_engine_result_and_decision_card_uses_it_for_formal_section(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_strict_result",
            disclosure_level="point_and_range",
            confidence_level="high",
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.COMPLETED)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_truth_view_contract"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_truth_view_contract"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "completed"
    assert result["resolved_result_category"] == "formal_independent_result"
    assert result["disclosure_decision"]["confidence_level"] == "high"
    assert result["probability_truth_view"]["run_outcome_status"] == "completed"
    assert result["probability_truth_view"]["resolved_result_category"] == "formal_independent_result"
    assert result["probability_truth_view"]["product_probability_method"] == "product_independent_path"
    assert result["probability_truth_view"]["disclosure_decision"]["confidence_level"] == "high"


def test_decision_card_prefers_probability_engine_result_for_formal_probability_fields() -> None:
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="v14_truth_view_card",
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "legacy_proxy_candidate",
                    "display_name": "旧代理方案",
                    "success_probability": 0.91,
                    "bucket_success_probability": 0.91,
                    "product_proxy_adjusted_success_probability": 0.91,
                    "product_probability_method": "product_proxy_path",
                    "expected_annual_return": 0.11,
                    "risk_summary": {"max_drawdown_90pct": 0.30, "shortfall_probability": 0.12},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "legacy_proxy_candidate",
                        "display_name": "旧代理方案",
                        "success_probability": 0.91,
                        "bucket_success_probability": 0.91,
                        "product_proxy_adjusted_success_probability": 0.91,
                        "product_probability_method": "product_proxy_path",
                        "expected_annual_return": 0.11,
                        "risk_summary": {"max_drawdown_90pct": 0.30, "shortfall_probability": 0.12},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "legacy_proxy_candidate",
                        "display_name": "旧代理方案",
                        "success_probability": 0.91,
                        "product_probability_method": "product_proxy_path",
                        "expected_annual_return": 0.11,
                        "max_drawdown_90pct": 0.30,
                        "why_selected": "legacy proxy path",
                    }
                },
                "frontier_diagnostics": {},
            },
            probability_engine_result=_probability_result(
                run_outcome_status="success",
                resolved_result_category="formal_strict_result",
                disclosure_level="point_and_range",
                confidence_level="high",
            ),
            run_outcome_status="completed",
            resolved_result_category="formal_independent_result",
            probability_truth_view={
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "product_probability_method": "product_independent_path",
                "disclosure_decision": {
                    "disclosure_level": "point_and_range",
                    "confidence_level": "high",
                },
            },
            disclosure_decision={
                "disclosure_level": "point_and_range",
                "confidence_level": "high",
            },
            evidence_bundle={
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "monthly_fallback_used": False,
                "bucket_fallback_used": False,
            },
        )
    )

    probability_explanation = dict(card.get("probability_explanation") or {})
    key_metrics = dict(card.get("key_metrics") or {})
    assert key_metrics["success_probability"] == "62.00%"
    assert key_metrics["success_probability_range"] == "58.00% ~ 66.00%"
    assert probability_explanation["recommended_success_probability"] == "62.00%"
    assert probability_explanation["recommended_expected_annual_return"] == "5.00%"
    assert probability_explanation["product_probability_method"] == "product_independent_path"
    assert key_metrics["product_probability_method"] == "product_independent_path"
    assert card["current_market_pressure"]["market_pressure_level"] == "L1_中性偏紧"
    assert [item["label"] for item in card["scenario_ladder"]] == [
        "历史回测",
        "当前市场延续",
        "若市场轻度恶化",
        "若市场中度恶化",
        "若市场重度恶化",
    ]


def test_quarterly_review_card_surfaces_probability_engine_pressure_ladder() -> None:
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.QUARTERLY_REVIEW,
            workflow_type="quarterly",
            run_id="v14_quarterly_pressure_ladder",
            goal_solver_output={
                "recommended_result": {
                    "success_probability": 0.71,
                    "risk_summary": {"max_drawdown_90pct": 0.18},
                },
                "solver_notes": ["baseline refreshed"],
            },
            runtime_result={
                "candidate_poverty": False,
                "ev_report": {
                    "ranked_actions": [
                        {
                            "action": {"type": "observe"},
                            "score": {"total": 0.01},
                            "rank": 1,
                            "is_recommended": True,
                            "recommendation_reason": "observe while validating new baseline",
                        }
                    ],
                    "recommended_action": {"type": "observe"},
                    "confidence_flag": "medium",
                    "confidence_reason": "quarterly review context",
                    "goal_solver_baseline": 0.69,
                    "goal_solver_after_recommended": 0.70,
                },
            },
            probability_engine_result=_probability_result(
                run_outcome_status="success",
                resolved_result_category="formal_strict_result",
                disclosure_level="point_and_range",
                confidence_level="high",
            ),
            run_outcome_status="completed",
            resolved_result_category="formal_independent_result",
            probability_truth_view={
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "product_probability_method": "product_independent_path",
                "disclosure_decision": {
                    "disclosure_level": "point_and_range",
                    "confidence_level": "high",
                },
            },
            disclosure_decision={
                "disclosure_level": "point_and_range",
                "confidence_level": "high",
            },
            evidence_bundle={
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "monthly_fallback_used": False,
                "bucket_fallback_used": False,
            },
        )
    )

    assert card["current_market_pressure"]["market_pressure_level"] == "L1_中性偏紧"
    assert [item["label"] for item in card["scenario_ladder"]] == [
        "历史回测",
        "当前市场延续",
        "若市场轻度恶化",
        "若市场中度恶化",
        "若市场重度恶化",
    ]
    assert card["probability_explanation"]["scenario_ladder"][1]["label"] == "当前市场延续"


def test_frontdesk_summary_prefers_top_level_probability_fields_over_decision_card_fallback() -> None:
    summary = _frontdesk_summary(
        account_profile_id="v14_truth_view_frontdesk",
        display_name="TruthView",
        db_path=Path("/tmp/frontdesk_truth_view.sqlite"),
        result_payload={
            "run_id": "run_truth_view_frontdesk",
            "workflow_type": "onboarding",
            "status": "completed",
            "run_outcome_status": "completed",
            "resolved_result_category": "formal_independent_result",
            "disclosure_decision": {
                "disclosure_level": "point_and_range",
                "confidence_level": "high",
            },
            "probability_truth_view": {
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "product_probability_method": "product_independent_path",
                "disclosure_decision": {
                    "disclosure_level": "point_and_range",
                    "confidence_level": "high",
                },
                "formal_path_visibility": {
                    "status": "completed",
                    "fallback_used": False,
                },
            },
            "decision_card": {
                "run_outcome_status": "completed",
                "resolved_result_category": "formal_independent_result",
                "probability_explanation": {
                    "product_probability_method": "product_proxy_path",
                },
                "key_metrics": {
                    "product_probability_method": "product_proxy_path",
                },
            },
            "probability_engine_result": _probability_result(
                run_outcome_status="success",
                resolved_result_category="formal_strict_result",
                disclosure_level="point_and_range",
                confidence_level="high",
            ).to_dict(),
        },
    )

    assert summary["product_probability_method"] == "product_independent_path"
    assert summary["run_outcome_status"] == "completed"
    assert summary["resolved_result_category"] == "formal_independent_result"


@pytest.mark.parametrize("legacy_status", [RunOutcomeStatus.BLOCKED, RunOutcomeStatus.UNAVAILABLE, RunOutcomeStatus.DEGRADED])
def test_orchestrator_prefers_probability_engine_result_when_gate1_is_blocked_unavailable_or_degraded(
    monkeypatch,
    legacy_status,
) -> None:
    monkeypatch.setattr(
        orchestrator_engine,
        "run_probability_engine",
        lambda sim_input: _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_estimated_result",
            disclosure_level="range_only",
            confidence_level="medium",
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: legacy_status)
    monkeypatch.setattr(orchestrator_engine, "_gate1_resolved_result_category", lambda **kwargs: None)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": f"v14_contract_{legacy_status.value}"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id=f"v14_contract_{legacy_status.value}"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "completed"
    assert result["resolved_result_category"] == "formal_estimated_result"
    assert result["disclosure_decision"]["confidence_level"] == "medium"
    assert result["evidence_bundle"]["run_outcome_status"] == "completed"


def test_formal_daily_builder_uses_product_level_factor_mapping_for_smoke_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(sim_input: dict[str, object]) -> ProbabilityEngineRunResult:
        incoming_products = list(sim_input.get("products") or [])
        captured_products = list(captured.get("products") or [])
        if not captured or len(incoming_products) > len(captured_products):
            captured.clear()
            captured.update(deepcopy(sim_input))
        return _probability_result(
            run_outcome_status="degraded",
            resolved_result_category="degraded_formal_result",
            disclosure_level="range_only",
            confidence_level="low",
        )

    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _capture)

    run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_builder"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_builder"),
    )

    assert captured["path_horizon_days"] > 20
    assert captured["success_event_spec"]["horizon_days"] == captured["path_horizon_days"]
    assert captured["success_event_spec"]["horizon_months"] == 36
    assert {product["factor_mapping_source"] for product in captured["products"]} == {"blended"}
    assert {product["mapping_confidence"] for product in captured["products"]} == {"high"}
    assert all(
        any(entry.get("source") == "returns" for entry in product["factor_mapping_evidence"])
        for product in captured["products"]
    )
    expected_factor_betas = {
        product["product_id"]: dict(product["factor_betas"])
        for product in build_formal_snapshot_payload(_profile(account_profile_id="v14_contract_builder"), as_of="2026-04-07T00:00:00Z")[
            "market_raw"
        ]["probability_engine"]["factor_mapping"]["products"]
    }
    assert captured["products"], "expected formal products to be captured"
    for product in captured["products"]:
        assert product["factor_betas"] == expected_factor_betas[product["product_id"]]
    assert "path_count" not in captured["recipes"][0]
    contribution_schedule = list(captured["contribution_schedule"])
    assert len(contribution_schedule) == 36
    assert contribution_schedule[-1]["date"] == captured["trading_calendar"][-1]


def test_decision_card_uses_probability_engine_result_primary_result_for_formal_section_when_present() -> None:
    goal_output = {
        "goal_description": "legacy goal solver output",
        "recommended_result": {
            "allocation_name": "legacy_candidate",
            "success_probability": 0.91,
            "expected_annual_return": 0.11,
            "product_probability_method": "product_proxy_adjustment_estimate",
            "risk_summary": {
                "max_drawdown_90pct": 0.14,
                "shortfall_probability": 0.08,
            },
        },
        "candidate_menu": [
            {
                "allocation_name": "legacy_candidate",
                "display_name": "Legacy Candidate",
                "success_probability": 0.91,
                "expected_annual_return": 0.11,
                "product_probability_method": "product_proxy_adjustment_estimate",
                "risk_summary": {
                    "max_drawdown_90pct": 0.14,
                    "shortfall_probability": 0.08,
                },
            },
            {
                "allocation_name": "secondary_candidate",
                "display_name": "Secondary Candidate",
                "success_probability": 0.84,
                "expected_annual_return": 0.09,
                "product_probability_method": "product_proxy_adjustment_estimate",
                "risk_summary": {
                    "max_drawdown_90pct": 0.12,
                    "shortfall_probability": 0.06,
                },
            },
        ],
        "frontier_analysis": {
            "recommended": {
                "allocation_name": "legacy_candidate",
                "expected_annual_return": 0.11,
            }
        },
        "calibration_summary": {"calibration_quality": "strong"},
    }
    probability_result = _probability_result(
        run_outcome_status="success",
        resolved_result_category="formal_estimated_result",
        disclosure_level="point_and_range",
        confidence_level="high",
    )
    probability_result = probability_result.__class__(
        run_outcome_status=probability_result.run_outcome_status,
        resolved_result_category=probability_result.resolved_result_category,
        output=probability_result.output.__class__(
            primary_result=probability_result.output.primary_result.__class__(
                recipe_name=probability_result.output.primary_result.recipe_name,
                role=probability_result.output.primary_result.role,
                success_probability=0.62,
                success_probability_range=(0.58, 0.66),
                cagr_range=(0.04, 0.08),
                drawdown_range=probability_result.output.primary_result.drawdown_range,
                sample_count=probability_result.output.primary_result.sample_count,
                path_stats=probability_result.output.primary_result.path_stats.__class__(
                    terminal_value_mean=probability_result.output.primary_result.path_stats.terminal_value_mean,
                    terminal_value_p05=probability_result.output.primary_result.path_stats.terminal_value_p05,
                    terminal_value_p50=probability_result.output.primary_result.path_stats.terminal_value_p50,
                    terminal_value_p95=probability_result.output.primary_result.path_stats.terminal_value_p95,
                    cagr_p05=0.04,
                    cagr_p50=0.05,
                    cagr_p95=0.08,
                    max_drawdown_p05=probability_result.output.primary_result.path_stats.max_drawdown_p05,
                    max_drawdown_p50=probability_result.output.primary_result.path_stats.max_drawdown_p50,
                    max_drawdown_p95=probability_result.output.primary_result.path_stats.max_drawdown_p95,
                    success_count=probability_result.output.primary_result.path_stats.success_count,
                    path_count=probability_result.output.primary_result.path_stats.path_count,
                ),
                calibration_link_ref=probability_result.output.primary_result.calibration_link_ref,
            ),
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=probability_result.output.probability_disclosure_payload.__class__(
                published_point=0.62,
                published_range=(0.58, 0.66),
                disclosure_level="point_and_range",
                confidence_level="high",
                challenger_gap=None,
                stress_gap=None,
                gap_total=None,
                widening_method="contract_fixture",
            ),
            evidence_refs=["evidence://contract/v14"],
        ),
        failure_artifact=None,
    )

    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="v14_decision_card_formal_truth",
            goal_solver_output=goal_output,
            goal_solver_input={
                "candidate_allocations": [
                    {"name": "legacy_candidate", "complexity_score": 0.2},
                    {"name": "secondary_candidate", "complexity_score": 0.6},
                ]
            },
            probability_engine_result=probability_result,
            disclosure_decision={"disclosure_level": "range_only", "confidence_level": "low"},
            execution_plan_summary={
                "formal_path_visibility": {"status": "formal", "execution_eligible": True},
                "product_universe_audit_summary": {"source_status": "observed", "data_status": "observed"},
                "valuation_audit_summary": {"source_status": "observed", "data_status": "observed"},
                "policy_news_audit_summary": {"source_status": "observed", "data_status": "observed"},
            },
        )
    )

    assert card["key_metrics"]["success_probability"] == "62.00%"
    assert card["key_metrics"]["success_probability_range"] == "58.00% ~ 66.00%"
    assert card["key_metrics"]["expected_annual_return"] == "5.00%"
    assert card["probability_explanation"]["recommended_success_probability"] == "62.00%"
    assert card["probability_explanation"]["recommended_expected_annual_return"] == "5.00%"
    assert card["candidate_options"][0]["success_probability"] == "91.00%"
    assert card["candidate_options"][0]["expected_annual_return"] == "11.00%"


def test_decision_card_ignores_goal_solver_probability_method_when_probability_engine_result_exists() -> None:
    goal_output = {
        "goal_description": "legacy goal solver output",
        "recommended_result": {
            "allocation_name": "legacy_candidate",
            "display_name": "Legacy Candidate",
            "success_probability": 0.91,
            "expected_annual_return": 0.11,
            "product_probability_method": "product_proxy_path",
            "risk_summary": {
                "max_drawdown_90pct": 0.14,
                "shortfall_probability": 0.08,
            },
        },
        "candidate_menu": [
            {
                "allocation_name": "legacy_candidate",
                "display_name": "Legacy Candidate",
                "success_probability": 0.91,
                "expected_annual_return": 0.11,
                "product_probability_method": "product_proxy_path",
                "risk_summary": {
                    "max_drawdown_90pct": 0.14,
                    "shortfall_probability": 0.08,
                },
            }
        ],
        "frontier_analysis": {
            "recommended": {
                "allocation_name": "legacy_candidate",
                "expected_annual_return": 0.11,
            }
        },
        "calibration_summary": {"calibration_quality": "strong"},
    }

    probability_result = _probability_result(
        run_outcome_status="success",
        resolved_result_category="formal_strict_result",
        disclosure_level="point_and_range",
        confidence_level="high",
    )

    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="v14_decision_card_engine_first",
            goal_solver_output=goal_output,
            goal_solver_input={
                "candidate_allocations": [
                    {"name": "legacy_candidate", "complexity_score": 0.2},
                ]
            },
            probability_engine_result=probability_result,
            disclosure_decision={"disclosure_level": "range_only", "confidence_level": "low"},
            execution_plan_summary={
                "formal_path_visibility": {"status": "formal", "execution_eligible": True},
                "product_universe_audit_summary": {"source_status": "observed", "data_status": "observed"},
                "valuation_audit_summary": {"source_status": "observed", "data_status": "observed"},
                "policy_news_audit_summary": {"source_status": "observed", "data_status": "observed"},
            },
        )
    )

    assert card["key_metrics"]["product_probability_method"] == "product_independent_path"
    assert card["probability_explanation"]["product_probability_method"] == "product_independent_path"
    assert card["key_metrics"]["success_probability"] == "62.00%"


def test_frontdesk_summary_consumes_orchestrator_surface_without_local_rebuild() -> None:
    result_payload = {
        "run_id": "v14_frontdesk_surface",
        "workflow_type": "onboarding",
        "status": "completed",
        "run_outcome_status": "completed",
        "resolved_result_category": "formal_estimated_result",
        "disclosure_decision": {
            "result_category": "formal_estimated_result",
            "disclosure_level": "range_only",
            "confidence_level": "medium",
        },
        "evidence_bundle": {
            "run_outcome_status": "completed",
            "resolved_result_category": "formal_estimated_result",
        },
        "decision_card": {
            "run_outcome_status": "degraded",
            "resolved_result_category": "degraded_formal_result",
        },
        "probability_engine_result": _probability_result(
            run_outcome_status="degraded",
            resolved_result_category="degraded_formal_result",
            disclosure_level="range_only",
            confidence_level="low",
        ).to_dict(),
    }

    summary = _frontdesk_summary(
        account_profile_id="v14_frontdesk_surface",
        display_name="FrontdeskSurface",
        result_payload=result_payload,
        db_path=Path("/tmp/frontdesk-surface.sqlite"),
        user_state={},
    )

    assert summary["run_outcome_status"] == "degraded"
    assert summary["resolved_result_category"] == "degraded_formal_result"
    assert summary["disclosure_decision"]["confidence_level"] == "low"
    assert summary["evidence_bundle"]["run_outcome_status"] == "completed"
    assert summary["monthly_fallback_used"] is False
    assert summary["bucket_fallback_used"] is False


def test_frontdesk_summary_prefers_probability_engine_result_and_top_level_payload_over_decision_card_fallbacks() -> None:
    result_payload = {
        "run_id": "v14_frontdesk_truth_surface",
        "workflow_type": "onboarding",
        "status": "completed",
        "goal_solver_output": {
            "recommended_result": {
                "product_probability_method": "product_proxy_adjustment_estimate",
            }
        },
        "decision_card": {
            "run_outcome_status": "degraded",
            "resolved_result_category": "degraded_formal_result",
            "disclosure_decision": {
                "result_category": "degraded_formal_result",
                "disclosure_level": "range_only",
                "confidence_level": "low",
            },
            "probability_explanation": {
                "product_probability_method": "decision_card_fallback_method",
            },
            "key_metrics": {
                "product_probability_method": "decision_card_fallback_method",
            },
        },
        "probability_engine_result": _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_estimated_result",
            disclosure_level="point_and_range",
            confidence_level="high",
        ).to_dict(),
    }

    summary = _frontdesk_summary(
        account_profile_id="v14_frontdesk_truth_surface",
        display_name="FrontdeskTruthSurface",
        result_payload=result_payload,
        db_path=Path("/tmp/frontdesk-truth-surface.sqlite"),
        user_state={},
    )

    assert summary["run_outcome_status"] == "completed"
    assert summary["resolved_result_category"] == "formal_estimated_result"
    assert summary["disclosure_decision"]["confidence_level"] == "high"
    assert summary["product_probability_method"] == "product_estimated_path"


def test_frontdesk_summary_ignores_goal_solver_probability_method_when_probability_engine_result_exists() -> None:
    result_payload = {
        "run_id": "v14_frontdesk_engine_first",
        "workflow_type": "onboarding",
        "status": "completed",
        "decision_card": {
            "run_outcome_status": "degraded",
            "resolved_result_category": "degraded_formal_result",
            "disclosure_decision": {
                "result_category": "degraded_formal_result",
                "disclosure_level": "range_only",
                "confidence_level": "low",
            },
            "probability_explanation": {
                "product_probability_method": "product_proxy_path",
            },
            "key_metrics": {
                "product_probability_method": "product_proxy_path",
            },
        },
        "goal_solver_output": {
            "recommended_result": {
                "product_probability_method": "product_proxy_adjustment_estimate",
            }
        },
        "probability_engine_result": _probability_result(
            run_outcome_status="success",
            resolved_result_category="formal_strict_result",
            disclosure_level="point_and_range",
            confidence_level="high",
        ).to_dict(),
    }

    summary = _frontdesk_summary(
        account_profile_id="v14_frontdesk_engine_first",
        display_name="FrontdeskEngineFirst",
        result_payload=result_payload,
        db_path=Path("/tmp/frontdesk-engine-first.sqlite"),
        user_state={},
    )

    assert summary["run_outcome_status"] == "completed"
    assert summary["resolved_result_category"] == "formal_independent_result"
    assert summary["product_probability_method"] == "product_independent_path"
    assert summary["disclosure_decision"]["confidence_level"] == "high"
