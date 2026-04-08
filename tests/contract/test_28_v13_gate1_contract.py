from __future__ import annotations

import pytest

from decision_card.types import SecondaryCompanionArtifact
from goal_solver.types import (
    CandidateProductContext,
    ConfidenceDerivationPolicy,
    FormalEstimatedResultSpec,
    SuccessEventSpec,
    SuccessProbabilityResult,
    normalize_product_probability_method,
)
from shared.audit import (
    CoverageSummary,
    DisclosureDecision,
    EvidenceBundle,
    FormalPathStatus,
    RunOutcomeStatus,
    coerce_formal_path_status,
    coerce_run_outcome_status,
)


@pytest.mark.contract
def test_run_outcome_status_uses_v13_domain_and_formal_path_status_coerces_legacy_aliases():
    assert coerce_run_outcome_status("completed") == RunOutcomeStatus.COMPLETED
    assert coerce_run_outcome_status(RunOutcomeStatus.UNAVAILABLE) == RunOutcomeStatus.UNAVAILABLE
    assert coerce_formal_path_status("completed") == FormalPathStatus.COMPLETED
    assert coerce_formal_path_status("formal") == FormalPathStatus.COMPLETED
    assert coerce_formal_path_status("fallback_used_but_not_formal") == FormalPathStatus.DEGRADED
    assert FormalPathStatus is RunOutcomeStatus

    with pytest.raises(ValueError, match="unknown run_outcome_status"):
        coerce_run_outcome_status("formal")


@pytest.mark.contract
def test_coverage_summary_normalizes_v13_coverage_ontology_into_closed_zero_to_one_range():
    summary = CoverageSummary.from_any(
        {
            "selected_product_count": 4,
            "observed_product_count": 2,
            "inferred_product_count": 1,
            "missing_product_count": 1,
            "weight_adjusted_coverage": 76,
            "independent_weight_adjusted_coverage": 0.5,
            "horizon_complete_coverage": 40,
            "independent_horizon_complete_coverage": 0.25,
            "distribution_ready_coverage": 0.5,
            "explanation_ready_coverage": 100,
            "blocking_products": ["fund_satellite"],
        }
    )

    assert summary.selected_product_count == 4
    assert summary.observed_ratio == pytest.approx(0.5)
    assert summary.inferred_ratio == pytest.approx(0.25)
    assert summary.missing_ratio == pytest.approx(0.25)
    assert summary.covered_ratio == pytest.approx(0.75)
    assert summary.security_level_coverage == pytest.approx(0.75)
    assert summary.weight_adjusted_coverage == pytest.approx(0.76)
    assert summary.independent_weight_adjusted_coverage == pytest.approx(0.5)
    assert summary.horizon_complete_coverage == pytest.approx(0.4)
    assert summary.independent_horizon_complete_coverage == pytest.approx(0.25)
    assert summary.distribution_ready_coverage == pytest.approx(0.5)
    assert summary.explanation_ready_coverage == pytest.approx(1.0)
    assert summary.blocking_products == ["fund_satellite"]

    with pytest.raises(ValueError, match="coverage ratio"):
        CoverageSummary.from_any({"distribution_ready_coverage": 1.2})


