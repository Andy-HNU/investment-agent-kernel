from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from shared.profile_parser import parse_profile_semantics

from product_mapping.catalog import load_builtin_catalog
from product_mapping.types import ExecutionPlan, ExecutionPlanItem, ProductCandidate


_BUCKET_ALIASES = {
    "cash": "cash_liquidity",
    "cash / liquidity": "cash_liquidity",
    "cash/liquidity": "cash_liquidity",
    "cash_liquidity": "cash_liquidity",
    "liquidity": "cash_liquidity",
    "qdii": "qdii_global",
    "qdii_global": "qdii_global",
    "overseas_equity": "overseas",
    "global_equity": "overseas",
}
_LIQUIDITY_PRIORITY = {"high": 0, "medium": 1, "low": 2}
_FEE_PRIORITY = {"low": 0, "medium": 1, "high": 2}
_WRAPPER_PRIORITY = {
    ("equity_cn", "etf"): 0,
    ("bond_cn", "etf"): 0,
    ("bond_cn", "fund"): 1,
    ("gold", "etf"): 0,
    ("gold", "fund"): 1,
    ("satellite", "etf"): 0,
    ("qdii_global", "etf"): 0,
    ("overseas", "etf"): 0,
    ("cash_liquidity", "cash_mgmt"): 0,
    ("cash_liquidity", "fund"): 1,
}
_CASH_FALLBACK_BUCKET = "cash_liquidity"


@dataclass(frozen=True)
class _RestrictionFilter:
    allowed_buckets: set[str]
    forbidden_buckets: set[str]
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
    warnings: list[str] = []
    lowered_items = [item.lower() for item in raw_restrictions]

    if any(token in item for item in lowered_items for token in ("不碰股票", "不买股票", "不能买股票")):
        forbidden_buckets.add("equity_cn")
        warnings.append("限制条件“不碰股票”已过滤权益类产品。")

    if any(
        token in item
        for item in lowered_items
        for token in ("只接受黄金和现金", "只接受现金和黄金", "只能黄金和现金", "只要黄金和现金")
    ):
        allowed_buckets.update({"gold", "cash_liquidity"})
        forbidden_buckets.update({"equity_cn", "bond_cn"})
        warnings.append("限制条件“只接受黄金和现金”已过滤为仅保留黄金与现金/流动性产品。")

    return _RestrictionFilter(
        allowed_buckets={bucket for bucket in allowed_buckets if bucket},
        forbidden_buckets={bucket for bucket in forbidden_buckets if bucket},
        qdii_allowed=parsed.qdii_allowed,
        warnings=warnings,
    )


