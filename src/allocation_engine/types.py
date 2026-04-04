from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from goal_solver.types import AccountConstraints, CashFlowPlan, GoalCard, StrategicAllocation


@dataclass
class AllocationProfile:
    account_profile_id: str
    risk_preference: str
    complexity_tolerance: str = "medium"
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)
    allowed_wrappers: list[str] = field(default_factory=list)
    forbidden_wrappers: list[str] = field(default_factory=list)
    allowed_regions: list[str] = field(default_factory=list)
    forbidden_regions: list[str] = field(default_factory=list)
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)
    qdii_allowed: bool = True
    profile_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationUniverse:
    buckets: list[str]
    bucket_category: dict[str, str]
    bucket_to_theme: dict[str, str | None]
    qdii_buckets: list[str] = field(default_factory=list)
    liquidity_buckets: list[str] = field(default_factory=list)
    bucket_alias: dict[str, str] = field(default_factory=dict)
    bucket_order: list[str] = field(default_factory=list)

    def ordered_buckets(self) -> list[str]:
        if self.bucket_order:
            seen = set(self.bucket_order)
            return list(self.bucket_order) + [bucket for bucket in self.buckets if bucket not in seen]
        return list(self.buckets)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationTemplate:
    template_name: str
    template_family: str
    target_core_weight: float
    target_defense_weight: float
    target_satellite_weight: float
    preferred_theme: str | None = None
    theme_tilt_strength: float = 0.0
    liquidity_buffer_bonus: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationEngineParams:
    version: str = "v1.0.0"
    min_candidates: int = 4
    max_candidates: int = 8
    dedup_l1_threshold: float = 0.08
    zero_clip_threshold: float = 1e-4
    weight_round_digits: int = 4
    complexity_bucket_count_weight: float = 0.35
    complexity_satellite_weight: float = 0.35
    complexity_theme_count_weight: float = 0.20
    complexity_special_rule_weight: float = 0.10
    theme_tilt_step: float = 0.05
    liquidity_buffer_step: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationEngineInput:
    account_profile: AllocationProfile
    goal: GoalCard
    cashflow_plan: CashFlowPlan
    constraints: AccountConstraints
    universe: AllocationUniverse
    params: AllocationEngineParams = field(default_factory=AllocationEngineParams)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateDiagnostics:
    allocation_name: str
    template_name: str
    theme_exposure: dict[str, float]
    satellite_weight: float
    qdii_weight: float
    liquidity_weight: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationEngineResult:
    candidate_set_id: str
    account_profile_id: str
    engine_version: str
    candidate_allocations: list[StrategicAllocation]
    diagnostics: list[CandidateDiagnostics]
    generation_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidate_allocations"] = [item.to_dict() for item in self.candidate_allocations]
        data["diagnostics"] = [item.to_dict() for item in self.diagnostics]
        return data
