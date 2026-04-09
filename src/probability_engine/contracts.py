from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

FACTOR_MAPPING_CONFIDENCE_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
DISTRIBUTION_READINESS_ORDER: dict[str, int] = {"not_ready": 0, "partial": 1, "ready": 2}
CALIBRATION_QUALITY_ORDER: dict[str, int] = {"failed": 0, "weak": 1, "acceptable": 2, "strong": 3}


def _ordering_at_least(value: str, minimum: str, ordering: dict[str, int]) -> bool:
    try:
        return ordering[str(value)] >= ordering[str(minimum)]
    except KeyError as exc:  # pragma: no cover - defensive contract guard
        raise ValueError(f"unknown ordered value: {exc.args[0]}") from exc


def factor_mapping_confidence_at_least(value: str, minimum: str) -> bool:
    return _ordering_at_least(value, minimum, FACTOR_MAPPING_CONFIDENCE_ORDER)


def distribution_readiness_at_least(value: str, minimum: str) -> bool:
    return _ordering_at_least(value, minimum, DISTRIBUTION_READINESS_ORDER)


def calibration_quality_at_least(value: str, minimum: str) -> bool:
    return _ordering_at_least(value, minimum, CALIBRATION_QUALITY_ORDER)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    return value


@dataclass(frozen=True)
class SuccessEventSpec:
    horizon_days: int
    horizon_months: int
    target_type: str
    target_value: float
    drawdown_constraint: float | None
    benchmark_ref: str | None
    contribution_policy: str
    withdrawal_policy: str
    rebalancing_policy_ref: str
    return_basis: str
    fee_basis: str
    success_logic: str


@dataclass(frozen=True)
class PathStatsSummary:
    terminal_value_mean: float
    terminal_value_p05: float
    terminal_value_p50: float
    terminal_value_p95: float
    cagr_p05: float
    cagr_p50: float
    cagr_p95: float
    max_drawdown_p05: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    success_count: int
    path_count: int


@dataclass(frozen=True)
class ProbabilityDisclosurePayload:
    published_point: float | None
    published_range: tuple[float, float] | None
    disclosure_level: str
    confidence_level: str
    challenger_gap: float | None
    stress_gap: float | None
    gap_total: float | None
    widening_method: str


@dataclass(frozen=True)
class RecipeSimulationResult:
    recipe_name: str
    role: str
    success_probability: float
    success_probability_range: tuple[float, float]
    cagr_range: tuple[float, float]
    drawdown_range: tuple[float, float]
    sample_count: int
    path_stats: PathStatsSummary
    calibration_link_ref: str | None


@dataclass(frozen=True)
class DailyProbabilityEngineInput:
    as_of: str
    path_horizon_days: int
    products: list[Any]
    factor_dynamics: Any
    regime_state: Any
    jump_state: Any
    current_positions: list[Any]
    contribution_schedule: list[Any]
    withdrawal_schedule: list[Any]
    rebalancing_policy: Any
    success_event_spec: SuccessEventSpec
    recipes: list[Any]
    evidence_bundle_ref: str


@dataclass(frozen=True)
class ProbabilityEngineOutput:
    primary_result: RecipeSimulationResult
    challenger_results: list[RecipeSimulationResult]
    stress_results: list[RecipeSimulationResult]
    model_disagreement: dict[str, Any]
    probability_disclosure_payload: ProbabilityDisclosurePayload
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class FailureArtifact:
    failure_stage: str
    failure_code: str
    message: str
    diagnostic_refs: list[str] = field(default_factory=list)
    trustworthy_partial_diagnostics: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_stage", str(self.failure_stage).strip())
        object.__setattr__(self, "failure_code", str(self.failure_code).strip())
        object.__setattr__(self, "message", str(self.message).strip())
        object.__setattr__(
            self,
            "diagnostic_refs",
            [str(item).strip() for item in list(self.diagnostic_refs or []) if str(item).strip()],
        )
        object.__setattr__(self, "trustworthy_partial_diagnostics", bool(self.trustworthy_partial_diagnostics))


@dataclass(frozen=True)
class ProbabilityEngineRunResult:
    run_outcome_status: str
    resolved_result_category: str
    output: ProbabilityEngineOutput | None
    failure_artifact: FailureArtifact | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_outcome_status", str(self.run_outcome_status).strip())
        object.__setattr__(self, "resolved_result_category", str(self.resolved_result_category).strip())
        if self.output is None and self.failure_artifact is None:
            raise ValueError("either output or failure_artifact is required")
        if self.output is not None and self.failure_artifact is not None:
            raise ValueError("output and failure_artifact are mutually exclusive")
        if self.output is None and self.resolved_result_category != "null":
            raise ValueError("failure path requires resolved_result_category='null'")
        if self.output is not None and self.resolved_result_category == "null":
            raise ValueError("null category requires failure_artifact")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))
