from __future__ import annotations

from product_mapping.cardinality import BucketCountResolution
from product_mapping.explanations import BucketConstructionExplanation
from product_mapping.relationships import has_high_duplicate_exposure, rank_construction_candidates, score_candidate_subset
from product_mapping.search_expansion import SearchExpansionLevels, candidate_pool_limit
from product_mapping.types import RecommendationRankingContext, RuntimeProductCandidate


_SINGLE_PRODUCT_BUCKETS = {"gold", "cash_liquidity"}
_MIN_MEMBER_WEIGHT_BY_BUCKET = {
    "equity_cn": 0.05,
    "bond_cn": 0.05,
    "gold": 0.10,
    "cash_liquidity": 0.10,
    "satellite": 0.02,
}
_AUTO_EXPANSION_GAIN_THRESHOLD_BY_BUCKET = {
    "equity_cn": 0.015,
    "bond_cn": 0.010,
    "satellite": 0.015,
}
_AUTO_DUPLICATE_GUARD_GAIN_THRESHOLD_BY_BUCKET = {
    "equity_cn": 0.045,
    "bond_cn": 0.030,
    "satellite": 0.035,
}
_RISK_SEEKING_PREFERENCE = {"aggressive", "growth", "进取"}
_RISK_DEFENSIVE_PREFERENCE = {"conservative", "稳健", "保守"}


def _candidate_tags(runtime_candidate: RuntimeProductCandidate) -> set[str]:
    return {
        str(tag).strip().lower()
        for tag in list(runtime_candidate.candidate.tags or [])
        if str(tag).strip()
    }


def _ranking_context(
    ranking_context: RecommendationRankingContext | None,
) -> RecommendationRankingContext:
    return ranking_context if ranking_context is not None else RecommendationRankingContext()


def profile_aware_candidate_sort_key(
    runtime_candidate: RuntimeProductCandidate,
    *,
    bucket: str,
    ranking_context: RecommendationRankingContext | None,
) -> tuple[float, ...]:
    context = _ranking_context(ranking_context)
    tags = _candidate_tags(runtime_candidate)
    policy_score = 0.0
    if runtime_candidate.policy_news_audit is not None:
        policy_score = float(runtime_candidate.policy_news_audit.score or 0.0)

    effective_required_return = max(float(context.required_annual_return or 0.0), 0.0)
    effective_horizon = max(int(context.goal_horizon_months or 0), 0)
    effective_drawdown = (
        0.20 if context.max_drawdown_tolerance is None else max(float(context.max_drawdown_tolerance), 0.0)
    )
    effective_pressure = max(float(context.market_pressure_score or 0.0), 0.0)
    normalized_risk_preference = str(context.risk_preference or "").strip().lower()

    growth_intensity = 0.0
    if effective_required_return >= 0.10:
        growth_intensity += min((effective_required_return - 0.10) / 0.06, 1.0)
    if effective_horizon >= 36:
        growth_intensity += min((effective_horizon - 36) / 36, 1.0) * 0.5
    if normalized_risk_preference in _RISK_SEEKING_PREFERENCE:
        growth_intensity += 0.3

    defensive_intensity = 0.0
    if effective_drawdown <= 0.12:
        defensive_intensity += min((0.12 - effective_drawdown) / 0.07, 1.0)
    if effective_pressure >= 60.0:
        defensive_intensity += min((effective_pressure - 60.0) / 30.0, 1.0)
    if normalized_risk_preference in _RISK_DEFENSIVE_PREFERENCE:
        defensive_intensity += 0.3

    profile_score = 0.0
    if bucket == "equity_cn":
        if "dividend" in tags:
            profile_score += growth_intensity * 1.15
        if "broad_market" in tags:
            profile_score += growth_intensity * 0.85
        if "low_vol" in tags or "defense" in tags:
            profile_score += defensive_intensity * 1.70
        if "core" in tags and defensive_intensity > 0.0:
            profile_score += defensive_intensity * 0.30
    elif bucket == "satellite":
        if "technology" in tags:
            profile_score += growth_intensity * 0.40
        if "cyclical" in tags:
            profile_score += growth_intensity * 0.18
        if "defense" in tags or "low_vol" in tags:
            profile_score += defensive_intensity * 0.70
        if "qdii" in tags or "overseas" in tags:
            profile_score -= defensive_intensity * 0.35
        profile_score += policy_score * (0.05 + growth_intensity * 0.10)
    elif bucket == "bond_cn":
        # Keep bond selection coarse and stable: ordering falls back to the
        # existing static rank instead of reacting to profile/news noise.
        profile_score += 0.0
    else:
        profile_score += policy_score * 0.02

    return (round(-profile_score, 6),)


