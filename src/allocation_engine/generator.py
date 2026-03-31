from __future__ import annotations

from allocation_engine.types import AllocationProfile, AllocationTemplate, AllocationUniverse


def _ordered_category_buckets(
    universe: AllocationUniverse,
    profile: AllocationProfile,
    category: str,
) -> list[str]:
    allowed = set(profile.allowed_buckets or universe.buckets)
    ordered = []
    for bucket in universe.ordered_buckets():
        if universe.bucket_category.get(bucket) != category:
            continue
        if bucket not in allowed or bucket in profile.forbidden_buckets:
            continue
        theme = universe.bucket_to_theme.get(bucket)
        if theme and theme in profile.forbidden_themes:
            continue
        ordered.append(bucket)
    return ordered


def _theme_buckets(
    universe: AllocationUniverse,
    profile: AllocationProfile,
    theme: str | None,
) -> list[str]:
    if not theme:
        return []
    return [
        bucket
        for bucket in universe.ordered_buckets()
        if bucket not in profile.forbidden_buckets
        and bucket in (profile.allowed_buckets or universe.buckets)
        and universe.bucket_to_theme.get(bucket) == theme
    ]


def _normalize_weights(weights: dict[str, float], ordered_buckets: list[str]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        equal = 1.0 / max(len(ordered_buckets), 1)
        return {bucket: equal for bucket in ordered_buckets}
    return {bucket: value / total for bucket, value in weights.items()}


def instantiate_template(
    template: AllocationTemplate,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> dict[str, float]:
    weights = {bucket: 0.0 for bucket in universe.buckets}
    category_targets = {
        "core": template.target_core_weight,
        "defense": template.target_defense_weight,
        "satellite": template.target_satellite_weight,
    }
    for category, total in category_targets.items():
        buckets = _ordered_category_buckets(universe, profile, category)
        if not buckets or total <= 0:
            continue
        per_bucket = total / len(buckets)
        for bucket in buckets:
            weights[bucket] += per_bucket

    theme_buckets = _theme_buckets(universe, profile, template.preferred_theme)
    if theme_buckets and template.theme_tilt_strength > 0:
        bonus = template.theme_tilt_strength / len(theme_buckets)
        for bucket in theme_buckets:
            weights[bucket] += bonus
        non_theme = [bucket for bucket in universe.buckets if bucket not in theme_buckets]
        if non_theme:
            penalty = template.theme_tilt_strength / len(non_theme)
            for bucket in non_theme:
                weights[bucket] = max(0.0, weights[bucket] - penalty)

    if template.liquidity_buffer_bonus > 0 and universe.liquidity_buckets:
        bonus = template.liquidity_buffer_bonus / len(universe.liquidity_buckets)
        for bucket in universe.liquidity_buckets:
            weights[bucket] += bonus

    return _normalize_weights(weights, universe.ordered_buckets())
