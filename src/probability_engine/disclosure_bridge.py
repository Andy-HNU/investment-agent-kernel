from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from probability_engine.contracts import (
    CALIBRATION_QUALITY_ORDER,
    DISTRIBUTION_READINESS_ORDER,
    FACTOR_MAPPING_CONFIDENCE_ORDER,
    FailureArtifact,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
    factor_mapping_confidence_at_least,
    distribution_readiness_at_least,
    calibration_quality_at_least,
)

_WIDENING_METHOD = "wilson_plus_gap_total"


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _confidence_rank(value: str) -> int:
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(str(value).strip().lower(), 0)


def _lower_confidence(value: str) -> str:
    return {2: "medium", 1: "low", 0: "low"}[_confidence_rank(value)]


def _confidence_score_from_evidence(evidence: "DisclosureEvidenceSpec") -> int:
    score = 0
    if float(evidence.observed_weight_adjusted_coverage) >= 0.95:
        score += 2
    if str(evidence.factor_mapping_confidence).strip().lower() == "high":
        score += 2
    if str(evidence.distribution_readiness).strip().lower() == "ready":
        score += 2
    if str(evidence.calibration_quality).strip().lower() == "strong":
        score += 2
    if bool(evidence.challenger_available):
        score += 1
    if bool(evidence.stress_available):
        score += 1
    return score


def _base_confidence_from_evidence(evidence: "DisclosureEvidenceSpec") -> str:
    score = _confidence_score_from_evidence(evidence)
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def _downshift_confidence(base_confidence: str, gap_total: float) -> str:
    if gap_total < 0.03:
        return str(base_confidence).strip().lower()
    if gap_total < 0.07:
        return _lower_confidence(str(base_confidence).strip().lower())
    return "low"


def _hard_cap_confidence(
    confidence_level: str,
    *,
    result_category: str,
    evidence: "DisclosureEvidenceSpec",
) -> str:
    confidence = str(confidence_level).strip().lower()
    if result_category == "degraded_formal_result":
        confidence = confidence if confidence != "high" else "medium"
    if result_category == "formal_estimated_result" and float(evidence.estimated_weight_adjusted_coverage) > 0.25:
        confidence = confidence if confidence != "high" else "medium"
    if not distribution_readiness_at_least(str(evidence.distribution_readiness), "ready"):
        confidence = confidence if confidence != "high" else "medium"
    return confidence


def _disclosure_level_for_category(result_category: str) -> str:
    if result_category == "formal_strict_result":
        return "point_and_range"
    if result_category in {"formal_estimated_result", "degraded_formal_result"}:
        return "range_only"
    return "diagnostic_only"


def _result_category_from_evidence(evidence: "DisclosureEvidenceSpec") -> str:
    if not evidence.daily_product_path_available:
        return "null"
    if evidence.monthly_fallback_used or evidence.bucket_fallback_used:
        return "null"
    if (
        str(evidence.execution_policy).strip().upper() == "FORMAL_STRICT"
        and float(evidence.independent_weight_adjusted_coverage) == 1.0
        and float(evidence.observed_weight_adjusted_coverage) >= 0.95
        and factor_mapping_confidence_at_least(str(evidence.factor_mapping_confidence), "medium")
        and distribution_readiness_at_least(str(evidence.distribution_readiness), "ready")
        and calibration_quality_at_least(str(evidence.calibration_quality), "acceptable")
    ):
        return "formal_strict_result"
    if (
        evidence.daily_product_path_available
        and float(evidence.observed_weight_adjusted_coverage) >= 0.60
        and float(evidence.estimated_weight_adjusted_coverage) <= 0.40
        and factor_mapping_confidence_at_least(str(evidence.factor_mapping_confidence), "low")
        and distribution_readiness_at_least(str(evidence.distribution_readiness), "partial")
        and calibration_quality_at_least(str(evidence.calibration_quality), "weak")
    ):
        return "formal_estimated_result"
    return "degraded_formal_result"


@dataclass(frozen=True)
class DisclosureEvidenceSpec:
    daily_product_path_available: bool
    monthly_fallback_used: bool
    bucket_fallback_used: bool
    independent_weight_adjusted_coverage: float
    observed_weight_adjusted_coverage: float
    estimated_weight_adjusted_coverage: float
    factor_mapping_confidence: str
    distribution_readiness: str
    calibration_quality: str
    challenger_available: bool
    stress_available: bool
    execution_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "factor_mapping_confidence", str(self.factor_mapping_confidence).strip().lower())
        object.__setattr__(self, "distribution_readiness", str(self.distribution_readiness).strip().lower())
        object.__setattr__(self, "calibration_quality", str(self.calibration_quality).strip().lower())
        object.__setattr__(self, "execution_policy", str(self.execution_policy).strip().upper())
        object.__setattr__(self, "daily_product_path_available", bool(self.daily_product_path_available))
        object.__setattr__(self, "monthly_fallback_used", bool(self.monthly_fallback_used))
        object.__setattr__(self, "bucket_fallback_used", bool(self.bucket_fallback_used))
        object.__setattr__(self, "challenger_available", bool(self.challenger_available))
        object.__setattr__(self, "stress_available", bool(self.stress_available))
        object.__setattr__(self, "independent_weight_adjusted_coverage", float(self.independent_weight_adjusted_coverage))
        object.__setattr__(self, "observed_weight_adjusted_coverage", float(self.observed_weight_adjusted_coverage))
        object.__setattr__(self, "estimated_weight_adjusted_coverage", float(self.estimated_weight_adjusted_coverage))

    @classmethod
    def from_any(cls, value: "DisclosureEvidenceSpec | dict[str, Any]") -> "DisclosureEvidenceSpec":
        if isinstance(value, cls):
            return value
        return cls(**dict(value))


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


