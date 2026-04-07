from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime
from typing import Any

from shared.audit import AuditWindow, DataStatus


def _as_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


_MODE_INELIGIBILITY_ACTIONS = {
    "select_lower_eligible_mode",
    "degrade_result",
    "mark_unavailable",
    "block_formal_run",
}
_CALIBRATION_QUALITY_LEVELS = {
    "strong",
    "acceptable",
    "weak",
    "insufficient_sample",
}
_DATA_STATUS_VALUES = {
    "observed",
    "inferred",
    "degraded",
}


def _normalize_text(value: Any, *, lower: bool = False) -> str:
    rendered = str(value or "").strip()
    return rendered.lower() if lower else rendered


def _normalize_text_list(values: Any, *, lower: bool = False) -> list[str]:
    items: list[str] = []
    for value in list(values or []):
        rendered = _normalize_text(value, lower=lower)
        if rendered and rendered not in items:
            items.append(rendered)
    return items


def _normalize_optional_text(value: Any, *, lower: bool = False) -> str | None:
    rendered = _normalize_text(value, lower=lower)
    return rendered or None


@dataclass
class ValuationObservation:
    bucket: str
    metric_name: str
    current_value: float
    history_values: list[float] = field(default_factory=list)
    data_status: DataStatus = DataStatus.OBSERVED
    source_ref: str = ""
    as_of: str = ""
    audit_window: AuditWindow | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_status"] = self.data_status.value
        payload["audit_window"] = None if self.audit_window is None else self.audit_window.to_dict()
        return payload


@dataclass
class ValuationPercentileResult:
    bucket: str
    metric_name: str
    percentile: float
    valuation_position: str
    current_value: float | None = None
    data_status: DataStatus = DataStatus.PRIOR_DEFAULT
    source_ref: str = ""
    as_of: str = ""
    audit_window: AuditWindow | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_status"] = self.data_status.value
        payload["audit_window"] = None if self.audit_window is None else self.audit_window.to_dict()
        return payload


