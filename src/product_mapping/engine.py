from __future__ import annotations

from collections import defaultdict

from product_mapping.catalog import load_builtin_catalog
from product_mapping.selection import (
    build_recommended_products,
    build_selection_evidence,
    normalize_user_restrictions,
    product_matches_constraints,
    rank_bucket_candidates,
)
from product_mapping.types import ExecutionPlan, ExecutionPlanItem, ProductCandidate, ProductConstraintProfile


_BUCKET_ALIASES = {
    "cash": "cash_liquidity",
    "cash / liquidity": "cash_liquidity",
    "cash/liquidity": "cash_liquidity",
    "cash_liquidity": "cash_liquidity",
    "liquidity": "cash_liquidity",
}


def _normalize_bucket(bucket: str) -> str:
    normalized = str(bucket).strip().lower()
    return _BUCKET_ALIASES.get(normalized, normalized)


def _normalize_bucket_targets(bucket_targets: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for bucket, weight in bucket_targets.items():
        canonical_bucket = _normalize_bucket(bucket)
        normalized[canonical_bucket] = round(normalized.get(canonical_bucket, 0.0) + float(weight), 4)
    return normalized


def _build_item(
    bucket: str,
    target_weight: float,
    candidates: list[ProductCandidate],
    warnings: list[str],
    constraints: ProductConstraintProfile,
) -> ExecutionPlanItem:
    ordered_candidates = rank_bucket_candidates(bucket, candidates)
    recommended_products = build_recommended_products(
        bucket=bucket,
        target_weight=target_weight,
        ordered_candidates=ordered_candidates,
    )
    primary_product = ordered_candidates[0]
    alternate_products = ordered_candidates[1:]
    rationale = [
        f"该执行项承接资金桶 {bucket} 的建议权重。",
        "候选先经过包装/风格/市场约束过滤，再按流动性、费率、估值和跟踪质量排序。",
    ]
    if alternate_products:
        rationale.append(f"当前保留 {len(alternate_products)} 个替代产品，避免只有 1 主 1 备的单薄映射。")
    selection_evidence = build_selection_evidence(
        bucket=bucket,
        ordered_candidates=ordered_candidates,
        constraints=constraints,
    )
    selection_evidence["selection_reason"] = list(rationale)
    selection_evidence["recommended_product_count"] = len(recommended_products)
    if bucket == "satellite" and len(recommended_products) < 3:
        warnings.append("卫星桶当前候选过少，后续应继续扩充主题产品池。")

    return ExecutionPlanItem(
        asset_bucket=bucket,
        target_weight=round(float(target_weight), 4),
        primary_product_id=primary_product.product_id,
        alternate_product_ids=[product.product_id for product in alternate_products],
        rationale=rationale,
        risk_labels=sorted({label for candidate in ordered_candidates for label in candidate.risk_labels}),
        primary_product=primary_product,
        alternate_products=alternate_products,
        recommended_products=recommended_products,
        selection_evidence=selection_evidence,
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
    constraint_profile = normalize_user_restrictions(restrictions)
    grouped_candidates: dict[str, list[ProductCandidate]] = defaultdict(list)

    for candidate in catalog or load_builtin_catalog():
        normalized_bucket = _normalize_bucket(candidate.asset_bucket)
        if product_matches_constraints(candidate, constraint_profile):
            grouped_candidates[normalized_bucket].append(candidate)

    items: list[ExecutionPlanItem] = []
    warnings = list(constraint_profile.warnings)
    for bucket, target_weight in normalized_targets.items():
        if target_weight <= 0:
            continue
        if bucket in constraint_profile.forbidden_exposures:
            warnings.append(f"资金桶 {bucket} 因用户暴露限制被排除。")
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            warnings.append(f"资金桶 {bucket} 当前没有可用产品候选。")
            continue
        items.append(_build_item(bucket, target_weight, bucket_candidates, warnings, constraint_profile))

    warnings.extend(constraint_profile.notes)
    return ExecutionPlan(
        plan_id=f"{source_run_id}:{source_allocation_id}",
        source_run_id=source_run_id,
        source_allocation_id=source_allocation_id,
        items=items,
        warnings=warnings,
        plan_version=max(int(plan_version), 1),
    )