def _working_pool_details(
    *,
    bucket: str,
    candidates: list[RuntimeProductCandidate],
    search_expansion_level: str,
    ranking_context: RecommendationRankingContext | None,
) -> tuple[list[RuntimeProductCandidate], list[RuntimeProductCandidate], bool]:
    domestic_pool = _domestic_only_pool(candidates)
    static_rank = {
        candidate.candidate.product_id: index
        for index, candidate in enumerate(rank_construction_candidates(bucket, domestic_pool))
    }
    ordered_pool = sorted(
        domestic_pool,
        key=lambda candidate: (
            profile_aware_candidate_sort_key(
                candidate,
                bucket=bucket,
                ranking_context=ranking_context,
            ),
            float(static_rank.get(candidate.candidate.product_id, len(static_rank))),
            candidate.candidate.product_id,
        ),
    )
    pool_limit = candidate_pool_limit(bucket, search_expansion_level)
    working_pool = ordered_pool[:pool_limit]
    return domestic_pool, working_pool, len(ordered_pool) > len(working_pool)


def _is_domestic_candidate(candidate: RuntimeProductCandidate) -> bool:
    product = candidate.candidate
    region = str(product.region or "").strip().upper()
    tags = {str(tag).strip().lower() for tag in list(product.tags or []) if str(tag).strip()}
    return region == "CN" and "qdii" not in tags and "overseas" not in tags


def _domestic_only_pool(candidates: list[RuntimeProductCandidate]) -> list[RuntimeProductCandidate]:
    domestic = [candidate for candidate in candidates if _is_domestic_candidate(candidate)]
    return domestic or list(candidates)


def _desired_count(resolution: BucketCountResolution) -> int:
    return int(resolution.requested_count or resolution.resolved_count)


def _auto_minimum_count(resolution: BucketCountResolution) -> int:
    return max(1, int(resolution.resolved_count))


def _expansion_gain_threshold(bucket: str) -> float:
    return float(_AUTO_EXPANSION_GAIN_THRESHOLD_BY_BUCKET.get(bucket, 0.015))


def _duplicate_guard_gain_threshold(bucket: str) -> float:
    return float(_AUTO_DUPLICATE_GUARD_GAIN_THRESHOLD_BY_BUCKET.get(bucket, 0.03))


def _select_subset(bucket: str, candidates: list[RuntimeProductCandidate], count: int) -> list[RuntimeProductCandidate]:
    if count <= 0 or not candidates:
        return []
    selected = [candidates[0]]
    remaining = list(candidates[1:])
    while len(selected) < count and remaining:
        best_index = 0
        best_score = float("-inf")
        for index, candidate in enumerate(remaining):
            subset_score = score_candidate_subset(bucket, [*selected, candidate])
            if subset_score > best_score:
                best_score = subset_score
                best_index = index
            elif subset_score == best_score and candidate.candidate.product_id < remaining[best_index].candidate.product_id:
                best_index = index
        selected.append(remaining.pop(best_index))
    return selected


def _select_auto_subset(
    bucket: str,
    candidates: list[RuntimeProductCandidate],
    *,
    minimum_count: int,
    bucket_weight: float,
) -> list[RuntimeProductCandidate]:
    if not candidates:
        return []
    selected = [candidates[0]]
    remaining = list(candidates[1:])
    current_score = score_candidate_subset(bucket, selected)
    minimum_member_weight = float(_MIN_MEMBER_WEIGHT_BY_BUCKET.get(bucket, 0.05) or 0.05)
    gain_threshold = _expansion_gain_threshold(bucket)
    duplicate_guard_gain_threshold = _duplicate_guard_gain_threshold(bucket)

    while remaining:
        if len(selected) >= 1 and float(bucket_weight) / float(len(selected) + 1) < minimum_member_weight:
            break

        best_index = 0
        best_subset_score = float("-inf")
        best_candidate_id = ""
        for index, candidate in enumerate(remaining):
            subset = [*selected, candidate]
            subset_score = score_candidate_subset(bucket, subset)
            candidate_id = candidate.candidate.product_id
            if subset_score > best_subset_score or (
                subset_score == best_subset_score and candidate_id < best_candidate_id
            ):
                best_subset_score = subset_score
                best_index = index
                best_candidate_id = candidate_id

        gain = best_subset_score - current_score
        next_selected = [*selected, remaining[best_index]]
        duplicate_high = has_high_duplicate_exposure(next_selected)

        if len(selected) >= minimum_count and (
            gain <= gain_threshold or (duplicate_high and gain <= duplicate_guard_gain_threshold)
        ):
            break

        selected.append(remaining.pop(best_index))
        current_score = best_subset_score

    return selected


