from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from shared.audit import CoverageSummary


class RankingMode(str, Enum):
    SUFFICIENCY_FIRST = "sufficiency_first"
    PROBABILITY_MAX = "probability_max"
    BALANCED = "balanced"


def _normalize_profile_label(value: Any) -> str:
    return str(getattr(value, "value", value)).strip().lower()


_CONFIDENCE_LEVELS = {"high", "medium", "low"}
_CALIBRATION_QUALITIES = {"strong", "acceptable", "weak", "insufficient_sample"}
_RESULT_CATEGORIES = {
    "formal_independent_result",
    "formal_estimated_result",
    "degraded_formal_result",
    "exploratory_result",
}
_RESULT_CATEGORY_MAX_CONFIDENCE = {
    "formal_independent_result": "high",
    "formal_estimated_result": "medium",
    "degraded_formal_result": "low",
    "exploratory_result": "low",
}
_ESTIMATION_BASES = {
    "proxy_path",
    "factor_model",
    "bucket_estimate",
    "hybrid_independent_estimate",
}
_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


class ProductProbabilityMethod(str, Enum):
    PRODUCT_INDEPENDENT_PATH = "product_independent_path"
    PRODUCT_ESTIMATED_PATH = "product_estimated_path"
    PRODUCT_PROXY_PATH = "product_proxy_path"
    HYBRID_INDEPENDENT_ESTIMATE = "hybrid_independent_estimate"


_LEGACY_PRODUCT_PROBABILITY_METHOD_MAP: dict[str, ProductProbabilityMethod] = {
    "product_proxy_adjustment_estimate": ProductProbabilityMethod.PRODUCT_ESTIMATED_PATH,
    "bucket_only_no_product_proxy_adjustment": ProductProbabilityMethod.PRODUCT_ESTIMATED_PATH,
}


def _canonicalize_product_probability_method(value: Any) -> str:
    raw = str(getattr(value, "value", value) or "").strip().lower()
    return raw.replace(" ", "_")


def normalize_product_probability_method(value: Any) -> str:
    raw = _canonicalize_product_probability_method(value)
    if raw in _LEGACY_PRODUCT_PROBABILITY_METHOD_MAP:
        return _LEGACY_PRODUCT_PROBABILITY_METHOD_MAP[raw].value
    try:
        return ProductProbabilityMethod(raw).value
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown product_probability_method: {value}") from exc


def _coerce_product_probability_method_label(value: Any) -> str:
    return normalize_product_probability_method(value)


def _normalize_coverage_summary(value: Any) -> dict[str, Any]:
    summary = CoverageSummary.from_any(value)
    return {} if summary is None else summary.to_dict()


def _normalize_ratio_threshold(value: Any, *, field_name: str) -> float:
    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0: {value}")
    return numeric


def _normalize_estimation_basis(value: Any) -> str:
    raw = str(getattr(value, "value", value) or "").strip().lower().replace(" ", "_")
    if raw not in _ESTIMATION_BASES:
        raise ValueError(f"unknown estimation_basis: {value}")
    return raw