@pytest.mark.contract
def test_gate1_probability_method_contract_maps_legacy_labels_into_closed_internal_set():
    context = CandidateProductContext(
        allocation_name="balanced",
        product_probability_method=" product_proxy_adjustment_estimate ",
    )
    result = SuccessProbabilityResult(
        allocation_name="balanced",
        weights={"equity_cn": 0.6, "bond_cn": 0.4},
        success_probability=0.66,
        expected_terminal_value=1_260_000.0,
        risk_summary={
            "max_drawdown_90pct": 0.18,
            "terminal_value_tail_mean_95": 910_000.0,
            "shortfall_probability": 0.34,
            "terminal_shortfall_p5_vs_initial": 0.09,
        },
        is_feasible=True,
        product_probability_method="bucket_only_no_product_proxy_adjustment",
        simulation_coverage_summary={
            "selected_product_count": 2,
            "observed_product_count": 1,
            "weight_adjusted_coverage": 0.5,
            "independent_weight_adjusted_coverage": 0.0,
            "horizon_complete_coverage": 0.5,
            "distribution_ready_coverage": 0.0,
            "explanation_ready_coverage": 0.5,
        },
    )

    assert normalize_product_probability_method("product_proxy_adjustment_estimate") == "product_estimated_path"
    assert normalize_product_probability_method("bucket_only_no_product_proxy_adjustment") == "product_estimated_path"
    assert normalize_product_probability_method("hybrid_independent_estimate") == "hybrid_independent_estimate"
    assert context.product_probability_method == "product_estimated_path"
    assert context.normalized_product_probability_method == "product_estimated_path"
    assert result.product_probability_method == "product_estimated_path"
    assert result.normalized_product_probability_method == "product_estimated_path"
    assert result.simulation_coverage_summary["distribution_ready_coverage"] == pytest.approx(0.0)


@pytest.mark.contract
def test_gate1_core_contracts_serialize_v13_schema_and_formal_estimated_result_is_positive_contract():
    success_event = SuccessEventSpec(
        horizon_months=36,
        target_type="target_annual_return",
        target_value=0.08,
        drawdown_constraint=0.2,
        benchmark_ref=None,
        contribution_policy="continue_monthly_contribution",
        rebalancing_policy="rebalance_gold_allowed",
        return_basis="nominal",
        fee_basis="net",
    )
    confidence_policy = ConfidenceDerivationPolicy(
        result_category="formal_estimated_result",
        minimum_independent_weight_adjusted_coverage_for_high=1.0,
        minimum_distribution_ready_coverage_for_high=1.0,
        minimum_calibration_quality_for_high="acceptable",
        maximum_confidence_by_result_category={
            "formal_independent_result": "high",
            "formal_estimated_result": "medium",
            "degraded_formal_result": "low",
        },
    )
    disclosure = DisclosureDecision(
        result_category="formal_estimated_result",
        disclosure_level="range_only",
        confidence_level="medium",
        data_completeness="partial",
        calibration_quality="acceptable",
        point_value_allowed=False,
        range_required=True,
        diagnostic_only=False,
        precision_cap="range_only",
        reasons=["estimated_result_requires_range_disclosure"],
    )
    companion = SecondaryCompanionArtifact(
        source_failure_ref="failure://goal/demo",
        companion_kind="exploratory_projection",
        exploratory_summary={"headline": "proxy exploration only"},
        disclosure_level="diagnostic_only",
        trustworthy_for_formal_decision=False,
    )
    bundle = EvidenceBundle(
        bundle_schema_version="v1.3",
        execution_policy_version="v1.3",
        disclosure_policy_version="v1.3",
        mapping_signature="mapping:abc123",
        history_revision="history:r1",
        distribution_revision="distribution:r1",
        solver_revision="solver:r1",
        code_revision="code:r1",
        calibration_revision="calibration:r1",
        request_id="req-demo",
        account_profile_id="acct-demo",
        as_of="2026-04-07",
        requested_result_category="formal_independent_result",
        resolved_result_category="formal_estimated_result",
        run_outcome_status="degraded",
        execution_policy="FORMAL_ESTIMATION_ALLOWED",
        disclosure_policy="FORMAL_STANDARD",
        simulation_mode="student_t",
        input_refs={"market_raw": "snapshot://market/demo"},
        evidence_refs={"solver_run": "solver://run/demo"},
        coverage_summary={
            "selected_product_count": 5,
            "observed_product_count": 3,
            "inferred_product_count": 1,
            "missing_product_count": 1,
            "weight_adjusted_coverage": 0.8,
            "independent_weight_adjusted_coverage": 0.6,
            "horizon_complete_coverage": 0.8,
            "independent_horizon_complete_coverage": 0.6,
            "distribution_ready_coverage": 0.6,
            "explanation_ready_coverage": 0.8,
        },
        calibration_summary={"sample_count": 120, "calibration_quality": "acceptable"},
        formal_path_status="degraded",
        failed_stage="disclosure_resolution",
        blocking_predicates=["independent_coverage_below_threshold"],
        degradation_reasons=["estimated_path_only"],
        next_recoverable_actions=["collect_missing_product_history"],
        diagnostics_trustworthy=True,
        secondary_companion_artifacts=[companion],
    )
    result_spec = FormalEstimatedResultSpec(
        estimation_basis="proxy_path",
        minimum_estimated_weight_adjusted_coverage=0.6,
        minimum_explanation_ready_coverage=0.6,
        point_estimate_allowed=False,
        required_range_disclosure=True,
    )

    assert bundle.run_outcome_status == RunOutcomeStatus.DEGRADED
    assert bundle.formal_path_status == FormalPathStatus.DEGRADED
    assert bundle.coverage_summary is not None
    assert bundle.coverage_summary.weight_adjusted_coverage == pytest.approx(0.8)
    assert bundle.to_dict()["secondary_companion_artifacts"][0]["companion_kind"] == "exploratory_projection"
    assert bundle.to_dict()["evidence_refs"]["solver_run"] == "solver://run/demo"
    assert disclosure.to_dict()["disclosure_level"] == "range_only"
    assert confidence_policy.to_dict()["maximum_confidence_by_result_category"]["formal_estimated_result"] == "medium"
    assert result_spec.to_dict()["estimation_basis"] == "proxy_path"
    assert result_spec.to_dict()["required_range_disclosure"] is True
    assert success_event.to_dict()["horizon_months"] == 36

    with pytest.raises(ValueError, match="unknown estimation_basis"):
        FormalEstimatedResultSpec(
            estimation_basis="product_proxy_path",
            minimum_estimated_weight_adjusted_coverage=0.6,
            minimum_explanation_ready_coverage=0.6,
        )


