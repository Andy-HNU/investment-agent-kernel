from __future__ import annotations

from typing import Any, Literal


SearchExpansionLevel = Literal["L0_compact", "L1_expanded", "L2_diversified", "L3_exhaustive"]


class SearchExpansionLevels:
    L0_COMPACT: str = "L0_compact"
    L1_EXPANDED: str = "L1_expanded"
    L2_DIVERSIFIED: str = "L2_diversified"
    L3_EXHAUSTIVE: str = "L3_exhaustive"


_SEARCH_EXPANSION_LEVELS: set[str] = {
    SearchExpansionLevels.L0_COMPACT,
    SearchExpansionLevels.L1_EXPANDED,
    SearchExpansionLevels.L2_DIVERSIFIED,
    SearchExpansionLevels.L3_EXHAUSTIVE,
}
DEFAULT_SEARCH_EXPANSION_LEVEL: str = SearchExpansionLevels.L0_COMPACT

_SEARCH_EXPANSION_POOL_LIMITS_BY_BUCKET: dict[str, dict[str, int]] = {
    "equity_cn": {
        SearchExpansionLevels.L0_COMPACT: 4,
        SearchExpansionLevels.L1_EXPANDED: 6,
        SearchExpansionLevels.L2_DIVERSIFIED: 8,
        SearchExpansionLevels.L3_EXHAUSTIVE: 10,
    },
    "satellite": {
        SearchExpansionLevels.L0_COMPACT: 5,
        SearchExpansionLevels.L1_EXPANDED: 8,
        SearchExpansionLevels.L2_DIVERSIFIED: 10,
        SearchExpansionLevels.L3_EXHAUSTIVE: 12,
    },
    "bond_cn": {
        SearchExpansionLevels.L0_COMPACT: 2,
        SearchExpansionLevels.L1_EXPANDED: 3,
        SearchExpansionLevels.L2_DIVERSIFIED: 4,
        SearchExpansionLevels.L3_EXHAUSTIVE: 4,
    },
}

_SEARCH_EXPANSION_DEFAULT_LIMITS: dict[str, int] = {
    SearchExpansionLevels.L0_COMPACT: 4,
    SearchExpansionLevels.L1_EXPANDED: 6,
    SearchExpansionLevels.L2_DIVERSIFIED: 8,
    SearchExpansionLevels.L3_EXHAUSTIVE: 10,
}

_MIN_TARGET_DISTANCE_STALL_GAIN = 0.001
_MIN_CONSECUTIVE_SMALL_GAIN_COUNT = 2
_CANONICAL_BUCKETS: set[str] = {"equity_cn", "bond_cn", "gold", "cash_liquidity", "satellite"}


def _normalize_bucket(bucket: Any) -> str:
    if bucket is None:
        raise ValueError("invalid bucket: None")
    if not isinstance(bucket, str):
        raise ValueError(f"invalid bucket: {bucket!r}")
    normalized = bucket.strip()
    if normalized not in _CANONICAL_BUCKETS:
        raise ValueError(f"invalid bucket: {bucket!r}")
    return normalized


def normalize_search_expansion_level(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("search_expansion_level must be a string")
    normalized = value.strip()
    if normalized not in _SEARCH_EXPANSION_LEVELS:
        raise ValueError(f"invalid search_expansion_level: {value!r}")
    return normalized


def candidate_pool_limit(bucket: Any, search_expansion_level: SearchExpansionLevel | str) -> int:
    normalized_bucket = _normalize_bucket(bucket)
    normalized_level = normalize_search_expansion_level(search_expansion_level)
    bucket_limits = _SEARCH_EXPANSION_POOL_LIMITS_BY_BUCKET.get(normalized_bucket)
    if bucket_limits is not None and normalized_level in bucket_limits:
        return bucket_limits[normalized_level]
    return _SEARCH_EXPANSION_DEFAULT_LIMITS[normalized_level]


def resolve_search_stop_reason(
    *,
    success_improvement: float,
    target_distance_improvement: float,
    drawdown_improvement: float,
    hard_stop_reason: str | None,
    consecutive_small_gain_count: int,
) -> str | None:
    if hard_stop_reason is not None:
        reason = str(hard_stop_reason).strip()
        return reason or None

    if consecutive_small_gain_count >= _MIN_CONSECUTIVE_SMALL_GAIN_COUNT and float(target_distance_improvement) < _MIN_TARGET_DISTANCE_STALL_GAIN:
        return "marginal_target_distance_gain_too_small"

    if float(success_improvement) <= 0.0 and float(drawdown_improvement) <= 0.0:
        return "no_material_improvement"

    return None