@dataclass(frozen=True)
class ConfidenceDerivationPolicy:
    result_category: str | None
    minimum_independent_weight_adjusted_coverage_for_high: float
    minimum_distribution_ready_coverage_for_high: float
    minimum_calibration_quality_for_high: str
    maximum_confidence_by_result_category: dict[str, str]

    def __post_init__(self) -> None:
        normalized_category = None if self.result_category in (None, "") else str(self.result_category).strip().lower()
        if normalized_category is not None and normalized_category not in _RESULT_CATEGORIES:
            raise ValueError(f"unknown result_category: {self.result_category}")
        object.__setattr__(self, "result_category", normalized_category)
        object.__setattr__(
            self,
            "minimum_independent_weight_adjusted_coverage_for_high",
            _normalize_ratio_threshold(
                self.minimum_independent_weight_adjusted_coverage_for_high,
                field_name="minimum_independent_weight_adjusted_coverage_for_high",
            ),
        )
        object.__setattr__(
            self,
            "minimum_distribution_ready_coverage_for_high",
            _normalize_ratio_threshold(
                self.minimum_distribution_ready_coverage_for_high,
                field_name="minimum_distribution_ready_coverage_for_high",
            ),
        )
        calibration_quality = str(self.minimum_calibration_quality_for_high).strip().lower()
        if calibration_quality not in _CALIBRATION_QUALITIES:
            raise ValueError(f"unknown minimum_calibration_quality_for_high: {self.minimum_calibration_quality_for_high}")
        object.__setattr__(self, "minimum_calibration_quality_for_high", calibration_quality)
        normalized_max = {
            str(category).strip().lower(): str(level).strip().lower()
            for category, level in dict(self.maximum_confidence_by_result_category or {}).items()
            if str(category).strip()
        }
        for category, level in normalized_max.items():
            if category not in _RESULT_CATEGORY_MAX_CONFIDENCE:
                raise ValueError(f"unknown result_category confidence cap: {category}")
            if level not in _CONFIDENCE_LEVELS:
                raise ValueError(f"unknown confidence_level: {level}")
            allowed_max = _RESULT_CATEGORY_MAX_CONFIDENCE[category]
            if _CONFIDENCE_ORDER[level] > _CONFIDENCE_ORDER[allowed_max]:
                raise ValueError(
                    f"confidence cap for {category} cannot exceed {allowed_max}: {level}"
                )
        object.__setattr__(self, "maximum_confidence_by_result_category", normalized_max)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RANKING_MODE_MATRIX: dict[tuple[str, str], RankingMode] = {
    ("essential", "conservative"): RankingMode.SUFFICIENCY_FIRST,
    ("essential", "moderate"): RankingMode.SUFFICIENCY_FIRST,
    ("essential", "aggressive"): RankingMode.SUFFICIENCY_FIRST,
    ("important", "conservative"): RankingMode.SUFFICIENCY_FIRST,
    ("important", "moderate"): RankingMode.SUFFICIENCY_FIRST,
    ("important", "aggressive"): RankingMode.BALANCED,
    ("aspirational", "conservative"): RankingMode.BALANCED,
    ("aspirational", "moderate"): RankingMode.PROBABILITY_MAX,
    ("aspirational", "aggressive"): RankingMode.PROBABILITY_MAX,
}


def infer_ranking_mode(priority: str, risk_preference: str) -> RankingMode:
    return RANKING_MODE_MATRIX.get(
        (_normalize_profile_label(priority), _normalize_profile_label(risk_preference)),
        RankingMode.SUFFICIENCY_FIRST,
    )


