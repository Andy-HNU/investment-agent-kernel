from __future__ import annotations

from product_mapping.cardinality import BucketCountResolution
from product_mapping.explanations import BucketConstructionExplanation
from product_mapping.relationships import has_high_duplicate_exposure, rank_construction_candidates, score_candidate_subset
from product_mapping.types import RuntimeProductCandidate


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
    ranked = rank_construction_candidates(bucket, candidates)
    selected = [ranked[0]]
    remaining = ranked[1:]
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
    ranked = rank_construction_candidates(bucket, candidates)
    selected = [ranked[0]]
    remaining = ranked[1:]
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
    candidates: list[RuntimeProductCandidate],
    is_explicit_request: bool,
) -> list[str]:
    actual_count = len(selected_members)
    desired_count = int(requested_resolution.requested_count or requested_resolution.resolved_count)
    domestic_pool = _domestic_only_pool(candidates)
    codes: list[str] = []
    if actual_count < desired_count or (is_explicit_request and bucket in _SINGLE_PRODUCT_BUCKETS and desired_count > 1):
        if len(domestic_pool) < desired_count:
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
) -> list[RuntimeProductCandidate]:
    if not candidates:
        return []
    working_pool = _domestic_only_pool(candidates)
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
) -> BucketConstructionExplanation:
    actual_count = len(selected_members)
    requested_count = requested_resolution.requested_count
    desired_count = int(requested_count or requested_resolution.resolved_count)
    is_explicit_request = requested_resolution.source in {"explicit_user", "persisted_user"}
    diagnostic_codes = _diagnostic_codes(
        bucket=bucket,
        bucket_weight=bucket_weight,
        requested_resolution=requested_resolution,
        selected_members=selected_members,
        candidates=candidates,
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
        domestic_pool = _domestic_only_pool(candidates)
        if len(domestic_pool) < desired_count:
            reasons.append(
                f"requested_count={desired_count} exceeds domestic candidate supply ({len(domestic_pool)})"
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
