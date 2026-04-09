from __future__ import annotations

from typing import Any

from probability_engine.contracts import (
    FailureArtifact,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
)
from probability_engine.path_generator import (
    DailyEngineRuntimeInput,
    probability_engine_confidence_level,
    simulate_primary_paths,
)
from probability_engine.recipes import primary_recipe, resolve_recipes


def _published_disclosure_level(run_outcome_status: str) -> str:
    return "point_and_range" if run_outcome_status == "success" else "range_only"


def _published_point(run_outcome_status: str, success_probability: float) -> float | None:
    if run_outcome_status != "success":
        return None
    return float(success_probability)


def _resolve_outcome(runtime_input: DailyEngineRuntimeInput) -> tuple[str, str]:
    confidence_level = probability_engine_confidence_level(runtime_input)
    if confidence_level == "low":
        return "degraded", "degraded_formal_result"
    return "success", "formal_independent_result"


def _base_disclosure_payload(
    primary_result: Any,
    *,
    run_outcome_status: str,
    confidence_level: str,
) -> ProbabilityDisclosurePayload:
    return ProbabilityDisclosurePayload(
        published_point=_published_point(run_outcome_status, primary_result.success_probability),
        published_range=tuple(primary_result.success_probability_range),
        disclosure_level=_published_disclosure_level(run_outcome_status),
        confidence_level=confidence_level,
        challenger_gap=None,
        stress_gap=None,
        gap_total=None,
        widening_method="task4_primary_only",
    )


def run_probability_engine(sim_input: Any) -> ProbabilityEngineRunResult:
    evidence_ref = None
    if isinstance(sim_input, dict):
        evidence_ref = sim_input.get("evidence_bundle_ref")
    try:
        runtime_input = DailyEngineRuntimeInput.from_any(sim_input)
        recipes = resolve_recipes(runtime_input.recipes)
        selected_recipe = primary_recipe(recipes)
        primary_result = simulate_primary_paths(runtime_input, selected_recipe)
        confidence_level = probability_engine_confidence_level(runtime_input)
        run_outcome_status, resolved_result_category = _resolve_outcome(runtime_input)
        return ProbabilityEngineRunResult(
            run_outcome_status=run_outcome_status,
            resolved_result_category=resolved_result_category,
            output=ProbabilityEngineOutput(
                primary_result=primary_result,
                challenger_results=[],
                stress_results=[],
                model_disagreement={},
                probability_disclosure_payload=_base_disclosure_payload(
                    primary_result,
                    run_outcome_status=run_outcome_status,
                    confidence_level=confidence_level,
                ),
                evidence_refs=[runtime_input.evidence_bundle_ref] if runtime_input.evidence_bundle_ref else [],
            ),
            failure_artifact=None,
        )
    except Exception as exc:
        return ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="probability_engine",
                failure_code="primary_daily_engine_failed",
                message=str(exc),
                diagnostic_refs=[str(evidence_ref)] if evidence_ref else [],
                trustworthy_partial_diagnostics=False,
            ),
        )