def _has_duplicate_exposure_too_high(members: list[RuntimeProductCandidate]) -> bool:
    return has_high_duplicate_exposure(members)


def _diagnostic_codes(
    *,
    bucket: str,
    bucket_weight: float,
    requested_resolution: BucketCountResolution,
    selected_members: list[RuntimeProductCandidate],
    domestic_pool: list[RuntimeProductCandidate],
    working_pool: list[RuntimeProductCandidate],
    working_pool_trimmed: bool,
    is_explicit_request: bool,
) -> list[str]:
    actual_count = len(selected_members)
    desired_count = int(requested_resolution.requested_count or requested_resolution.resolved_count)
    codes: list[str] = []
    search_expansion_pool_limited = (
        working_pool_trimmed and len(working_pool) < desired_count and len(domestic_pool) >= desired_count
    )
    if actual_count < desired_count or (is_explicit_request and bucket in _SINGLE_PRODUCT_BUCKETS and desired_count > 1):
        if search_expansion_pool_limited:
            codes.append("search_expansion_pool_limit")
        elif len(working_pool) < desired_count:
            codes.append("insufficient_eligible_candidates")
        if actual_count <= 1 and desired_count > 1:
            codes.append("estimated_only_member_required")
    if is_explicit_request and desired_count > 1 and float(bucket_weight) / max(desired_count, 1) < float(_MIN_MEMBER_WEIGHT_BY_BUCKET.get(bucket, 0.05) or 0.05):
        codes.append("minimum_weight_breach")
        codes.append("count_preference_not_fully_satisfied")
    if _has_duplicate_exposure_too_high(selected_members):
        codes.append("duplicate_exposure_too_high")
    if actual_count > 1 and score_candidate_subset(bucket, selected_members) <= score_candidate_subset(bucket, selected_members[:1]) + 0.05:
        codes.append("insufficient_diversification_gain")
    if bucket == "bond_cn" and requested_resolution.source == "auto_policy" and actual_count == 1 and desired_count > 1:
        codes.append("formal_path_coverage_insufficient")
    return list(dict.fromkeys(codes))


def split_bucket_weight(target_weight: float, member_count: int) -> list[float]:
    if member_count <= 1:
        return [round(float(target_weight), 4)]
    total = round(float(target_weight), 4)
    base = round(total / float(member_count), 4)
    weights = [base for _ in range(member_count)]
    remainder = round(total - sum(weights), 4)
    if weights:
        weights[-1] = round(weights[-1] + remainder, 4)
    return weights


def build_bucket_subset(
    *,
    bucket: str,
    bucket_weight: float,
    requested_resolution: BucketCountResolution,
    candidates: list[RuntimeProductCandidate],
    search_expansion_level: str = SearchExpansionLevels.L0_COMPACT,
    ranking_context: RecommendationRankingContext | None = None,
) -> list[RuntimeProductCandidate]:
    if not candidates:
        return []
    _, working_pool, _ = _working_pool_details(
        bucket=bucket,
        candidates=candidates,
        search_expansion_level=search_expansion_level,
        ranking_context=ranking_context,
    )
    desired_count = _desired_count(requested_resolution)
    is_explicit_request = requested_resolution.source in {"explicit_user", "persisted_user"}
    if bucket in _SINGLE_PRODUCT_BUCKETS:
        capped_count = 1
    elif is_explicit_request:
        capped_count = min(desired_count, len(working_pool))
    else:
        return _select_auto_subset(
            bucket,
            working_pool,
            minimum_count=_auto_minimum_count(requested_resolution),
            bucket_weight=float(bucket_weight),
        )
    return _select_subset(bucket, working_pool, max(1, capped_count))