@pytest.mark.contract
def test_evidence_bundle_rejects_outcome_status_mismatch_and_formal_exploratory_resolution():
    with pytest.raises(ValueError, match="formal_path_status must match run_outcome_status"):
        EvidenceBundle(
            request_id="req-demo",
            execution_policy="FORMAL_STRICT",
            disclosure_policy="FORMAL_STANDARD",
            requested_result_category="formal_independent_result",
            resolved_result_category="formal_independent_result",
            run_outcome_status="blocked",
            formal_path_status="degraded",
        )

    with pytest.raises(ValueError, match="formal execution_policy cannot resolve exploratory_result"):
        EvidenceBundle(
            request_id="req-demo",
            execution_policy="FORMAL_STRICT",
            disclosure_policy="FORMAL_STANDARD",
            requested_result_category="formal_independent_result",
            resolved_result_category="exploratory_result",
            run_outcome_status="completed",
            formal_path_status="completed",
        )


@pytest.mark.contract
def test_disclosure_decision_and_confidence_policy_enforce_closed_contract_caps():
    with pytest.raises(ValueError, match="unknown disclosure_level"):
        DisclosureDecision(
            result_category="formal_independent_result",
            disclosure_level="full_text",
        )

    with pytest.raises(ValueError, match="confidence cap for formal_estimated_result cannot exceed medium"):
        ConfidenceDerivationPolicy(
            result_category="formal_estimated_result",
            minimum_independent_weight_adjusted_coverage_for_high=1.0,
            minimum_distribution_ready_coverage_for_high=1.0,
            minimum_calibration_quality_for_high="acceptable",
            maximum_confidence_by_result_category={
                "formal_estimated_result": "high",
            },
        )
