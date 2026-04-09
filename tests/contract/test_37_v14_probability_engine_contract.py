from __future__ import annotations

import pytest

from decision_card.types import DecisionCardBuildInput, DecisionCardType
from probability_engine.contracts import (
    FailureArtifact,
    ProbabilityEngineRunResult,
    calibration_quality_at_least,
    distribution_readiness_at_least,
    factor_mapping_confidence_at_least,
)


def test_probability_engine_run_result_failure_requires_null_category() -> None:
    result = ProbabilityEngineRunResult(
        run_outcome_status="failure",
        resolved_result_category="null",
        output=None,
        failure_artifact=FailureArtifact(
            failure_stage="preflight",
            failure_code="missing_daily_path",
            message="daily product path unavailable",
            diagnostic_refs=["diag://missing_daily_path"],
            trustworthy_partial_diagnostics=False,
        ),
    )

    assert result.output is None
    assert result.failure_artifact is not None


def test_probability_engine_run_result_rejects_success_branch_failure_artifact() -> None:
    with pytest.raises(ValueError, match="run_outcome_status"):
        ProbabilityEngineRunResult(
            run_outcome_status="success",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="preflight",
                failure_code="missing_daily_path",
                message="daily product path unavailable",
                diagnostic_refs=["diag://missing_daily_path"],
                trustworthy_partial_diagnostics=False,
            ),
        )


def test_decision_card_build_input_from_any_rehydrates_probability_engine_result() -> None:
    build_input = DecisionCardBuildInput.from_any(
        {
            "card_type": DecisionCardType.GOAL_BASELINE,
            "workflow_type": "monthly",
            "goal_solver_output": {"success_probability": 0.62},
            "probability_engine_result": {
                "run_outcome_status": "failure",
                "resolved_result_category": "null",
                "output": None,
                "failure_artifact": {
                    "failure_stage": "preflight",
                    "failure_code": "missing_daily_path",
                    "message": "daily product path unavailable",
                    "diagnostic_refs": ["diag://missing_daily_path"],
                    "trustworthy_partial_diagnostics": False,
                },
            },
        }
    )

    assert isinstance(build_input.probability_engine_result, ProbabilityEngineRunResult)
    assert build_input.probability_engine_result.failure_artifact is not None
    assert build_input.probability_engine_result.failure_artifact.failure_code == "missing_daily_path"


def test_decision_card_build_input_from_any_rehydrates_success_probability_engine_output() -> None:
    build_input = DecisionCardBuildInput.from_any(
        {
            "card_type": DecisionCardType.GOAL_BASELINE,
            "workflow_type": "monthly",
            "goal_solver_output": {"success_probability": 0.71},
            "probability_engine_result": {
                "run_outcome_status": "success",
                "resolved_result_category": "formal_independent_result",
                "output": {
                    "primary_result": {
                        "recipe_name": "scheme_b_primary",
                        "role": "primary",
                        "success_probability": 0.71,
                        "success_probability_range": [0.68, 0.74],
                        "cagr_range": [0.05, 0.11],
                        "drawdown_range": [0.08, 0.16],
                        "sample_count": 2000,
                        "path_stats": {
                            "terminal_value_mean": 125000.0,
                            "terminal_value_p05": 110000.0,
                            "terminal_value_p50": 123000.0,
                            "terminal_value_p95": 139000.0,
                            "cagr_p05": 0.04,
                            "cagr_p50": 0.07,
                            "cagr_p95": 0.12,
                            "max_drawdown_p05": 0.06,
                            "max_drawdown_p50": 0.09,
                            "max_drawdown_p95": 0.18,
                            "success_count": 1420,
                            "path_count": 2000,
                        },
                        "calibration_link_ref": "cal://primary",
                    },
                    "challenger_results": [],
                    "stress_results": [],
                    "model_disagreement": {"gap": 0.03},
                    "probability_disclosure_payload": {
                        "published_point": 0.71,
                        "published_range": [0.68, 0.74],
                        "disclosure_level": "point_and_range",
                        "confidence_level": "medium",
                        "challenger_gap": 0.02,
                        "stress_gap": 0.05,
                        "gap_total": 0.07,
                        "widening_method": "max_gap",
                    },
                    "evidence_refs": ["evidence://primary"],
                },
                "failure_artifact": None,
            },
        }
    )

    assert isinstance(build_input.probability_engine_result, ProbabilityEngineRunResult)
    assert build_input.probability_engine_result is not None
    assert build_input.probability_engine_result.output is not None
    assert build_input.probability_engine_result.output.primary_result.recipe_name == "scheme_b_primary"
    assert build_input.probability_engine_result.output.primary_result.path_stats.path_count == 2000
    assert isinstance(build_input.probability_engine_result.output.primary_result.success_probability_range, tuple)
    assert isinstance(build_input.probability_engine_result.output.primary_result.cagr_range, tuple)
    assert isinstance(build_input.probability_engine_result.output.primary_result.drawdown_range, tuple)
    assert isinstance(
        build_input.probability_engine_result.output.probability_disclosure_payload.published_range,
        tuple,
    )


def test_enum_order_helpers_are_ordinal_not_string_based() -> None:
    assert factor_mapping_confidence_at_least("high", "medium") is True
    assert distribution_readiness_at_least("partial", "ready") is False
    assert calibration_quality_at_least("acceptable", "weak") is True
