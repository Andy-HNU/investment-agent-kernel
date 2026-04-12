from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    return value


_BUCKET_CARDINALITY_MODES = {"auto", "target_count", "count_range"}
_BUCKET_CARDINALITY_SOURCES = {"system_default", "user_requested", "persisted_user"}
_BUCKET_COUNT_RESOLUTION_SOURCES = {"explicit_user", "persisted_user", "auto_policy"}


def _require_nonempty_str_choice(value: Any, *, field_name: str, allowed: set[str]) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if normalized not in allowed:
        raise ValueError(f"invalid {field_name}: {value!r}")
    return normalized


def _require_real_bool(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")
    return value


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return value


@dataclass(frozen=True)
class BucketCardinalityPreference:
    bucket: str
    mode: Literal["auto", "target_count", "count_range"]
    target_count: int | None
    min_count: int | None
    max_count: int | None
    source: Literal["system_default", "user_requested", "persisted_user"] = "system_default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket", str(self.bucket).strip())
        object.__setattr__(self, "mode", _require_nonempty_str_choice(self.mode, field_name="mode", allowed=_BUCKET_CARDINALITY_MODES))
        object.__setattr__(self, "source", _require_nonempty_str_choice(self.source, field_name="source", allowed=_BUCKET_CARDINALITY_SOURCES))
        if self.target_count is not None:
            object.__setattr__(self, "target_count", _require_positive_int(self.target_count, field_name="target_count"))
        if self.min_count is not None:
            object.__setattr__(self, "min_count", _require_positive_int(self.min_count, field_name="min_count"))
        if self.max_count is not None:
            object.__setattr__(self, "max_count", _require_positive_int(self.max_count, field_name="max_count"))
        if self.mode == "target_count" and self.target_count is None:
            raise ValueError("target_count is required when mode='target_count'")
        if self.mode == "count_range":
            if self.target_count is None and self.min_count is None and self.max_count is None:
                raise ValueError("at least one of target_count, min_count, or max_count is required when mode='count_range'")
            if self.min_count is not None and self.max_count is not None and self.min_count > self.max_count:
                raise ValueError("min_count must be <= max_count")
            if (
                self.target_count is not None
                and self.min_count is not None
                and self.max_count is not None
                and not (self.min_count <= self.target_count <= self.max_count)
            ):
                raise ValueError("target_count must fall within min_count and max_count")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BucketCountResolution:
    bucket: str
    requested_count: int | None
    resolved_count: int
    source: Literal["explicit_user", "persisted_user", "auto_policy"]
    fully_satisfied: bool
    unmet_reasons: list[str] = field(default_factory=list)
    alternative_counts_considered: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket", str(self.bucket).strip())
        object.__setattr__(self, "resolved_count", _require_positive_int(self.resolved_count, field_name="resolved_count"))
        if self.requested_count is not None:
            object.__setattr__(self, "requested_count", _require_positive_int(self.requested_count, field_name="requested_count"))
        object.__setattr__(self, "source", _require_nonempty_str_choice(self.source, field_name="source", allowed=_BUCKET_COUNT_RESOLUTION_SOURCES))
        object.__setattr__(self, "fully_satisfied", _require_real_bool(self.fully_satisfied, field_name="fully_satisfied"))
        object.__setattr__(
            self,
            "unmet_reasons",
            [str(item).strip() for item in list(self.unmet_reasons or []) if str(item).strip()],
        )
        object.__setattr__(
            self,
            "alternative_counts_considered",
            [_require_positive_int(item, field_name="alternative_counts_considered") for item in list(self.alternative_counts_considered or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def _auto_resolve_count(
    *,
    bucket: str,
    bucket_weight: float,
    horizon_months: int | None,
    goal_horizon_months: int | None,
    risk_preference: str,
    max_drawdown_tolerance: float,
    current_market_pressure_score: float | None,
    required_return_gap: float | None,
    implied_required_annual_return: float | None,
) -> int:
    bucket = str(bucket).strip()
    effective_horizon_months = int(goal_horizon_months if goal_horizon_months is not None else horizon_months or 0)
    risk_preference = str(risk_preference).strip().lower()
    pressure_score = float(current_market_pressure_score or 0.0)
    effective_required_return_gap = (
        float(required_return_gap)
        if required_return_gap is not None
        else float(implied_required_annual_return or 0.0)
    )
    if bucket in {"gold", "cash_liquidity"}:
        return 1
    if effective_horizon_months < 12:
        return 1
    if bucket == "bond_cn":
        if effective_horizon_months >= 24 and bucket_weight >= 0.20:
            return 2
        return 1
    if bucket == "satellite":
        if bucket_weight < 0.08:
            return 1
        if effective_horizon_months < 18:
            return 2
        if 0.12 <= bucket_weight < 0.18:
            return 2
        if 0.18 <= bucket_weight < 0.28:
            return 3
        if bucket_weight >= 0.28:
            return 4
        return 2
    if bucket == "equity_cn":
        if risk_preference == "aggressive" and effective_required_return_gap > 0.02:
            return 1
        if effective_horizon_months < 18:
            return 1
        if effective_horizon_months < 24:
            return 2
        if pressure_score >= 25.0 or max_drawdown_tolerance <= 0.20 or risk_preference in {"moderate", "aggressive", "中等", "进取"}:
            return 2
        return 2
    return 1


def _preference_to_requested_count(preference: BucketCardinalityPreference | None) -> int | None:
    if preference is None:
        return None
    if preference.mode == "target_count":
        return preference.target_count
    if preference.mode == "count_range":
        if preference.target_count is not None:
            return preference.target_count
        if preference.min_count is not None:
            return preference.min_count
        return preference.max_count
    return None


def _preference_to_alternatives(preference: BucketCardinalityPreference | None, resolved_count: int) -> list[int]:
    if preference is None:
        return [max(1, resolved_count - 1), resolved_count + 1]
    if preference.mode == "count_range":
        alternatives: list[int] = []
        if preference.min_count is not None:
            alternatives.append(int(preference.min_count))
        if preference.max_count is not None:
            alternatives.append(int(preference.max_count))
        if preference.target_count is not None:
            alternatives.append(int(preference.target_count))
        return list(dict.fromkeys(item for item in alternatives if item > 0))
    requested = _preference_to_requested_count(preference)
    if requested is None:
        return [max(1, resolved_count - 1), resolved_count + 1]
    return list(dict.fromkeys(item for item in [requested - 1, requested, requested + 1] if item > 0))


def _assert_matching_bucket(preference: BucketCardinalityPreference | None, *, bucket: str, field_name: str) -> None:
    if preference is not None and str(preference.bucket).strip() != str(bucket).strip():
        raise ValueError(f"{field_name}.bucket must match bucket being resolved")


def resolve_bucket_count(
    *,
    bucket: str,
    bucket_weight: float,
    horizon_months: int | None = None,
    goal_horizon_months: int | None = None,
    risk_preference: str,
    max_drawdown_tolerance: float,
    current_market_pressure_score: float | None = None,
    required_return_gap: float | None = None,
    implied_required_annual_return: float | None = None,
    explicit_request: BucketCardinalityPreference | None = None,
    persisted_preference: BucketCardinalityPreference | None = None,
) -> BucketCountResolution:
    _assert_matching_bucket(explicit_request, bucket=bucket, field_name="explicit_request")
    _assert_matching_bucket(persisted_preference, bucket=bucket, field_name="persisted_preference")
    if explicit_request is not None:
        requested_count = _preference_to_requested_count(explicit_request)
        if requested_count is None:
            requested_count = _auto_resolve_count(
                bucket=bucket,
                bucket_weight=bucket_weight,
                horizon_months=horizon_months,
                goal_horizon_months=goal_horizon_months,
                risk_preference=risk_preference,
                max_drawdown_tolerance=max_drawdown_tolerance,
                current_market_pressure_score=current_market_pressure_score,
                required_return_gap=required_return_gap,
                implied_required_annual_return=implied_required_annual_return,
            )
        return BucketCountResolution(
            bucket=bucket,
            requested_count=requested_count,
            resolved_count=requested_count,
            source="explicit_user",
            fully_satisfied=True,
            unmet_reasons=[],
            alternative_counts_considered=_preference_to_alternatives(explicit_request, requested_count),
        )
    if persisted_preference is not None:
        requested_count = _preference_to_requested_count(persisted_preference)
        if requested_count is None:
            requested_count = _auto_resolve_count(
                bucket=bucket,
                bucket_weight=bucket_weight,
                horizon_months=horizon_months,
                goal_horizon_months=goal_horizon_months,
                risk_preference=risk_preference,
                max_drawdown_tolerance=max_drawdown_tolerance,
                current_market_pressure_score=current_market_pressure_score,
                required_return_gap=required_return_gap,
                implied_required_annual_return=implied_required_annual_return,
            )
        return BucketCountResolution(
            bucket=bucket,
            requested_count=requested_count,
            resolved_count=requested_count,
            source="persisted_user",
            fully_satisfied=True,
            unmet_reasons=[],
            alternative_counts_considered=_preference_to_alternatives(persisted_preference, requested_count),
        )

    resolved_count = _auto_resolve_count(
        bucket=bucket,
        bucket_weight=bucket_weight,
        horizon_months=horizon_months,
        goal_horizon_months=goal_horizon_months,
        risk_preference=risk_preference,
        max_drawdown_tolerance=max_drawdown_tolerance,
        current_market_pressure_score=current_market_pressure_score,
        required_return_gap=required_return_gap,
        implied_required_annual_return=implied_required_annual_return,
    )
    return BucketCountResolution(
        bucket=bucket,
        requested_count=None,
        resolved_count=resolved_count,
        source="auto_policy",
        fully_satisfied=True,
        unmet_reasons=[],
        alternative_counts_considered=_preference_to_alternatives(None, resolved_count),
    )
