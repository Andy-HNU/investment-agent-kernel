from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import goal_solver.engine as goal_solver_engine
import orchestrator.engine as orchestrator_engine
from goal_solver.engine import run_goal_solver
from orchestrator.engine import run_orchestrator
from shared.audit import EvidenceBundle, RunOutcomeStatus, build_evidence_invariance_report


def _estimated_candidate_context() -> dict[str, object]:
    return {
        "allocation_name": "base_allocation",
        "product_probability_method": "product_proxy_adjustment_estimate",
        "selected_product_ids": ["eq_core"],
        "selected_proxy_refs": ["tinyshare://510300.SH"],
        "product_simulation_input": {
            "frequency": "daily",
            "simulation_method": "product_estimated_path",
            "coverage_summary": {
                "selected_product_count": 2,
                "observed_product_count": 1,
                "inferred_product_count": 1,
                "missing_product_count": 0,
                "weight_adjusted_coverage": 0.75,
                "distribution_ready_coverage": 0.60,
                "explanation_ready_coverage": 0.50,
            },
            "products": [],
        },
        "formal_path_preflight": {
            "formal_path_required": True,
            "execution_policy": "formal_estimation_allowed",
            "run_outcome_status": "degraded",
            "degradation_reasons": ["product_independent_coverage_incomplete"],
            "blocking_predicates": [],
            "estimation_basis": "proxy_path",
        },
    }


@pytest.mark.contract
def test_build_evidence_invariance_report_distinguishes_semantic_and_artifact_refs():
    baseline = EvidenceBundle(
        request_id="baseline_run",
        account_profile_id="acc001",
        as_of="2026-04-07T12:00:00Z",
        requested_result_category="formal_independent_result",
        resolved_result_category="formal_estimated_result",
        run_outcome_status=RunOutcomeStatus.DEGRADED,
        execution_policy="formal_estimation_allowed",
        disclosure_policy="FORMAL_STANDARD",
        simulation_mode="student_t",
        mapping_signature="mapping:v1",
        history_revision="history:v1",
        distribution_revision="distribution:v1",
        solver_revision="solver:v1",
        code_revision="code:v1",
        input_refs={"bundle_id": "bundle_001"},
        evidence_refs={"calibration_id": "cal_001"},
        coverage_summary={"independent_weight_adjusted_coverage": 0.75},
        disclosure_decision={"disclosure_level": "range_only"},
    )
    optimized = EvidenceBundle.from_any(
        {
            **baseline.to_dict(),
            "request_id": "optimized_run",
        }
    )
    report = build_evidence_invariance_report(
        baseline=baseline,
        optimized=optimized,
        baseline_run_ref="baseline_run",
        optimized_run_ref="optimized_run",
        artifact_refs={"storage_ref": "sqlite://optimized"},
    )

    assert report.verdict == "invariant"
    assert "resolved_result_category" in report.semantic_refs
    assert report.semantic_refs["resolved_result_category"] == "formal_estimated_result"
    assert report.artifact_refs == {"storage_ref": "sqlite://optimized"}
    assert "mapping_signature" in report.exact_match_fields
    assert report.drift_fields == []


@pytest.mark.contract
def test_run_orchestrator_emits_evidence_invariance_report_when_baseline_bundle_supplied(
    goal_solver_input_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _fake_run_monte_carlo(
        _weights: dict[str, float],
        _cashflow_schedule: list[float],
        _initial_value: float,
        _goal_amount: float,
        _market_state,
        _n_paths: int,
        _seed: int,
    ):
        return (
            0.61,
            {"expected_terminal_value": 2_750_000.0},
            goal_solver_engine.RiskSummary(
                max_drawdown_90pct=0.12,
                terminal_value_tail_mean_95=2_020_000.0,
                shortfall_probability=0.39,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    solver_input = {
        **deepcopy(goal_solver_input_base),
        "candidate_product_contexts": {
            "base_allocation": _estimated_candidate_context(),
        },
    }
    goal_solver_output = run_goal_solver(solver_input)

    def _fake_runtime_optimizer(**kwargs):
        return SimpleNamespace(
            candidate_poverty=False,
            mode=kwargs["mode"],
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
                "goal_solver_baseline": goal_solver_output.recommended_result.success_probability,
                "goal_solver_after_recommended": goal_solver_output.recommended_result.success_probability,
            },
            state_snapshot={"mode": kwargs["mode"].value},
            candidates_generated=1,
            candidates_after_filter=1,
            run_timestamp="2026-03-29T12:00:00Z",
            optimizer_params_version="v1.0.0",
            goal_solver_params_version=goal_solver_output.params_version,
        )

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    baseline_evidence_bundle = EvidenceBundle(
        request_id="baseline_run",
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of="2026-03-29T12:00:00Z",
        requested_result_category="formal_independent_result",
        resolved_result_category="formal_estimated_result",
        run_outcome_status=RunOutcomeStatus.DEGRADED,
        execution_policy="formal_estimation_allowed",
        disclosure_policy="FORMAL_STANDARD",
        simulation_mode="normal",
        mapping_signature="goal_solver:baseline",
        history_revision="params:v1",
        distribution_revision="calibration:baseline",
        solver_revision="params:v1",
        code_revision="v1.3-package4",
        input_refs={"bundle_id": "bundle_acc001_20260329T120000Z"},
        evidence_refs={"calibration_id": "calibration:baseline"},
        coverage_summary={"independent_weight_adjusted_coverage": 0.75},
        disclosure_decision={"disclosure_level": "range_only"},
    ).to_dict()

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "v13_package4_invariance"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
            "baseline_evidence_bundle": baseline_evidence_bundle,
        },
        prior_solver_output=goal_solver_output,
        prior_solver_input=solver_input,
    )

    report = result.evidence_invariance_report
    assert result.audit_record is not None
    assert result.audit_record.artifact_refs["has_evidence_invariance_report"] is True
    assert report["baseline_run_ref"] == "baseline_run"
    assert report["optimized_run_ref"] == "v13_package4_invariance"
    assert report["artifact_refs"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert report["verdict"] in {"invariant", "drifted"}
    assert "resolved_result_category" in report["semantic_refs"]