def build_bucket_construction_explanation(
    *,
    bucket: str,
    bucket_weight: float,
    requested_resolution: BucketCountResolution,
    selected_members: list[RuntimeProductCandidate],
    candidates: list[RuntimeProductCandidate],
    search_expansion_level: str = SearchExpansionLevels.L0_COMPACT,
    ranking_context: RecommendationRankingContext | None = None,
) -> BucketConstructionExplanation:
    actual_count = len(selected_members)
    requested_count = requested_resolution.requested_count
    desired_count = int(requested_count or requested_resolution.resolved_count)
    is_explicit_request = requested_resolution.source in {"explicit_user", "persisted_user"}
    domestic_pool, working_pool, working_pool_trimmed = _working_pool_details(
        bucket=bucket,
        candidates=candidates,
        search_expansion_level=search_expansion_level,
        ranking_context=ranking_context,
    )
    diagnostic_codes = _diagnostic_codes(
        bucket=bucket,
        bucket_weight=bucket_weight,
        requested_resolution=requested_resolution,
        selected_members=selected_members,
        domestic_pool=domestic_pool,
        working_pool=working_pool,
        working_pool_trimmed=working_pool_trimmed,
        is_explicit_request=is_explicit_request,
    )
    count_satisfied = actual_count >= desired_count and (
        requested_resolution.source == "auto_policy" or not diagnostic_codes
    )
    minimum_weight = float(_MIN_MEMBER_WEIGHT_BY_BUCKET.get(bucket, 0.05) or 0.05)
    reasons: list[str] = []
    if bucket in _SINGLE_PRODUCT_BUCKETS:
        reasons.append(f"bucket {bucket} remains single-product")
    if actual_count < desired_count:
        search_expansion_pool_limited = (
            working_pool_trimmed and len(working_pool) < desired_count and len(domestic_pool) >= desired_count
        )
        if search_expansion_pool_limited:
            reasons.append(
                "search_expansion_level="
                f"{search_expansion_level} limited working pool to {len(working_pool)} of {len(domestic_pool)} eligible candidates"
            )
        elif len(working_pool) < desired_count:
            reasons.append(
                f"requested_count={desired_count} exceeds domestic candidate supply ({len(working_pool)})"
            )
        if float(bucket_weight) / max(desired_count, 1) < minimum_weight:
            reasons.append(
                f"requested_count={desired_count} would put each member below minimum position threshold of {minimum_weight:.0%}"
            )
        if requested_resolution.source == "auto_policy" and bucket == "bond_cn" and actual_count < desired_count:
            reasons.append("bond_cn auto policy limits construction to a coarse two-product split")
        if not reasons:
            reasons.append(
                f"requested_count={desired_count} could not be realized within the available candidate set"
            )
    elif is_explicit_request and desired_count > 1 and float(bucket_weight) / max(desired_count, 1) < minimum_weight:
        reasons.append(f"minimum_weight_breach={minimum_weight:.0%}")
        reasons.append("count_preference_not_fully_satisfied")
    if actual_count > 1 and not reasons:
        reasons.append(f"bucket {bucket} is split across {actual_count} domestic members for construction-time diversification")
    if actual_count <= 1 and bucket not in _SINGLE_PRODUCT_BUCKETS and not reasons:
        reasons.append(f"bucket {bucket} stays concentrated in the highest-ranked domestic candidate")
    member_roles: dict[str, str] = {}
    for index, member in enumerate(selected_members):
        member_roles[member.candidate.product_id] = "primary" if index == 0 else f"secondary_{index}"
    no_split_counterfactual = []
    if actual_count > 1:
        no_split_counterfactual.append("single_product_counterfactual")
    return BucketConstructionExplanation(
        bucket=bucket,
        requested_count=requested_count,
        actual_count=actual_count,
        count_source=requested_resolution.source,
        count_satisfied=count_satisfied,
        unmet_reason=None
        if count_satisfied
        else "; ".join(reasons)
        if reasons
        else "requested bucket count could not be fully satisfied",
        diagnostic_codes=diagnostic_codes,
        why_split=reasons,
        no_split_counterfactual=no_split_counterfactual,
        member_roles=member_roles,
    )
