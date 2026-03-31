from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime
from typing import Any


def _as_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


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
    liquidity_flag: dict[str, bool] = field(default_factory=dict)

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
    calibration_quality: str = "full"
    degraded_domains: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    param_version_meta: ParamVersionMeta | dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