@dataclass(frozen=True)
class DisclosureDecisionSummary:
    result_category: str
    disclosure_level: str
    confidence_level: str
    gap_total: float


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


def _resolve_disclosure_decision(
    *,
    primary: RecipeSimulationResult,
    challengers: list[RecipeSimulationResult],
    stresses: list[RecipeSimulationResult],
    evidence: DisclosureEvidenceSpec,
) -> DisclosureDecisionSummary:
    best_challenger = _best_challenger(primary, challengers)
    best_stress = _best_stress(stresses)
    challenger_gap = abs(float(primary.success_probability) - float(best_challenger.success_probability)) if best_challenger else None
    stress_gap = max(0.0, float(primary.success_probability) - float(best_stress.success_probability)) if best_stress else None
    gap_total = max([gap for gap in [challenger_gap, stress_gap] if gap is not None], default=0.0)

    result_category = _result_category_from_evidence(evidence)
    if result_category == "null":
        return DisclosureDecisionSummary(
            result_category="null",
            disclosure_level="unavailable" if not evidence.daily_product_path_available or evidence.monthly_fallback_used or evidence.bucket_fallback_used else "diagnostic_only",
            confidence_level="low",
            gap_total=gap_total,
        )

    base_confidence = _base_confidence_from_evidence(evidence)
    confidence_level = _downshift_confidence(base_confidence, gap_total)
    confidence_level = _hard_cap_confidence(confidence_level, result_category=result_category, evidence=evidence)
    disclosure_level = _disclosure_level_for_category(result_category)

    return DisclosureDecisionSummary(
        result_category=result_category,
        disclosure_level=disclosure_level,
        confidence_level=confidence_level,
        gap_total=gap_total,
    )


def assemble_probability_run_result(
    *,
    primary: RecipeSimulationResult | None,
    challengers: list[RecipeSimulationResult],
    stresses: list[RecipeSimulationResult],
    evidence: DisclosureEvidenceSpec,
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

    evidence = DisclosureEvidenceSpec.from_any(evidence)
    decision = _resolve_disclosure_decision(
        primary=primary,
        challengers=challengers,
        stresses=stresses,
        evidence=evidence,
    )
    if decision.result_category == "null":
        return ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="disclosure_bridge",
                failure_code="formal_surface_unavailable",
                message="formal disclosure cannot be resolved from the supplied evidence",
                diagnostic_refs=[],
                trustworthy_partial_diagnostics=False,
            ),
        )

    best_challenger = _best_challenger(primary, challengers)
    best_stress = _best_stress(stresses)
    challenger_gap = abs(float(primary.success_probability) - float(best_challenger.success_probability)) if best_challenger else None
    stress_gap = max(0.0, float(primary.success_probability) - float(best_stress.success_probability)) if best_stress else None
    gap_total = decision.gap_total

    model_disagreement = ModelDisagreementSummary(
        primary_probability=float(primary.success_probability),
        best_challenger_probability=None if best_challenger is None else float(best_challenger.success_probability),
        stress_probability=None if best_stress is None else float(best_stress.success_probability),
        challenger_gap=challenger_gap,
        stress_gap=stress_gap,
        gap_total=gap_total,
        confidence_level=decision.confidence_level,
        widening_method=_WIDENING_METHOD,
    )

    output = ProbabilityEngineOutput(
        primary_result=primary,
        challenger_results=challengers,
        stress_results=stresses,
        model_disagreement=model_disagreement.to_dict(),
        probability_disclosure_payload=ProbabilityDisclosurePayload(
            published_point=_clamp_probability(primary.success_probability),
            published_range=_published_range(primary, gap_total),
            disclosure_level=decision.disclosure_level,
            confidence_level=decision.confidence_level,
            challenger_gap=challenger_gap,
            stress_gap=stress_gap,
            gap_total=gap_total,
            widening_method=_WIDENING_METHOD,
        ),
        evidence_refs=[ref for ref in [primary.calibration_link_ref, *(item.calibration_link_ref for item in challengers), *(item.calibration_link_ref for item in stresses)] if ref],
    )

    return ProbabilityEngineRunResult(
        run_outcome_status="success" if decision.result_category == "formal_strict_result" else "degraded",
        resolved_result_category=decision.result_category,
        output=output,
        failure_artifact=None,
    )
