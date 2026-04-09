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


def test_enum_order_helpers_are_ordinal_not_string_based() -> None:
    assert factor_mapping_confidence_at_least("high", "medium") is True
    assert distribution_readiness_at_least("partial", "ready") is False
    assert calibration_quality_at_least("acceptable", "weak") is True
