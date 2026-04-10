from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import orchestrator.engine as orchestrator_engine
from frontdesk.service import _frontdesk_summary
from orchestrator.engine import run_orchestrator
from probability_engine.contracts import (
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
    assert result["disclosure_decision"]["confidence_level"] == "medium"
    assert result["evidence_bundle"]["run_outcome_status"] == "completed"
    assert result["evidence_bundle"]["resolved_result_category"] == "formal_estimated_result"


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


@pytest.mark.parametrize(
    ("legacy_status", "expected_top_level_status"),
    [
        (RunOutcomeStatus.BLOCKED, "blocked"),
        (RunOutcomeStatus.UNAVAILABLE, "unavailable"),
    ],
)
def test_orchestrator_keeps_legacy_blocked_or_unavailable_outcome_even_with_probability_overlay(
    monkeypatch,
    legacy_status,
    expected_top_level_status: str,
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
        trigger={"workflow_type": "onboarding", "run_id": f"v14_contract_{expected_top_level_status}"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id=f"v14_contract_{expected_top_level_status}"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == expected_top_level_status
    assert result["resolved_result_category"] is None


def test_orchestrator_keeps_legacy_degraded_outcome_even_when_probability_engine_succeeds(monkeypatch) -> None:
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
    monkeypatch.setattr(orchestrator_engine, "_gate1_run_outcome_status", lambda **kwargs: RunOutcomeStatus.DEGRADED)
    monkeypatch.setattr(
        orchestrator_engine,
        "_gate1_resolved_result_category",
        lambda **kwargs: "degraded_formal_result",
    )

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "v14_contract_degraded"},
        raw_inputs=_formal_onboarding_raw_inputs(account_profile_id="v14_contract_degraded"),
    ).to_dict()

    assert result["probability_engine_result"] is not None
    assert result["run_outcome_status"] == "degraded"
    assert result["resolved_result_category"] == "degraded_formal_result"


def test_formal_daily_builder_uses_goal_horizon_and_proxy_confidence_for_smoke_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(sim_input: dict[str, object]) -> ProbabilityEngineRunResult:
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
    assert {product["mapping_confidence"] for product in captured["products"]} == {"low"}
    contribution_schedule = list(captured["contribution_schedule"])
    assert len(contribution_schedule) == 36
    assert contribution_schedule[-1]["date"] == captured["trading_calendar"][-1]


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

    assert summary["run_outcome_status"] == "completed"
    assert summary["resolved_result_category"] == "formal_estimated_result"
    assert summary["disclosure_decision"]["confidence_level"] == "medium"
    assert summary["evidence_bundle"]["run_outcome_status"] == "completed"
    assert summary["monthly_fallback_used"] is False
    assert summary["bucket_fallback_used"] is False
