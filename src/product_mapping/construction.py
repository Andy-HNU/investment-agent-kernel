from __future__ import annotations

from math import floor

from product_mapping.cardinality import BucketCountResolution
from product_mapping.explanations import BucketConstructionExplanation
from product_mapping.relationships import rank_construction_candidates, score_candidate_subset
from product_mapping.types import RuntimeProductCandidate


_SINGLE_PRODUCT_BUCKETS = {"gold", "cash_liquidity"}
_MIN_MEMBER_WEIGHT_BY_BUCKET = {
    "equity_cn": 0.05,
    "bond_cn": 0.05,
    "gold": 0.10,
    "cash_liquidity": 0.10,
    "satellite": 0.02,
}


def _is_domestic_candidate(candidate: RuntimeProductCandidate) -> bool:
    product = candidate.candidate
    region = str(product.region or "").strip().upper()
    tags = {str(tag).strip().lower() for tag in list(product.tags or []) if str(tag).strip()}
    return region == "CN" and "qdii" not in tags and "overseas" not in tags


def _domestic_only_pool(candidates: list[RuntimeProductCandidate]) -> list[RuntimeProductCandidate]:
    domestic = [candidate for candidate in candidates if _is_domestic_candidate(candidate)]
    return domestic or list(candidates)


def _minimum_position_member_cap(bucket: str, bucket_weight: float) -> int:
    minimum_weight = float(_MIN_MEMBER_WEIGHT_BY_BUCKET.get(bucket, 0.05) or 0.05)
    if minimum_weight <= 0.0:
        return 1
    return max(1, int(floor(float(bucket_weight) / minimum_weight + 1e-9)))


def _desired_count(resolution: BucketCountResolution) -> int:
    return int(resolution.requested_count or resolution.resolved_count)


def _policy_cap(bucket: str, resolution: BucketCountResolution, candidate_count: int) -> int:
    if bucket in _SINGLE_PRODUCT_BUCKETS:
        return 1
    if bucket == "bond_cn" and resolution.source == "auto_policy":
        return min(2, candidate_count)
    return candidate_count


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
        capped_count = min(
            desired_count,
            _policy_cap(bucket, requested_resolution, len(working_pool)),
            _minimum_position_member_cap(bucket, float(bucket_weight)),
            len(working_pool),
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
    count_satisfied = actual_count >= desired_count
    minimum_weight = float(_MIN_MEMBER_WEIGHT_BY_BUCKET.get(bucket, 0.05) or 0.05)
    is_explicit_request = requested_resolution.source in {"explicit_user", "persisted_user"}
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
        reasons.append(
            f"explicit_request_honored_despite_minimum_position_guidance={minimum_weight:.0%}"
        )
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
        why_split=reasons,
        no_split_counterfactual=no_split_counterfactual,
        member_roles=member_roles,
    )
