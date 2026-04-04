from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from shared.profile_parser import parse_profile_semantics

from product_mapping.catalog import load_builtin_catalog
from product_mapping.types import (
    CandidateFilterBreakdown,
    CandidateFilterStage,
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    RuntimeProductCandidate,
)


_BUCKET_ALIASES = {
    "cash": "cash_liquidity",
    "cash / liquidity": "cash_liquidity",
    "cash/liquidity": "cash_liquidity",
    "cash_liquidity": "cash_liquidity",
    "liquidity": "cash_liquidity",
}
_LIQUIDITY_PRIORITY = {"high": 0, "medium": 1, "low": 2}
_FEE_PRIORITY = {"low": 0, "medium": 1, "high": 2}
_WRAPPER_PRIORITY = {
    ("equity_cn", "etf"): 0,
    ("bond_cn", "etf"): 0,
    ("bond_cn", "fund"): 1,
    ("gold", "etf"): 0,
    ("gold", "fund"): 1,
    ("cash_liquidity", "cash_mgmt"): 0,
    ("cash_liquidity", "fund"): 1,
}


@dataclass(frozen=True)
class _RestrictionFilter:
    allowed_buckets: set[str]
    forbidden_buckets: set[str]
    allowed_wrappers: set[str]
    forbidden_wrappers: set[str]
    qdii_allowed: bool | None
    warnings: list[str]


def _normalize_bucket(bucket: str) -> str:
    normalized = str(bucket).strip().lower()
    return _BUCKET_ALIASES.get(normalized, normalized)