@dataclass
class MarketAssumptions:
    expected_returns: dict[str, float]
    volatility: dict[str, float]
    correlation_matrix: dict[str, dict[str, float]]
    source_name: str | None = None
    dataset_version: str | None = None
    lookback_months: int | None = None
    historical_backtest_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoalCard:
    goal_amount: float
    horizon_months: int
    goal_description: str
    success_prob_threshold: float
    priority: str = "important"
    risk_preference: str = "moderate"
    goal_type: str = "wealth_accumulation"
    target_annual_return: float | None = None
    goal_amount_basis: str = "nominal"
    goal_amount_scope: str = "total_assets"
    tax_assumption: str = "pre_tax"
    fee_assumption: str = "transaction_cost_only"
    contribution_commitment_confidence: float = 0.82

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CashFlowEvent:
    month_index: int
    amount: float
    event_type: str = "lump_sum"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CashFlowPlan:
    monthly_contribution: float
    annual_step_up_rate: float
    cashflow_events: list[CashFlowEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccountConstraints:
    max_drawdown_tolerance: float
    ips_bucket_boundaries: dict[str, tuple[float, float]]
    satellite_cap: float
    theme_caps: dict[str, float]
    qdii_cap: float
    liquidity_reserve_min: float
    bucket_category: dict[str, str] = field(default_factory=dict)
    bucket_to_theme: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategicAllocation:
    name: str
    weights: dict[str, float]
    complexity_score: float
    description: str = ""
    display_name: str = ""
    user_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductHistoryProfile:
    product_id: str
    source_ref: str | None = None
    observed_history_days: int | None = None
    inferred_history_days: int | None = None
    inference_weight: float = 1.0
    data_status: str = "manual_annotation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductSimulationSeries:
    product_id: str
    asset_bucket: str
    target_weight: float
    return_series: list[float] = field(default_factory=list)
    observation_dates: list[str] = field(default_factory=list)
    source_ref: str | None = None
    data_status: str = "manual_annotation"
    frequency: str = "daily"
    observed_start_date: str | None = None
    observed_end_date: str | None = None
    observed_points: int = 0
    inferred_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductSimulationInput:
    products: list[ProductSimulationSeries] = field(default_factory=list)
    frequency: str = "daily"
    simulation_method: str = "product_independent_path"
    audit_window: dict[str, Any] | None = None
    coverage_summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.coverage_summary = _normalize_coverage_summary(self.coverage_summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [item.to_dict() for item in self.products],
            "frequency": self.frequency,
            "simulation_method": self.simulation_method,
            "audit_window": None if self.audit_window is None else dict(self.audit_window),
            "coverage_summary": dict(self.coverage_summary),
        }


@dataclass
class CandidateProductContext:
    allocation_name: str
    product_probability_method: str = "product_estimated_path"
    bucket_expected_return_adjustments: dict[str, float] = field(default_factory=dict)
    bucket_volatility_multipliers: dict[str, float] = field(default_factory=dict)
    selected_product_ids: list[str] = field(default_factory=list)
    selected_proxy_refs: list[str] = field(default_factory=list)
    product_history_profiles: list[ProductHistoryProfile] = field(default_factory=list)
    product_simulation_input: ProductSimulationInput | None = None
    formal_path_preflight: dict[str, Any] = field(default_factory=dict)
    failure_artifact: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.product_probability_method = _coerce_product_probability_method_label(self.product_probability_method)
        if isinstance(self.product_simulation_input, dict):
            self.product_simulation_input = ProductSimulationInput(**self.product_simulation_input)

    @property
    def normalized_product_probability_method(self) -> str:
        return normalize_product_probability_method(self.product_probability_method)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_name": self.allocation_name,
            "product_probability_method": self.product_probability_method,
            "bucket_expected_return_adjustments": dict(self.bucket_expected_return_adjustments),
            "bucket_volatility_multipliers": dict(self.bucket_volatility_multipliers),
            "selected_product_ids": list(self.selected_product_ids),
            "selected_proxy_refs": list(self.selected_proxy_refs),
            "product_history_profiles": [item.to_dict() for item in self.product_history_profiles],
            "product_simulation_input": (
                None if self.product_simulation_input is None else self.product_simulation_input.to_dict()
            ),
            "formal_path_preflight": dict(self.formal_path_preflight or {}),
            "failure_artifact": None if self.failure_artifact is None else dict(self.failure_artifact),
            "notes": list(self.notes),
        }


