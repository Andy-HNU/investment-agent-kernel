from __future__ import annotations

from allocation_engine.types import AllocationEngineParams, AllocationUniverse
from goal_solver.types import StrategicAllocation


def compute_complexity_score(
    weights: dict[str, float],
    universe: AllocationUniverse,
    params: AllocationEngineParams,
) -> float:
    active_buckets = [bucket for bucket, value in weights.items() if value > params.zero_clip_threshold]
    satellite_weight = sum(
        value for bucket, value in weights.items() if universe.bucket_category.get(bucket) == "satellite"
    )
    used_themes = {
        universe.bucket_to_theme.get(bucket)
        for bucket, value in weights.items()
        if value > params.zero_clip_threshold and universe.bucket_to_theme.get(bucket)
    }
    special_rule_hits = int(any(bucket in universe.qdii_buckets for bucket in active_buckets)) + int(
        any(bucket in universe.liquidity_buckets for bucket in active_buckets)
    )
    bucket_factor = len(active_buckets) / max(len(universe.buckets), 1)
    satellite_factor = satellite_weight
    distinct_themes = {theme for theme in universe.bucket_to_theme.values() if theme}
    theme_factor = len(used_themes) / max(1, len(distinct_themes))
    special_factor = min(special_rule_hits, 1)
    complexity = (
        params.complexity_bucket_count_weight * bucket_factor
        + params.complexity_satellite_weight * satellite_factor
        + params.complexity_theme_count_weight * theme_factor
        + params.complexity_special_rule_weight * special_factor
    )
    return max(0.0, min(1.0, complexity))


def build_strategic_allocation(
    name: str,
    weights: dict[str, float],
    universe: AllocationUniverse,
    params: AllocationEngineParams,
    description: str,
) -> StrategicAllocation:
    return StrategicAllocation(
        name=name,
        weights={bucket: round(value, params.weight_round_digits) for bucket, value in weights.items()},
        complexity_score=round(compute_complexity_score(weights, universe, params), 4),
        description=description,
    )