def _matches_restrictions(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> bool:
    if candidate.asset_bucket in restriction_filter.forbidden_buckets:
        return False
    if restriction_filter.qdii_allowed is False and candidate.asset_bucket == "qdii_global":
        return False
    if restriction_filter.allowed_buckets and candidate.asset_bucket not in restriction_filter.allowed_buckets:
        return False
    return candidate.enabled and not candidate.deprecated


def _candidate_sort_key(candidate: ProductCandidate) -> tuple[int, int, int, str]:
    return (
        _WRAPPER_PRIORITY.get((candidate.asset_bucket, candidate.wrapper_type), 9),
        _LIQUIDITY_PRIORITY.get(candidate.liquidity_tier, 9),
        _FEE_PRIORITY.get(candidate.fee_tier, 9),
        candidate.product_id,
    )


def _build_item(
    bucket: str,
    target_weight: float,
    candidates: list[ProductCandidate],
    *,
    rationale_prefixes: list[str] | None = None,
) -> ExecutionPlanItem:
    ordered_candidates = sorted(candidates, key=_candidate_sort_key)
    primary_product = ordered_candidates[0]
    alternate_products = ordered_candidates[1:]
    rationale = list(rationale_prefixes or []) + [
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
    grouped_candidates: dict[str, list[ProductCandidate]] = defaultdict(list)
    all_grouped_candidates: dict[str, list[ProductCandidate]] = defaultdict(list)

    for candidate in catalog or load_builtin_catalog():
        all_grouped_candidates[_normalize_bucket(candidate.asset_bucket)].append(candidate)
        if _matches_restrictions(candidate, restriction_filter):
            grouped_candidates[_normalize_bucket(candidate.asset_bucket)].append(candidate)

    items: list[ExecutionPlanItem] = []
    warnings = list(restriction_filter.warnings)
    planned_targets: dict[str, float] = defaultdict(float)
    planned_rationale_prefixes: dict[str, list[str]] = defaultdict(list)
    unmapped_buckets: list[str] = []
    degraded_buckets: list[str] = []
    blocked_buckets: list[str] = []
    total_target_weight = sum(max(float(weight), 0.0) for weight in normalized_targets.values())

    for bucket, target_weight in normalized_targets.items():
        if target_weight <= 0:
            continue
        if bucket in restriction_filter.forbidden_buckets:
            warnings.append(f"资金桶 {bucket} 因用户限制被排除。")
            blocked_buckets.append(bucket)
            continue
        if restriction_filter.allowed_buckets and bucket not in restriction_filter.allowed_buckets:
            warnings.append(f"资金桶 {bucket} 不在用户允许范围内，已从执行计划移除。")
            blocked_buckets.append(bucket)
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            catalog_candidates = all_grouped_candidates.get(bucket, [])
            if catalog_candidates:
                warnings.append(f"资金桶 {bucket} 当前因用户限制没有可执行产品候选，执行计划已被阻断。")
                blocked_buckets.append(bucket)
                continue
            unmapped_buckets.append(bucket)
            cash_fallback_allowed = (
                bucket != _CASH_FALLBACK_BUCKET
                and grouped_candidates.get(_CASH_FALLBACK_BUCKET)
                and _CASH_FALLBACK_BUCKET not in restriction_filter.forbidden_buckets
                and (
                    not restriction_filter.allowed_buckets
                    or _CASH_FALLBACK_BUCKET in restriction_filter.allowed_buckets
                )
            )
            if cash_fallback_allowed:
                degraded_buckets.append(bucket)
                planned_targets[_CASH_FALLBACK_BUCKET] = round(
                    planned_targets.get(_CASH_FALLBACK_BUCKET, 0.0) + float(target_weight),
                    4,
                )
                planned_rationale_prefixes[_CASH_FALLBACK_BUCKET].append(
                    f"原资金桶 {bucket} 当前没有直接产品映射，本轮先用现金/流动性产品临时承接。"
                )
                warnings.append(
                    f"资金桶 {bucket} 当前没有可用产品候选，已降级为现金/流动性承接，待人工复核。"
                )
                continue
            warnings.append(f"资金桶 {bucket} 当前没有可用产品候选，执行计划已被阻断。")
            blocked_buckets.append(bucket)
            continue
        planned_targets[bucket] = round(planned_targets.get(bucket, 0.0) + float(target_weight), 4)

    for bucket, target_weight in planned_targets.items():
        if target_weight <= 0:
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            warnings.append(f"计划中的资金桶 {bucket} 缺少产品候选，执行计划已被阻断。")
            blocked_buckets.append(bucket)
            continue
        items.append(
            _build_item(
                bucket,
                target_weight,
                bucket_candidates,
                rationale_prefixes=planned_rationale_prefixes.get(bucket),
            )
        )

    covered_weight = round(sum(float(item.target_weight) for item in items), 4)
    coverage_ratio = 0.0 if total_target_weight <= 1e-9 else round(min(covered_weight / total_target_weight, 1.0), 4)
    if coverage_ratio < 1.0 - 1e-6:
        status = "blocked"
    elif blocked_buckets:
        status = "blocked"
    elif degraded_buckets:
        status = "degraded"
    else:
        status = "draft"

    return ExecutionPlan(
        plan_id=f"{source_run_id}:{source_allocation_id}",
        source_run_id=source_run_id,
        source_allocation_id=source_allocation_id,
        status=status,
        items=items,
        warnings=warnings,
        confirmation_required=status != "blocked",
        plan_version=max(int(plan_version), 1),
        coverage_ratio=coverage_ratio,
        unmapped_buckets=sorted(set(unmapped_buckets)),
        degraded_buckets=sorted(set(degraded_buckets)),
    )