@dataclass
class GoalSolverParams:
    version: str
    n_paths: int
    n_paths_lightweight: int
    seed: int
    market_assumptions: MarketAssumptions
    shrinkage_factor: float = 0.85
    ranking_mode_default: RankingMode = RankingMode.SUFFICIENCY_FIRST

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoalSolverInput:
    snapshot_id: str
    account_profile_id: str
    goal: GoalCard
    cashflow_plan: CashFlowPlan
    current_portfolio_value: float
    candidate_allocations: list[StrategicAllocation]
    constraints: AccountConstraints
    solver_params: GoalSolverParams
    ranking_mode_override: RankingMode | None = None
    candidate_product_contexts: dict[str, CandidateProductContext] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskSummary:
    max_drawdown_90pct: float
    terminal_value_tail_mean_95: float
    shortfall_probability: float
    terminal_shortfall_p5_vs_initial: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructureBudget:
    core_weight: float
    defense_weight: float
    satellite_weight: float
    theme_remaining_budget: dict[str, float]
    satellite_remaining_cap: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskBudget:
    drawdown_budget_used_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExpectedReturnDecomposition:
    decomposition_basis: str
    additivity_convention: str
    residual: float
    component_contributions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SuccessEventSpec:
    horizon_months: int
    target_type: str
    target_value: float
    drawdown_constraint: float | None
    benchmark_ref: str | None
    contribution_policy: str
    rebalancing_policy: str
    return_basis: str
    fee_basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FormalEstimatedResultSpec:
    estimation_basis: str
    minimum_estimated_weight_adjusted_coverage: float
    minimum_explanation_ready_coverage: float
    point_estimate_allowed: bool = False
    required_range_disclosure: bool = True

    def __post_init__(self) -> None:
        self.estimation_basis = _normalize_estimation_basis(self.estimation_basis)
        self.minimum_estimated_weight_adjusted_coverage = _normalize_ratio_threshold(
            self.minimum_estimated_weight_adjusted_coverage,
            field_name="minimum_estimated_weight_adjusted_coverage",
        )
        self.minimum_explanation_ready_coverage = _normalize_ratio_threshold(
            self.minimum_explanation_ready_coverage,
            field_name="minimum_explanation_ready_coverage",
        )
        self.point_estimate_allowed = bool(self.point_estimate_allowed)
        self.required_range_disclosure = bool(self.required_range_disclosure)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SuccessProbabilityResult:
    allocation_name: str
    weights: dict[str, float]
    success_probability: float
    expected_terminal_value: float
    risk_summary: RiskSummary
    is_feasible: bool
    bucket_success_probability: float | None = None
    product_proxy_adjusted_success_probability: float | None = None
    product_independent_success_probability: float | None = None
    product_probability_method: str = "product_estimated_path"
    selected_product_ids: list[str] = field(default_factory=list)
    selected_proxy_refs: list[str] = field(default_factory=list)
    bucket_expected_return_adjustments: dict[str, float] = field(default_factory=dict)
    bucket_volatility_multipliers: dict[str, float] = field(default_factory=dict)
    simulation_coverage_summary: dict[str, Any] = field(default_factory=dict)
    implied_required_annual_return: float | None = None
    expected_annual_return: float | None = None
    success_event_spec: SuccessEventSpec | dict[str, Any] | None = None
    formal_estimated_result_spec: FormalEstimatedResultSpec | dict[str, Any] | None = None
    expected_return_decomposition: ExpectedReturnDecomposition | dict[str, Any] | None = None
    display_name: str = ""
    summary: str = ""
    complexity_label: str = ""
    infeasibility_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.risk_summary, dict):
            self.risk_summary = RiskSummary(**self.risk_summary)
        if isinstance(self.success_event_spec, dict):
            self.success_event_spec = SuccessEventSpec(**self.success_event_spec)
        if isinstance(self.formal_estimated_result_spec, dict):
            self.formal_estimated_result_spec = FormalEstimatedResultSpec(**self.formal_estimated_result_spec)
        if isinstance(self.expected_return_decomposition, dict):
            self.expected_return_decomposition = ExpectedReturnDecomposition(**self.expected_return_decomposition)
        self.product_probability_method = _coerce_product_probability_method_label(self.product_probability_method)
        self.simulation_coverage_summary = _normalize_coverage_summary(self.simulation_coverage_summary)

    @property
    def normalized_product_probability_method(self) -> str:
        return normalize_product_probability_method(self.product_probability_method)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_summary"] = self.risk_summary.to_dict()
        return data