@dataclass
class MarketState:
    as_of: Any
    source_bundle_id: str
    version: str
    risk_environment: str
    volatility_regime: str
    liquidity_status: dict[str, str]
    valuation_positions: dict[str, str]
    correlation_spike_alert: bool
    quality_flags: list[str] = field(default_factory=list)
    is_degraded: bool = False
    valuation_percentile: dict[str, float] = field(default_factory=dict)
    valuation_percentile_results: dict[str, ValuationPercentileResult] = field(default_factory=dict)
    liquidity_flag: dict[str, bool] = field(default_factory=dict)
    policy_regime: str | None = None
    macro_uncertainty: str | None = None
    sentiment_stress: str | None = None
    liquidity_stress: str | None = None
    manual_review_required: bool = False
    policy_signal_confidence: float = 0.0
    policy_signal_ids: list[str] = field(default_factory=list)
    historical_dataset_version: str | None = None
    historical_dataset_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConstraintState:
    as_of: Any
    source_bundle_id: str
    version: str
    ips_bucket_boundaries: dict[str, tuple[float, float]]
    satellite_cap: float
    theme_caps: dict[str, float]
    qdii_cap: float
    liquidity_reserve_min: float
    max_drawdown_tolerance: float
    rebalancing_band: float = 0.0
    forbidden_actions: list[str] = field(default_factory=list)
    cooling_period_days: int = 0
    soft_preferences: dict[str, Any] = field(default_factory=dict)
    effective_drawdown_threshold: float = 0.0
    cooldown_currently_active: bool = False
    bucket_category: dict[str, str] = field(default_factory=dict)
    bucket_to_theme: dict[str, str | None] = field(default_factory=dict)
    qdii_available: float = 0.0
    premium_discount: dict[str, float] = field(default_factory=dict)
    transaction_fee_rate: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviorState:
    as_of: Any
    source_bundle_id: str
    version: str
    recent_chase_risk: str
    recent_panic_risk: str
    trade_frequency_30d: float
    override_count_90d: int
    cooldown_active: bool
    cooldown_until: Any
    behavior_penalty_coeff: float
    recent_chasing_flag: bool = False
    high_emotion_flag: bool = False
    panic_flag: bool = False
    action_frequency_30d: int = 0
    emotion_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeOptimizerParams:
    version: str
    deviation_soft_threshold: float
    deviation_hard_threshold: float
    satellite_overweight_threshold: float
    drawdown_event_threshold: float
    min_candidates: int
    max_candidates: int
    min_cash_for_action: float = 0.0
    new_cash_split_buckets: int = 1
    new_cash_use_pct: float = 1.0
    defense_add_pct: float = 0.0
    rebalance_full_allowed_monthly: bool = False
    cooldown_trade_frequency_limit: float = 0.0
    amount_pct_min: float = 0.0
    amount_pct_max: float = 1.0
    max_portfolio_snapshot_age_days: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EVParams:
    version: str
    goal_impact_weight: float
    risk_penalty_weight: float
    soft_constraint_weight: float
    behavior_penalty_weight: float
    execution_penalty_weight: float
    goal_solver_seed: int
    goal_solver_min_delta: float
    high_confidence_min_diff: float
    medium_confidence_min_diff: float
    volatility_penalty_coeff: float = 0.0
    drawdown_penalty_coeff: float = 0.0
    qdii_premium_cost_rate: float = 0.0
    transaction_cost_rate: float = 0.0
    ips_headroom_warning_threshold: float = 0.0
    theme_budget_warning_pct: float = 0.0
    concentration_headroom_threshold: float = 0.0
    emotion_score_threshold: float = 0.0
    action_frequency_threshold: float = 0.0
    momentum_lookback_days: int = 0
    momentum_threshold_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParamVersionMeta:
    version_id: str
    source_bundle_id: str
    created_at: Any
    updated_reason: str
    quality: str
    is_temporary: bool
    can_be_replayed: bool
    previous_version_id: str | None = None
    market_assumptions_version: str | None = None
    goal_solver_params_version: str | None = None
    runtime_optimizer_params_version: str | None = None
    ev_params_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class SimulationModeEligibility:
    simulation_mode: str
    minimum_sample_months: int
    minimum_weight_adjusted_coverage: float
    requires_regime_stability: bool
    requires_jump_calibration: bool
    allowed_result_categories: list[str] = field(default_factory=list)
    downgrade_target: str | None = None
    ineligibility_action: str = "mark_unavailable"

    def __post_init__(self) -> None:
        self.simulation_mode = _normalize_text(self.simulation_mode, lower=True)
        if not self.simulation_mode:
            raise ValueError("simulation_mode is required")
        self.minimum_sample_months = int(self.minimum_sample_months)
        if self.minimum_sample_months < 0:
            raise ValueError("minimum_sample_months must be >= 0")
        self.minimum_weight_adjusted_coverage = float(self.minimum_weight_adjusted_coverage)
        if not 0.0 <= self.minimum_weight_adjusted_coverage <= 1.0:
            raise ValueError("minimum_weight_adjusted_coverage must be between 0 and 1")
        self.requires_regime_stability = bool(self.requires_regime_stability)
        self.requires_jump_calibration = bool(self.requires_jump_calibration)
        self.allowed_result_categories = _normalize_text_list(self.allowed_result_categories, lower=True)
        if not self.allowed_result_categories:
            raise ValueError("allowed_result_categories must not be empty")
        self.downgrade_target = _normalize_optional_text(self.downgrade_target, lower=True)
        self.ineligibility_action = _normalize_text(self.ineligibility_action, lower=True)
        if self.ineligibility_action not in _MODE_INELIGIBILITY_ACTIONS:
            raise ValueError(f"unknown ineligibility_action: {self.ineligibility_action}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModeResolutionDecision:
    requested_mode: str
    selected_mode: str | None
    eligible_modes_in_order: list[str]
    ineligibility_action: str
    downgraded: bool
    downgrade_reason: str | None = None

    def __post_init__(self) -> None:
        self.requested_mode = _normalize_text(self.requested_mode, lower=True)
        if not self.requested_mode:
            raise ValueError("requested_mode is required")
        self.selected_mode = _normalize_optional_text(self.selected_mode, lower=True)
        self.eligible_modes_in_order = _normalize_text_list(self.eligible_modes_in_order, lower=True)
        if not self.eligible_modes_in_order:
            raise ValueError("eligible_modes_in_order must not be empty")
        self.ineligibility_action = _normalize_text(self.ineligibility_action, lower=True)
        if self.ineligibility_action not in _MODE_INELIGIBILITY_ACTIONS:
            raise ValueError(f"unknown ineligibility_action: {self.ineligibility_action}")
        self.downgraded = bool(self.downgraded)
        self.downgrade_reason = _normalize_optional_text(self.downgrade_reason)
        if self.selected_mode is not None and self.selected_mode not in self.eligible_modes_in_order:
            raise ValueError("selected_mode must be included in eligible_modes_in_order when present")
        if self.selected_mode is None and not self.downgraded:
            raise ValueError("selected_mode cannot be empty when downgraded is False")
        if self.selected_mode is not None and self.selected_mode != self.requested_mode and not self.downgraded:
            raise ValueError("downgraded must be True when selected_mode differs from requested_mode")
        if self.selected_mode == self.requested_mode and self.downgraded:
            raise ValueError("downgraded cannot be True when requested_mode matches selected_mode")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationSummary:
    sample_count: int
    brier_score: float | None
    reliability_buckets: list[dict[str, Any]]
    regime_breakdown: list[dict[str, Any]]
    calibration_quality: str
    source_ref: str

    def __post_init__(self) -> None:
        self.sample_count = int(self.sample_count)
        if self.sample_count < 0:
            raise ValueError("sample_count must be >= 0")
        self.brier_score = None if self.brier_score is None else float(self.brier_score)
        if self.brier_score is not None and not 0.0 <= self.brier_score <= 1.0:
            raise ValueError("brier_score must be between 0 and 1")
        self.reliability_buckets = [dict(bucket) for bucket in list(self.reliability_buckets or [])]
        self.regime_breakdown = [dict(item) for item in list(self.regime_breakdown or [])]
        self.calibration_quality = _normalize_text(self.calibration_quality, lower=True)
        if self.calibration_quality not in _CALIBRATION_QUALITY_LEVELS:
            raise ValueError(f"unknown calibration_quality: {self.calibration_quality}")
        self.source_ref = _normalize_text(self.source_ref)
        if not self.source_ref:
            raise ValueError("source_ref is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DistributionModelState:
    simulation_mode: str
    selected_mode: str
    tail_model: str | None
    regime_sensitive: bool
    jump_overlay_enabled: bool
    eligibility_decision: SimulationModeEligibility | dict[str, Any]
    mode_resolution_decision: ModeResolutionDecision | dict[str, Any]
    calibration_summary: CalibrationSummary | dict[str, Any] | None
    source_ref: str
    as_of: str
    data_status: str

    def __post_init__(self) -> None:
        self.simulation_mode = _normalize_text(self.simulation_mode, lower=True)
        self.selected_mode = _normalize_text(self.selected_mode, lower=True)
        if not self.simulation_mode:
            raise ValueError("simulation_mode is required")
        if not self.selected_mode:
            raise ValueError("selected_mode is required")
        self.tail_model = _normalize_optional_text(self.tail_model, lower=True)
        self.regime_sensitive = bool(self.regime_sensitive)
        self.jump_overlay_enabled = bool(self.jump_overlay_enabled)
        self.eligibility_decision = (
            self.eligibility_decision
            if isinstance(self.eligibility_decision, SimulationModeEligibility)
            else SimulationModeEligibility(**dict(self.eligibility_decision))
        )
        self.mode_resolution_decision = (
            self.mode_resolution_decision
            if isinstance(self.mode_resolution_decision, ModeResolutionDecision)
            else ModeResolutionDecision(**dict(self.mode_resolution_decision))
        )
        self.calibration_summary = (
            None
            if self.calibration_summary is None
            else (
                self.calibration_summary
                if isinstance(self.calibration_summary, CalibrationSummary)
                else CalibrationSummary(**dict(self.calibration_summary))
            )
        )
        self.source_ref = _normalize_text(self.source_ref)
        if not self.source_ref:
            raise ValueError("source_ref is required")
        self.as_of = _normalize_text(self.as_of)
        if not self.as_of:
            raise ValueError("as_of is required")
        self.data_status = _normalize_text(self.data_status, lower=True)
        if self.data_status not in _DATA_STATUS_VALUES:
            raise ValueError(f"unknown data_status: {self.data_status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["eligibility_decision"] = self.eligibility_decision.to_dict()
        payload["mode_resolution_decision"] = self.mode_resolution_decision.to_dict()
        payload["calibration_summary"] = (
            None if self.calibration_summary is None else self.calibration_summary.to_dict()
        )
        return payload


@dataclass
class CalibrationResult:
    calibration_id: str
    source_bundle_id: str
    created_at: Any
    account_profile_id: str
    market_state: Any
    constraint_state: Any
    behavior_state: Any
    market_assumptions: Any
    goal_solver_params: Any
    runtime_optimizer_params: Any
    ev_params: Any
    distribution_model_state: DistributionModelState | dict[str, Any] | None = None
    calibration_summary: CalibrationSummary | dict[str, Any] | None = None
    calibration_quality: str = "full"
    degraded_domains: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    param_version_meta: ParamVersionMeta | dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.distribution_model_state = (
            None
            if self.distribution_model_state is None
            else (
                self.distribution_model_state
                if isinstance(self.distribution_model_state, DistributionModelState)
                else DistributionModelState(**dict(self.distribution_model_state))
            )
        )
        self.calibration_summary = (
            None
            if self.calibration_summary is None
            else (
                self.calibration_summary
                if isinstance(self.calibration_summary, CalibrationSummary)
                else CalibrationSummary(**dict(self.calibration_summary))
            )
        )
        self.param_version_meta = (
            self.param_version_meta
            if isinstance(self.param_version_meta, ParamVersionMeta)
            else ParamVersionMeta(**dict(self.param_version_meta))
        )
        self.calibration_quality = _normalize_text(self.calibration_quality, lower=True)
        self.degraded_domains = _normalize_text_list(self.degraded_domains, lower=True)
        self.notes = _normalize_text_list(self.notes)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["distribution_model_state"] = (
            None if self.distribution_model_state is None else self.distribution_model_state.to_dict()
        )
        payload["calibration_summary"] = (
            None if self.calibration_summary is None else self.calibration_summary.to_dict()
        )
        payload["param_version_meta"] = self.param_version_meta.to_dict()
        return payload