def _normalize_bucket_targets(bucket_targets: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for bucket, weight in bucket_targets.items():
        canonical_bucket = _normalize_bucket(bucket)
        normalized[canonical_bucket] = round(normalized.get(canonical_bucket, 0.0) + float(weight), 4)
    return normalized


def _compile_restrictions(restrictions: list[str] | None) -> _RestrictionFilter:
    raw_restrictions = [str(item).strip() for item in restrictions or [] if str(item).strip()]
    parsed = parse_profile_semantics(current_holdings="", restrictions=raw_restrictions)
    allowed_buckets = {_normalize_bucket(bucket) for bucket in parsed.allowed_buckets}
    forbidden_buckets = {_normalize_bucket(bucket) for bucket in parsed.forbidden_buckets}
    allowed_wrappers = {str(wrapper).strip().lower() for wrapper in parsed.allowed_wrappers}
    forbidden_wrappers = {str(wrapper).strip().lower() for wrapper in parsed.forbidden_wrappers}
    warnings: list[str] = []
    lowered_items = [item.lower() for item in raw_restrictions]

    if any(token in item for item in lowered_items for token in ("不碰股票", "不买股票", "不能买股票")):
        forbidden_wrappers.add("stock")
        warnings.append("限制条件“不碰股票”已过滤股票包装，ETF/基金权益敞口仍可保留。")

    if any(
        token in item
        for item in lowered_items
        for token in ("只接受黄金和现金", "只接受现金和黄金", "只能黄金和现金", "只要黄金和现金")
    ):
        allowed_buckets.update({"gold", "cash_liquidity"})
        forbidden_buckets.update({"equity_cn", "bond_cn", "satellite"})
        warnings.append("限制条件“只接受黄金和现金”已过滤为仅保留黄金与现金/流动性产品。")

    return _RestrictionFilter(
        allowed_buckets={bucket for bucket in allowed_buckets if bucket},
        forbidden_buckets={bucket for bucket in forbidden_buckets if bucket},
        allowed_wrappers={wrapper for wrapper in allowed_wrappers if wrapper},
        forbidden_wrappers={wrapper for wrapper in forbidden_wrappers if wrapper},
        qdii_allowed=parsed.qdii_allowed,
        warnings=warnings,
    )


def _availability_reason(candidate: ProductCandidate) -> str | None:
    if not candidate.enabled:
        return "availability:disabled"
    if candidate.deprecated:
        return "availability:deprecated"
    return None


def _bucket_reason(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> str | None:
    if candidate.asset_bucket in restriction_filter.forbidden_buckets:
        return f"bucket:{candidate.asset_bucket}"
    if restriction_filter.allowed_buckets and candidate.asset_bucket not in restriction_filter.allowed_buckets:
        return f"bucket:not_allowed:{candidate.asset_bucket}"
    return None


def _wrapper_reason(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> str | None:
    if candidate.wrapper_type in restriction_filter.forbidden_wrappers:
        return f"wrapper:{candidate.wrapper_type}"
    if restriction_filter.allowed_wrappers and candidate.wrapper_type not in restriction_filter.allowed_wrappers:
        return f"wrapper:not_allowed:{candidate.wrapper_type}"
    return None


def _region_reason(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> str | None:
    if restriction_filter.qdii_allowed is False:
        if "qdii" in candidate.tags:
            return "tag:qdii"
        if candidate.region != "CN":
            return "region:non_cn"
    return None


def _candidate_sort_key(candidate: ProductCandidate) -> tuple[int, int, int, str]:
    return (
        _WRAPPER_PRIORITY.get((candidate.asset_bucket, candidate.wrapper_type), 9),
        _LIQUIDITY_PRIORITY.get(candidate.liquidity_tier, 9),
        _FEE_PRIORITY.get(candidate.fee_tier, 9),
        candidate.product_id,
    )


def _build_item(bucket: str, target_weight: float, candidates: list[ProductCandidate]) -> ExecutionPlanItem:
    ordered_candidates = sorted(candidates, key=_candidate_sort_key)
    primary_product = ordered_candidates[0]
    alternate_products = ordered_candidates[1:]
    rationale = [
        f"该执行项承接资金桶 {bucket} 的建议权重。",
        "主推产品按高流动性、低费用、低复杂度优先排序。",
    ]
    if alternate_products:
        rationale.append(f"同时保留 {len(alternate_products)} 个替代产品，避免把候选隐藏成黑箱答案。")

    return ExecutionPlanItem(
        asset_bucket=bucket,
        target_weight=round(float(target_weight), 4),
        primary_product_id=primary_product.product_id,
        alternate_product_ids=[product.product_id for product in alternate_products],
        rationale=rationale,
        risk_labels=sorted(set(primary_product.risk_labels)),
        primary_product=primary_product,
        alternate_products=alternate_products,
    )


def _apply_stage(
    stage_name: str,
    candidates: list[tuple[int, ProductCandidate]],
    predicate,
) -> tuple[list[tuple[int, ProductCandidate]], CandidateFilterStage]:
    kept: list[tuple[int, ProductCandidate]] = []
    dropped_reasons: dict[str, int] = {}
    for registry_index, candidate in candidates:
        reason = predicate(candidate)
        if reason is None:
            kept.append((registry_index, candidate))
            continue
        dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
    return kept, CandidateFilterStage(
        stage_name=stage_name,
        input_count=len(candidates),
        output_count=len(kept),
        dropped_reasons=dropped_reasons,
    )


def _build_runtime_candidate_pool(
    registry: list[ProductCandidate],
    restriction_filter: _RestrictionFilter,
) -> tuple[list[RuntimeProductCandidate], CandidateFilterBreakdown]:
    staged_candidates = list(enumerate(registry))
    stages: list[CandidateFilterStage] = []

    staged_candidates, stage = _apply_stage("availability", staged_candidates, _availability_reason)
    stages.append(stage)
    staged_candidates, stage = _apply_stage(
        "bucket_restrictions",
        staged_candidates,
        lambda candidate: _bucket_reason(candidate, restriction_filter),
    )
    stages.append(stage)
    staged_candidates, stage = _apply_stage(
        "wrapper_restrictions",
        staged_candidates,
        lambda candidate: _wrapper_reason(candidate, restriction_filter),
    )
    stages.append(stage)
    staged_candidates, stage = _apply_stage(
        "region_restrictions",
        staged_candidates,
        lambda candidate: _region_reason(candidate, restriction_filter),
    )
    stages.append(stage)

    dropped_reasons: dict[str, int] = {}
    for stage in stages:
        for reason, count in stage.dropped_reasons.items():
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + count

    runtime_candidates = [
        RuntimeProductCandidate(candidate=candidate, registry_index=registry_index)
        for registry_index, candidate in staged_candidates
    ]
    return runtime_candidates, CandidateFilterBreakdown(
        registry_candidate_count=len(registry),
        runtime_candidate_count=len(runtime_candidates),
        stages=stages,
        dropped_reasons=dropped_reasons,
    )


def build_execution_plan(
    *,
    source_run_id: str,
    source_allocation_id: str,
    bucket_targets: dict[str, float],
    restrictions: list[str] | None = None,
    plan_version: int = 1,
    catalog: list[ProductCandidate] | None = None,
) -> ExecutionPlan:
    normalized_targets = _normalize_bucket_targets(bucket_targets)
    restriction_filter = _compile_restrictions(restrictions)
    registry = list(catalog or load_builtin_catalog())
    runtime_candidates, candidate_filter_breakdown = _build_runtime_candidate_pool(registry, restriction_filter)
    grouped_candidates: dict[str, list[ProductCandidate]] = defaultdict(list)

    for runtime_candidate in runtime_candidates:
        candidate = runtime_candidate.candidate
        grouped_candidates[_normalize_bucket(candidate.asset_bucket)].append(candidate)

    items: list[ExecutionPlanItem] = []
    warnings = list(restriction_filter.warnings)
    for bucket, target_weight in normalized_targets.items():
        if target_weight <= 0:
            continue
        if bucket in restriction_filter.forbidden_buckets:
            warnings.append(f"资金桶 {bucket} 因用户限制被排除。")
            continue
        if restriction_filter.allowed_buckets and bucket not in restriction_filter.allowed_buckets:
            warnings.append(f"资金桶 {bucket} 不在用户允许范围内，已从执行计划移除。")
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            warnings.append(f"资金桶 {bucket} 当前没有可用产品候选。")
            continue
        items.append(_build_item(bucket, target_weight, bucket_candidates))

    return ExecutionPlan(
        plan_id=f"{source_run_id}:{source_allocation_id}",
        source_run_id=source_run_id,
        source_allocation_id=source_allocation_id,
        items=items,
        warnings=warnings,
        plan_version=max(int(plan_version), 1),
        registry_candidate_count=len(registry),
        runtime_candidate_count=len(runtime_candidates),
        runtime_candidates=runtime_candidates,
        candidate_filter_breakdown=candidate_filter_breakdown,
    )