@dataclass
class FrontierScenario:
    scenario_id: str
    allocation_name: str
    weights: dict[str, float]
    success_probability: float
    expected_terminal_value: float
    max_drawdown_90pct: float
    product_proxy_adjusted_success_probability: float | None = None
    product_independent_success_probability: float | None = None
    product_probability_method: str = "product_estimated_path"
    selected_product_ids: list[str] = field(default_factory=list)
    bucket_expected_return_adjustments: dict[str, float] = field(default_factory=dict)
    bucket_volatility_multipliers: dict[str, float] = field(default_factory=dict)
    simulation_coverage_summary: dict[str, Any] = field(default_factory=dict)
    success_event_spec: SuccessEventSpec | dict[str, Any] | None = None
    formal_estimated_result_spec: FormalEstimatedResultSpec | dict[str, Any] | None = None
    expected_return_decomposition: ExpectedReturnDecomposition | dict[str, Any] | None = None
    expected_annual_return: float | None = None
    meets_success_threshold: bool = False
    drawdown_gap: float = 0.0
    target_return_gap: float = 0.0
    rationale: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.success_event_spec, dict):
            self.success_event_spec = SuccessEventSpec(**self.success_event_spec)
        if isinstance(self.formal_estimated_result_spec, dict):
            self.formal_estimated_result_spec = FormalEstimatedResultSpec(**self.formal_estimated_result_spec)
        if isinstance(self.expected_return_decomposition, dict):
            self.expected_return_decomposition = ExpectedReturnDecomposition(**self.expected_return_decomposition)
        self.product_probability_method = _coerce_product_probability_method_label(self.product_probability_method)
        self.simulation_coverage_summary = _normalize_coverage_summary(self.simulation_coverage_summary)

    @property
    def normalized_product_probability_method(self) -> str:
        return normalize_product_probability_method(self.product_probability_method)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrontierAnalysis:
    implied_required_annual_return: float | None
    success_probability_threshold: float
    max_drawdown_tolerance: float
    recommended: FrontierScenario
    highest_probability: FrontierScenario
    target_return_priority: FrontierScenario
    drawdown_priority: FrontierScenario
    balanced_tradeoff: FrontierScenario
    scenario_status: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "implied_required_annual_return": self.implied_required_annual_return,
            "success_probability_threshold": self.success_probability_threshold,
            "max_drawdown_tolerance": self.max_drawdown_tolerance,
            "recommended": self.recommended.to_dict(),
            "highest_probability": self.highest_probability.to_dict(),
            "target_return_priority": self.target_return_priority.to_dict(),
            "drawdown_priority": self.drawdown_priority.to_dict(),
            "balanced_tradeoff": self.balanced_tradeoff.to_dict(),
            "scenario_status": self.scenario_status,
        }


@dataclass
class GoalSolverOutput:
    input_snapshot_id: str
    generated_at: str
    recommended_allocation: StrategicAllocation
    recommended_result: SuccessProbabilityResult
    all_results: list[SuccessProbabilityResult]
    ranking_mode_used: RankingMode
    structure_budget: StructureBudget
    risk_budget: RiskBudget
    solver_notes: list[str] = field(default_factory=list)
    params_version: str = ""
    frontier_analysis: FrontierAnalysis | None = None
    frontier_diagnostics: dict[str, Any] = field(default_factory=dict)
    candidate_menu: list[dict[str, Any]] = field(default_factory=list)
    fallback_suggestions: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = "以下为模型模拟结果，不是历史回测收益承诺。"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["recommended_allocation"] = self.recommended_allocation.to_dict()
        data["recommended_result"] = self.recommended_result.to_dict()
        data["frontier_analysis"] = self.frontier_analysis.to_dict() if self.frontier_analysis is not None else None
        data["all_results"] = [item.to_dict() for item in self.all_results]
        data["structure_budget"] = self.structure_budget.to_dict()
        data["risk_budget"] = self.risk_budget.to_dict()
        data["ranking_mode_used"] = self.ranking_mode_used.value
        return data
