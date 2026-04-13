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
_GENERIC_THEME_TAGS = {
    "cn",
    "cash",
    "core",
    "defense",
    "equity",
    "etf",
    "fund",
    "liquidity",
    "satellite",
    "stock",
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


def _candidate_family(candidate: RuntimeProductCandidate | object) -> str:
    product = _candidate(candidate)
    return str(getattr(product, "product_family", "") or "").strip().lower()


def _candidate_theme_tags(candidate: RuntimeProductCandidate | object) -> set[str]:
    tags = _candidate_tags(candidate)
    theme_tags = {tag for tag in tags if tag not in _GENERIC_THEME_TAGS}
    if theme_tags:
        return theme_tags
    family = _candidate_family(candidate)
    return {family} if family else set()


def _candidate_theme_signature(candidate: RuntimeProductCandidate | object) -> tuple[str, ...]:
    return tuple(sorted(_candidate_theme_tags(candidate)))


def pairwise_duplicate_exposure_score(
    left: RuntimeProductCandidate,
    right: RuntimeProductCandidate,
) -> float:
    left_product = left.candidate
    right_product = right.candidate
    score = 0.0
    if str(left_product.asset_bucket or "").strip() == str(right_product.asset_bucket or "").strip():
        score += 0.08
    if str(left_product.region or "").strip().upper() == str(right_product.region or "").strip().upper():
        score += 0.08
    if _candidate_family(left) == _candidate_family(right):
        score += 0.40
    if _candidate_theme_signature(left) == _candidate_theme_signature(right):
        score += 0.32
    if left_product.wrapper_type == right_product.wrapper_type:
        score += 0.08
    shared_tags = _candidate_theme_tags(left).intersection(_candidate_theme_tags(right))
    score += min(len(shared_tags), 3) * 0.05
    shared_risk_labels = _candidate_risk_labels(left).intersection(_candidate_risk_labels(right))
    score += min(len(shared_risk_labels), 2) * 0.05
    if "qdii" in _candidate_tags(left) or "qdii" in _candidate_tags(right) or "overseas" in _candidate_tags(left) or "overseas" in _candidate_tags(right):
        score += 0.12
    return round(score, 6)


def _subset_duplicate_exposure_score(members: Iterable[RuntimeProductCandidate]) -> float:
    selected = list(members)
    if len(selected) <= 1:
        return 0.0
    return round(max(pairwise_duplicate_exposure_score(left, right) for left, right in combinations(selected, 2)), 6)


def has_high_duplicate_exposure(
    members: Iterable[RuntimeProductCandidate],
    *,
    threshold: float = 0.75,
) -> bool:
    return _subset_duplicate_exposure_score(members) >= float(threshold)


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
    left_tags = _candidate_theme_tags(left)
    right_tags = _candidate_theme_tags(right)
    if _candidate_family(left) == _candidate_family(right):
        score -= 0.14
    if _candidate_theme_signature(left) == _candidate_theme_signature(right):
        score -= 0.18
    shared_tags = left_tags.intersection(right_tags)
    score += min(len(shared_tags), 3) * 0.08
    if left_product.wrapper_type == right_product.wrapper_type:
        score -= 0.05
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
    family_diversity = len({_candidate_family(item) for item in selected}) * 0.06
    theme_diversity = len({_candidate_theme_signature(item) for item in selected}) * 0.05
    return round(base_score + pairwise_score + wrapper_diversity + region_diversity + family_diversity + theme_diversity, 6)


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


__all__ = [
    "has_high_duplicate_exposure",
    "pairwise_duplicate_exposure_score",
    "rank_construction_candidates",
    "score_candidate_subset",
    "score_construction_relation",
]
