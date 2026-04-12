from __future__ import annotations

from itertools import combinations
from typing import Iterable

from product_mapping.types import RuntimeProductCandidate


_LIQUIDITY_PRIORITY = {"high": 3.0, "medium": 2.0, "low": 1.0}
_FEE_PRIORITY = {"low": 1.0, "medium": 0.5, "high": 0.0}
_WRAPPER_PRIORITY = {
    "etf": 0.8,
    "cash_mgmt": 0.7,
    "fund": 0.5,
    "bond": 0.4,
    "stock": 0.2,
    "other": 0.0,
}


def _candidate(candidate: RuntimeProductCandidate | object) -> object:
    return candidate.candidate if isinstance(candidate, RuntimeProductCandidate) else candidate


def _candidate_tags(candidate: RuntimeProductCandidate | object) -> set[str]:
    product = _candidate(candidate)
    return {str(tag).strip().lower() for tag in list(getattr(product, "tags", []) or []) if str(tag).strip()}


def _candidate_risk_labels(candidate: RuntimeProductCandidate | object) -> set[str]:
    product = _candidate(candidate)
    return {
        str(label).strip().lower()
        for label in list(getattr(product, "risk_labels", []) or [])
        if str(label).strip()
    }


def _construction_prior_score(bucket: str, candidate: RuntimeProductCandidate) -> float:
    product = candidate.candidate
    score = 0.0
    score += _LIQUIDITY_PRIORITY.get(product.liquidity_tier, 1.0)
    score += _FEE_PRIORITY.get(product.fee_tier, 0.0)
    score += _WRAPPER_PRIORITY.get(product.wrapper_type, 0.0)
    if str(product.region or "").strip().upper() == "CN":
        score += 0.8
    else:
        score -= 1.2
    tags = _candidate_tags(candidate)
    if "qdii" in tags or "overseas" in tags:
        score -= 1.0
    if bucket == "equity_cn":
        if "core" in tags:
            score += 0.4
        if "equity" in tags:
            score += 0.2
    elif bucket == "satellite":
        if tags.intersection({"technology", "cyclical", "satellite"}):
            score += 0.4
        if "qdii" not in tags:
            score += 0.2
    elif bucket == "bond_cn":
        if "defense" in tags:
            score += 0.3
    elif bucket == "gold":
        if "defense" in tags:
            score += 0.3
    elif bucket == "cash_liquidity":
        if "cash" in tags:
            score += 0.3
    return round(score, 6)


def score_construction_relation(
    left: RuntimeProductCandidate,
    right: RuntimeProductCandidate,
) -> float:
    left_product = left.candidate
    right_product = right.candidate
    score = 0.0
    same_region = str(left_product.region or "").strip().upper() == str(right_product.region or "").strip().upper()
    if same_region and str(left_product.region or "").strip().upper() == "CN":
        score += 0.2
    elif not same_region:
        score -= 1.0
    left_tags = _candidate_tags(left)
    right_tags = _candidate_tags(right)
    shared_tags = left_tags.intersection(right_tags)
    score += min(len(shared_tags), 3) * 0.12
    if left_product.wrapper_type == right_product.wrapper_type:
        score -= 0.08
    else:
        score += 0.05
    shared_risk_labels = _candidate_risk_labels(left).intersection(_candidate_risk_labels(right))
    score -= min(len(shared_risk_labels), 2) * 0.08
    if "qdii" in left_tags or "qdii" in right_tags or "overseas" in left_tags or "overseas" in right_tags:
        score -= 0.6
    return round(score, 6)


def score_candidate_subset(bucket: str, members: Iterable[RuntimeProductCandidate]) -> float:
    selected = list(members)
    if not selected:
        return float("-inf")
    base_score = sum(_construction_prior_score(bucket, item) for item in selected) / len(selected)
    if len(selected) == 1:
        return round(base_score, 6)
    pairwise_scores = [score_construction_relation(left, right) for left, right in combinations(selected, 2)]
    pairwise_score = sum(pairwise_scores) / len(pairwise_scores)
    wrapper_diversity = len({item.candidate.wrapper_type for item in selected}) * 0.08
    region_diversity = len({str(item.candidate.region or "").strip().upper() for item in selected}) * 0.04
    return round(base_score + pairwise_score + wrapper_diversity + region_diversity, 6)


def rank_construction_candidates(
    bucket: str,
    candidates: list[RuntimeProductCandidate],
) -> list[RuntimeProductCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -_construction_prior_score(bucket, candidate),
            candidate.candidate.product_id,
        ),
    )
