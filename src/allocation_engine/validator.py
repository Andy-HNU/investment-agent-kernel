from __future__ import annotations

from allocation_engine.types import AllocationEngineInput, AllocationProfile, AllocationUniverse
from goal_solver.types import AccountConstraints


def validate_allocation_input(inp: AllocationEngineInput) -> list[str]:
    issues: list[str] = []
    universe = inp.universe
    constraints = inp.constraints
    profile = inp.account_profile
    if inp.params.min_candidates <= 0 or inp.params.max_candidates <= 0:
        issues.append("candidate counts must be positive")
    if inp.params.min_candidates > inp.params.max_candidates:
        issues.append("min_candidates cannot exceed max_candidates")
    if not universe.buckets:
        issues.append("universe.buckets cannot be empty")
    if set(universe.bucket_category) != set(universe.buckets):
        issues.append("bucket_category must fully cover universe.buckets")
    if set(universe.bucket_to_theme) != set(universe.buckets):
        issues.append("bucket_to_theme must fully cover universe.buckets")
    if not set(universe.qdii_buckets).issubset(set(universe.buckets)):
        issues.append("qdii_buckets must be a subset of universe.buckets")
    if not set(universe.liquidity_buckets).issubset(set(universe.buckets)):
        issues.append("liquidity_buckets must be a subset of universe.buckets")
    if not set(profile.allowed_buckets or universe.buckets).issubset(set(universe.buckets)):
        issues.append("allowed_buckets must be a subset of universe.buckets")
    if not set(profile.forbidden_buckets).issubset(set(universe.buckets)):
        issues.append("forbidden_buckets must be a subset of universe.buckets")
    if set(constraints.ips_bucket_boundaries) != set(universe.buckets):
        issues.append("ips_bucket_boundaries must fully cover universe.buckets")
    if set(constraints.ips_bucket_boundaries) - set(universe.buckets):
        issues.append("ips_bucket_boundaries contains unknown buckets")
    return issues


def validate_candidate(
    weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> list[str]:
    notes: list[str] = []
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        notes.append(f"weights sum drifted to {total:.4f}")
    for bucket, value in weights.items():
        if bucket not in universe.buckets:
            notes.append(f"{bucket} is not in allocation universe")
            continue
        if value < -1e-9:
            notes.append(f"{bucket} has negative weight")
        lo, hi = constraints.ips_bucket_boundaries.get(bucket, (0.0, 1.0))
        if value < lo - 1e-6 or value > hi + 1e-6:
            notes.append(f"{bucket} out of bounds")
        if bucket in profile.forbidden_buckets and value > 0:
            notes.append(f"{bucket} is forbidden but allocated")
        theme = universe.bucket_to_theme.get(bucket)
        if theme and theme in profile.forbidden_themes and value > 0:
            notes.append(f"{theme} theme is forbidden but allocated")

    satellite_total = sum(
        value for bucket, value in weights.items() if universe.bucket_category.get(bucket) == "satellite"
    )
    if satellite_total > constraints.satellite_cap + 1e-6:
        notes.append("satellite cap exceeded")

    qdii_total = sum(weights.get(bucket, 0.0) for bucket in universe.qdii_buckets)
    if not profile.qdii_allowed and qdii_total > 1e-6:
        notes.append("qdii allocation present while qdii_allowed is False")
    if qdii_total > constraints.qdii_cap + 1e-6:
        notes.append("qdii cap exceeded")

    liquidity_total = sum(weights.get(bucket, 0.0) for bucket in universe.liquidity_buckets)
    if liquidity_total + 1e-6 < constraints.liquidity_reserve_min:
        notes.append("liquidity reserve below minimum")

    for theme, cap in constraints.theme_caps.items():
        theme_total = sum(
            value
            for bucket, value in weights.items()
            if universe.bucket_to_theme.get(bucket) == theme
        )
        if theme_total > cap + 1e-6:
            notes.append(f"{theme} cap exceeded")
    return notes
