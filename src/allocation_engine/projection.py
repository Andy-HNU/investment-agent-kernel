from __future__ import annotations

from allocation_engine.types import AllocationEngineParams, AllocationProfile, AllocationUniverse
from goal_solver.types import AccountConstraints


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _ordered_eligible_buckets(
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> list[str]:
    allowed = set(profile.allowed_buckets or universe.buckets)
    ordered: list[str] = []
    for bucket in universe.ordered_buckets():
        if bucket in profile.forbidden_buckets:
            continue
        if bucket not in allowed:
            continue
        theme = universe.bucket_to_theme.get(bucket)
        if theme and theme in profile.forbidden_themes:
            continue
        ordered.append(bucket)
    return ordered


def _satellite_total(weights: dict[str, float], universe: AllocationUniverse) -> float:
    return sum(
        value
        for bucket, value in weights.items()
        if universe.bucket_category.get(bucket) == "satellite"
    )


def _theme_total(weights: dict[str, float], universe: AllocationUniverse, theme: str) -> float:
    return sum(
        value
        for bucket, value in weights.items()
        if universe.bucket_to_theme.get(bucket) == theme
    )


def _qdii_total(weights: dict[str, float], universe: AllocationUniverse) -> float:
    return sum(weights.get(bucket, 0.0) for bucket in universe.qdii_buckets)


def _liquidity_total(weights: dict[str, float], universe: AllocationUniverse) -> float:
    return sum(weights.get(bucket, 0.0) for bucket in universe.liquidity_buckets)


def _increase_limit(
    bucket: str,
    weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> float:
    current = weights.get(bucket, 0.0)
    _lo, hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
    limit = max(0.0, hi - current)
    if limit <= 0:
        return 0.0
    if bucket in universe.qdii_buckets:
        if not profile.qdii_allowed:
            return 0.0
        limit = min(limit, max(0.0, constraints.qdii_cap - _qdii_total(weights, universe)))
    theme = universe.bucket_to_theme.get(bucket)
    if theme and theme in constraints.theme_caps:
        limit = min(
            limit,
            max(0.0, constraints.theme_caps[theme] - _theme_total(weights, universe, theme)),
        )
    if universe.bucket_category.get(bucket) == "satellite":
        limit = min(limit, max(0.0, constraints.satellite_cap - _satellite_total(weights, universe)))
    return max(0.0, limit)


def _decrease_limit(
    bucket: str,
    weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
) -> float:
    current = weights.get(bucket, 0.0)
    lo, _hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
    limit = max(0.0, current - lo)
    if bucket in universe.liquidity_buckets:
        limit = min(
            limit,
            max(0.0, _liquidity_total(weights, universe) - constraints.liquidity_reserve_min),
        )
    return max(0.0, limit)


def _rebalance_total(
    weights: dict[str, float],
    constraints: AccountConstraints,
    ordered_buckets: list[str],
) -> dict[str, float]:
    lowered = {}
    for bucket in ordered_buckets:
        lo, hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
        lowered[bucket] = _clamp(weights.get(bucket, 0.0), lo, hi)

    total = sum(lowered.values())
    if abs(total - 1.0) < 1e-9:
        return lowered

    if total < 1.0:
        deficit = 1.0 - total
        for bucket in ordered_buckets:
            lo, hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
            headroom = max(0.0, hi - lowered[bucket])
            add = min(headroom, deficit)
            lowered[bucket] += add
            deficit -= add
            if deficit <= 1e-9:
                break
        return lowered

    excess = total - 1.0
    for bucket in reversed(ordered_buckets):
        lo, hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
        removable = max(0.0, lowered[bucket] - lo)
        cut = min(removable, excess)
        lowered[bucket] -= cut
        excess -= cut
        if excess <= 1e-9:
            break
    return lowered


def _redistribute(
    weights: dict[str, float],
    amount: float,
    buckets: list[str],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> dict[str, float]:
    if amount <= 0 or not buckets:
        return weights
    for bucket in buckets:
        headroom = _increase_limit(bucket, weights, constraints, universe, profile)
        add = min(headroom, amount)
        weights[bucket] = weights.get(bucket, 0.0) + add
        amount -= add
        if amount <= 1e-9:
            break
    return weights


def _repair_total_after_rounding(
    weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
    ordered_buckets: list[str],
) -> dict[str, float]:
    residual = 1.0 - sum(weights.values())
    if abs(residual) <= 1e-9:
        return weights
    if residual > 0:
        for bucket in ordered_buckets:
            add = min(
                residual,
                _increase_limit(bucket, weights, constraints, universe, profile),
            )
            if add <= 0:
                continue
            weights[bucket] = weights.get(bucket, 0.0) + add
            residual -= add
            if residual <= 1e-9:
                break
        return weights
    for bucket in reversed(ordered_buckets):
        cut = min(
            -residual,
            _decrease_limit(bucket, weights, constraints, universe),
        )
        if cut <= 0:
            continue
        weights[bucket] = weights.get(bucket, 0.0) - cut
        residual += cut
        if residual >= -1e-9:
            break
    return weights


def project_to_constraints(
    draft_weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
    params: AllocationEngineParams,
) -> dict[str, float]:
    ordered_buckets = _ordered_eligible_buckets(universe, profile)
    weights = {bucket: draft_weights.get(bucket, 0.0) for bucket in ordered_buckets}
    weights = _rebalance_total(weights, constraints, ordered_buckets)

    satellite_buckets = [
        bucket for bucket in ordered_buckets if universe.bucket_category.get(bucket) == "satellite"
    ]
    satellite_total = sum(weights.get(bucket, 0.0) for bucket in satellite_buckets)
    if satellite_total > constraints.satellite_cap and satellite_total > 0:
        scale = constraints.satellite_cap / satellite_total
        for bucket in satellite_buckets:
            weights[bucket] *= scale

    if not profile.qdii_allowed:
        removed = sum(weights.get(bucket, 0.0) for bucket in universe.qdii_buckets)
        for bucket in universe.qdii_buckets:
            if bucket in weights:
                weights[bucket] = 0.0
        replenish = [bucket for bucket in ordered_buckets if bucket not in universe.qdii_buckets]
        weights = _redistribute(weights, removed, replenish, constraints, universe, profile)
    else:
        qdii_total = sum(weights.get(bucket, 0.0) for bucket in universe.qdii_buckets)
        if qdii_total > constraints.qdii_cap and qdii_total > 0:
            scale = constraints.qdii_cap / qdii_total
            removed = 0.0
            for bucket in universe.qdii_buckets:
                old = weights.get(bucket, 0.0)
                weights[bucket] = old * scale
                removed += old - weights[bucket]
            replenish = [bucket for bucket in ordered_buckets if bucket not in universe.qdii_buckets]
            weights = _redistribute(weights, removed, replenish, constraints, universe, profile)

    for theme, cap in constraints.theme_caps.items():
        themed_buckets = [
            bucket for bucket in ordered_buckets if universe.bucket_to_theme.get(bucket) == theme
        ]
        theme_total = sum(weights.get(bucket, 0.0) for bucket in themed_buckets)
        if theme_total > cap and theme_total > 0:
            scale = cap / theme_total
            removed = 0.0
            for bucket in themed_buckets:
                old = weights.get(bucket, 0.0)
                weights[bucket] = old * scale
                removed += old - weights[bucket]
            replenish = [bucket for bucket in ordered_buckets if bucket not in themed_buckets]
            weights = _redistribute(weights, removed, replenish, constraints, universe, profile)

    liquidity_total = sum(weights.get(bucket, 0.0) for bucket in universe.liquidity_buckets)
    if universe.liquidity_buckets and liquidity_total < constraints.liquidity_reserve_min:
        need = constraints.liquidity_reserve_min - liquidity_total
        shifted = 0.0
        donors = [bucket for bucket in reversed(ordered_buckets) if bucket not in universe.liquidity_buckets]
        for bucket in donors:
            removable = _decrease_limit(bucket, weights, constraints, universe)
            cut = min(removable, need)
            weights[bucket] -= cut
            need -= cut
            shifted += cut
            if need <= 1e-9:
                break
        weights = _redistribute(
            weights,
            shifted,
            universe.liquidity_buckets,
            constraints,
            universe,
            profile,
        )

    rounded = {
        bucket: round(max(0.0, value), params.weight_round_digits)
        for bucket, value in weights.items()
        if value > params.zero_clip_threshold or bucket in constraints.ips_bucket_boundaries
    }
    return _repair_total_after_rounding(
        rounded,
        constraints,
        universe,
        profile,
        ordered_buckets,
    )
