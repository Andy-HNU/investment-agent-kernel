from __future__ import annotations

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


def test_enum_order_helpers_are_ordinal_not_string_based() -> None:
    assert factor_mapping_confidence_at_least("high", "medium") is True
    assert distribution_readiness_at_least("partial", "ready") is False
    assert calibration_quality_at_least("acceptable", "weak") is True
