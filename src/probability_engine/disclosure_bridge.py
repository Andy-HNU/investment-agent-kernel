from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from probability_engine.contracts import (
    FailureArtifact,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
    SuccessEventSpec,
)


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _base_confidence_from_primary(primary: RecipeSimulationResult) -> str:
    if primary.sample_count >= 3000:
        return "high"
    if primary.sample_count >= 1000:
        return "medium"
    return "low"


def _confidence_rank(value: str) -> int:
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(str(value).strip().lower(), 0)


def _downshift_confidence(base_confidence: str, gap_total: float) -> str:
    confidence = str(base_confidence).strip().lower()
    if gap_total < 0.03:
        return confidence
    if gap_total < 0.07:
        return {0: "low", 1: "low", 2: "medium"}[_confidence_rank(confidence)]
    return "low"


def _result_category_from_confidence(confidence_level: str) -> str:
    confidence = str(confidence_level).strip().lower()
    if confidence == "high":
        return "formal_strict_result"
    if confidence == "medium":
        return "formal_estimated_result"
    return "degraded_formal_result"


@dataclass(frozen=True)
class ModelDisagreementSummary:
    primary_probability: float
    best_challenger_probability: float | None
    stress_probability: float | None
    challenger_gap: float | None
    stress_gap: float | None
    gap_total: float | None
    confidence_level: str
    widening_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _best_challenger(primary: RecipeSimulationResult, challengers: list[RecipeSimulationResult]) -> RecipeSimulationResult | None:
    if not challengers:
        return None
    return max(challengers, key=lambda challenger: abs(float(primary.success_probability) - float(challenger.success_probability)))


def _best_stress(stresses: list[RecipeSimulationResult]) -> RecipeSimulationResult | None:
    if not stresses:
        return None
    return min(stresses, key=lambda stress: float(stress.success_probability))


def _published_range(primary: RecipeSimulationResult, gap_total: float) -> tuple[float, float]:
    lower, upper = tuple(primary.success_probability_range)
    widened_lower = _clamp_probability(lower - 0.5 * gap_total)
    widened_upper = _clamp_probability(upper + 0.5 * gap_total)
    return (widened_lower, widened_upper)


def assemble_probability_run_result(
    *,
    primary: RecipeSimulationResult | None,
    challengers: list[RecipeSimulationResult],
    stresses: list[RecipeSimulationResult],
    success_event_spec: SuccessEventSpec,
) -> ProbabilityEngineRunResult:
    if primary is None:
        return ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="disclosure_bridge",
                failure_code="missing_primary_result",
                message="primary result is required to assemble a probability disclosure payload",
                diagnostic_refs=[],
                trustworthy_partial_diagnostics=False,
            ),
        )

    best_challenger = _best_challenger(primary, challengers)
    best_stress = _best_stress(stresses)

    challenger_gap = abs(float(primary.success_probability) - float(best_challenger.success_probability)) if best_challenger else None
    stress_gap = max(0.0, float(primary.success_probability) - float(best_stress.success_probability)) if best_stress else None
    gap_total = max([gap for gap in [challenger_gap, stress_gap] if gap is not None], default=0.0)

    base_confidence = _base_confidence_from_primary(primary)
    confidence_level = _downshift_confidence(base_confidence, gap_total)
    disclosure_level = "point_and_range" if confidence_level == "high" else "range_only"
    published_range = _published_range(primary, gap_total)

    model_disagreement = ModelDisagreementSummary(
        primary_probability=float(primary.success_probability),
        best_challenger_probability=None if best_challenger is None else float(best_challenger.success_probability),
        stress_probability=None if best_stress is None else float(best_stress.success_probability),
        challenger_gap=challenger_gap,
        stress_gap=stress_gap,
        gap_total=gap_total,
        confidence_level=confidence_level,
        widening_method="task5_primary_challenger_stress",
    )

    result_category = _result_category_from_confidence(confidence_level)
    evidence_refs = [ref for ref in [primary.calibration_link_ref, *(item.calibration_link_ref for item in challengers), *(item.calibration_link_ref for item in stresses)] if ref]

    output = ProbabilityEngineOutput(
        primary_result=primary,
        challenger_results=challengers,
        stress_results=stresses,
        model_disagreement=model_disagreement.to_dict(),
        probability_disclosure_payload=ProbabilityDisclosurePayload(
            published_point=_clamp_probability(primary.success_probability),
            published_range=published_range,
            disclosure_level=disclosure_level,
            confidence_level=confidence_level,
            challenger_gap=challenger_gap,
            stress_gap=stress_gap,
            gap_total=gap_total,
            widening_method="task5_primary_challenger_stress",
        ),
        evidence_refs=evidence_refs,
    )

    return ProbabilityEngineRunResult(
        run_outcome_status="success" if confidence_level == "high" else "degraded",
        resolved_result_category=result_category,
        output=output,
        failure_artifact=None,
    )
