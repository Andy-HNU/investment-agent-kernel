from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class RankingMode(str, Enum):
    SUFFICIENCY_FIRST = "sufficiency_first"
    PROBABILITY_MAX = "probability_max"
    BALANCED = "balanced"


def _normalize_profile_label(value: Any) -> str:
    return str(getattr(value, "value", value)).strip().lower()


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
class CandidateProductContext:
    allocation_name: str
    product_probability_method: str = "product_proxy_adjustment_estimate"
    bucket_expected_return_adjustments: dict[str, float] = field(default_factory=dict)
    bucket_volatility_multipliers: dict[str, float] = field(default_factory=dict)
    selected_product_ids: list[str] = field(default_factory=list)
    selected_proxy_refs: list[str] = field(default_factory=list)
    product_history_profiles: list[ProductHistoryProfile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_name": self.allocation_name,
            "product_probability_method": self.product_probability_method,
            "bucket_expected_return_adjustments": dict(self.bucket_expected_return_adjustments),
            "bucket_volatility_multipliers": dict(self.bucket_volatility_multipliers),
            "selected_product_ids": list(self.selected_product_ids),
            "selected_proxy_refs": list(self.selected_proxy_refs),
            "product_history_profiles": [item.to_dict() for item in self.product_history_profiles],
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
class SuccessProbabilityResult:
    allocation_name: str
    weights: dict[str, float]
    success_probability: float
    expected_terminal_value: float
    risk_summary: RiskSummary
    is_feasible: bool
    bucket_success_probability: float | None = None
    product_adjusted_success_probability: float | None = None
    product_probability_method: str = "bucket_only_no_product_proxy_adjustment"
    implied_required_annual_return: float | None = None
    display_name: str = ""
    summary: str = ""
    complexity_label: str = ""
    infeasibility_reasons: list[str] = field(default_factory=list)

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
    product_adjusted_success_probability: float | None = None
    product_probability_method: str = "bucket_only_no_product_proxy_adjustment"
    expected_annual_return: float | None = None
    meets_success_threshold: bool = False
    drawdown_gap: float = 0.0
    target_return_gap: float = 0.0
    rationale: str = ""

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
