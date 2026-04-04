from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any

from shared.profile_parser import parse_profile_semantics

from product_mapping.catalog import load_builtin_catalog
from product_mapping.policy_news import apply_policy_news_scores
from product_mapping.types import (
    CandidateFilterBreakdown,
    CandidateFilterStage,
    ExecutionRealismSummary,
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    ProductPolicyNewsAudit,
    ProductProxySpec,
    ProductValuationAudit,
    ProxyUniverseSummary,
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
_VALUATION_MAX_PE = 40.0
_VALUATION_MAX_PERCENTILE = 0.30
_PROXY_CONFIDENCE_BY_WRAPPER = {
    "stock": 0.96,
    "etf": 0.93,
    "fund": 0.82,
    "cash_mgmt": 0.88,
    "bond": 0.90,
    "other": 0.70,
}
_WRAPPER_SLIPPAGE_RATE = {
    "stock": 0.0015,
    "etf": 0.0008,
    "fund": 0.0005,
    "cash_mgmt": 0.0,
    "bond": 0.0004,
    "other": 0.0010,
}


@dataclass(frozen=True)
class _RestrictionFilter:
    allowed_buckets: set[str]
    forbidden_buckets: set[str]
    allowed_wrappers: set[str]
    forbidden_wrappers: set[str]
    allowed_regions: set[str]
    forbidden_regions: set[str]
    forbidden_themes: set[str]
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
    allowed_regions = {str(region).strip().upper() for region in parsed.allowed_regions}
    forbidden_regions = {str(region).strip().upper() for region in parsed.forbidden_regions}
    forbidden_themes = {str(theme).strip().lower() for theme in parsed.forbidden_themes}
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
        allowed_regions={region for region in allowed_regions if region},
        forbidden_regions={region for region in forbidden_regions if region},
        forbidden_themes={theme for theme in forbidden_themes if theme},
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
    region = str(candidate.region or "").strip().upper()
    if restriction_filter.allowed_regions and region and region not in restriction_filter.allowed_regions:
        return f"region:not_allowed:{region}"
    if region in restriction_filter.forbidden_regions:
        return f"region:{region.lower()}"
    if "NON_CN" in restriction_filter.forbidden_regions and region and region != "CN":
        return "region:non_cn"
    if restriction_filter.qdii_allowed is False:
        if "qdii" in candidate.tags:
            return "tag:qdii"
        if region and region != "CN":
            return "region:non_cn"
    return None


def _theme_reason(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> str | None:
    candidate_tags = {str(tag).strip().lower() for tag in candidate.tags}
    for theme in sorted(restriction_filter.forbidden_themes):
        if theme in candidate_tags:
            return f"theme:{theme}"
    return None


def _candidate_sort_key(runtime_candidate: RuntimeProductCandidate) -> tuple[float, int, int, int, str]:
    candidate = runtime_candidate.candidate
    policy_score = 0.0
    if runtime_candidate.policy_news_audit is not None:
        policy_score = float(runtime_candidate.policy_news_audit.score or 0.0)
    if candidate.asset_bucket == "satellite":
        policy_priority = -policy_score
    else:
        # Core buckets can see the score in audits, but ranking only uses it as a
        # late tiebreaker so policy/news cannot silently replace the core.
        policy_priority = 0.0
    return (
        policy_priority,
        _WRAPPER_PRIORITY.get((candidate.asset_bucket, candidate.wrapper_type), 9),
        _LIQUIDITY_PRIORITY.get(candidate.liquidity_tier, 9),
        _FEE_PRIORITY.get(candidate.fee_tier, 9),
        candidate.product_id,
    )


def _is_valuation_applicable(candidate: ProductCandidate) -> bool:
    return candidate.asset_bucket in {"equity_cn", "satellite"} or candidate.wrapper_type == "stock"


def _resolve_valuation_payload(
    candidate: ProductCandidate,
    valuation_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not valuation_result:
        return None
    product_map = dict(valuation_result.get("products") or {})
    for key in (
        candidate.product_id,
        str(candidate.provider_symbol or "").strip(),
        str(candidate.provider_symbol or "").strip().lower(),
    ):
        if key and key in product_map:
            payload = dict(product_map.get(key) or {})
            payload.setdefault("product_key", key)
            return payload
    return None


def _valuation_source_summary(
    valuation_inputs: dict[str, Any] | None,
    valuation_result: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = dict(valuation_inputs or {})
    result = dict(valuation_result or {})
    return {
        "requested": bool(inputs.get("requested") or valuation_result is not None),
        "require_observed_source": bool(inputs.get("require_observed_source", False)),
        "source_status": str(result.get("source_status") or "missing"),
        "source_name": result.get("source_name"),
        "source_ref": result.get("source_ref"),
        "as_of": result.get("as_of"),
        "rule_max_pe": _VALUATION_MAX_PE,
        "rule_max_percentile": _VALUATION_MAX_PERCENTILE,
    }


def _build_valuation_audit(
    candidate: ProductCandidate,
    valuation_inputs: dict[str, Any] | None,
    valuation_result: dict[str, Any] | None,
) -> tuple[ProductValuationAudit | None, str | None]:
    summary = _valuation_source_summary(valuation_inputs, valuation_result)
    if not summary["requested"]:
        return None, None
    if not _is_valuation_applicable(candidate):
        return ProductValuationAudit(
            status="not_applicable",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            passed_filters=None,
            reason="valuation:not_applicable",
        ), None

    payload = _resolve_valuation_payload(candidate, valuation_result)
    if (
        summary["source_status"] != "observed"
        or not payload
        or str(payload.get("status") or "missing") != "observed"
    ):
        reason = "valuation:missing_observed_source"
        audit = ProductValuationAudit(
            status="missing_source",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            passed_filters=False,
            reason=reason,
        )
        if summary["require_observed_source"]:
            return audit, reason
        return audit, None

    pe_ratio = payload.get("pe_ratio")
    percentile = payload.get("percentile")
    if pe_ratio is None or percentile is None:
        reason = "valuation:missing_metrics"
        return ProductValuationAudit(
            status="missing_metrics",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            pe_ratio=pe_ratio,
            percentile=percentile,
            passed_filters=False,
            reason=reason,
        ), reason

    pe_ratio = float(pe_ratio)
    percentile = float(percentile)
    if pe_ratio > _VALUATION_MAX_PE:
        reason = "valuation:pe_above_40"
        return ProductValuationAudit(
            status="observed",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            pe_ratio=pe_ratio,
            percentile=percentile,
            passed_filters=False,
            reason=reason,
        ), reason
    if percentile > _VALUATION_MAX_PERCENTILE:
        reason = "valuation:percentile_above_0.30"
        return ProductValuationAudit(
            status="observed",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            pe_ratio=pe_ratio,
            percentile=percentile,
            passed_filters=False,
            reason=reason,
        ), reason
    return ProductValuationAudit(
        status="observed",
        source_name=summary["source_name"],
        source_ref=summary["source_ref"],
        as_of=summary["as_of"],
        pe_ratio=pe_ratio,
        percentile=percentile,
        passed_filters=True,
        reason="valuation:passed",
    ), None


def _apply_valuation_stage(
    staged_candidates: list[tuple[int, ProductCandidate]],
    *,
    valuation_inputs: dict[str, Any] | None,
    valuation_result: dict[str, Any] | None,
) -> tuple[list[RuntimeProductCandidate], CandidateFilterStage, dict[str, Any]]:
    summary = _valuation_source_summary(valuation_inputs, valuation_result)
    if not summary["requested"]:
        runtime_candidates = [
            RuntimeProductCandidate(candidate=candidate, registry_index=registry_index)
            for registry_index, candidate in staged_candidates
        ]
        return runtime_candidates, CandidateFilterStage(
            stage_name="valuation_filters",
            input_count=len(staged_candidates),
            output_count=len(runtime_candidates),
            dropped_reasons={},
            audit_fields=summary,
        ), {
            **summary,
            "applicable_candidate_count": 0,
            "observed_candidate_count": 0,
            "passed_candidate_count": 0,
            "non_applicable_candidate_count": 0,
            "dropped_candidate_count": 0,
        }

    dropped_reasons: dict[str, int] = {}
    runtime_candidates: list[RuntimeProductCandidate] = []
    applicable_count = 0
    observed_count = 0
    passed_count = 0
    non_applicable_count = 0
    dropped_count = 0

    for registry_index, candidate in staged_candidates:
        audit, drop_reason = _build_valuation_audit(candidate, valuation_inputs, valuation_result)
        if audit is not None:
            if audit.status == "not_applicable":
                non_applicable_count += 1
            else:
                applicable_count += 1
            if audit.status == "observed":
                observed_count += 1
            if audit.passed_filters:
                passed_count += 1
        if drop_reason:
            dropped_reasons[drop_reason] = dropped_reasons.get(drop_reason, 0) + 1
            dropped_count += 1
            continue
        runtime_candidates.append(
            RuntimeProductCandidate(
                candidate=candidate,
                registry_index=registry_index,
                valuation_audit=audit,
            )
        )

    audit_summary = {
        **summary,
        "applicable_candidate_count": applicable_count,
        "observed_candidate_count": observed_count,
        "passed_candidate_count": passed_count,
        "non_applicable_candidate_count": non_applicable_count,
        "dropped_candidate_count": dropped_count,
    }
    return runtime_candidates, CandidateFilterStage(
        stage_name="valuation_filters",
        input_count=len(staged_candidates),
        output_count=len(runtime_candidates),
        dropped_reasons=dropped_reasons,
        audit_fields=audit_summary,
    ), audit_summary


def _build_item(
    bucket: str,
    target_weight: float,
    candidates: list[RuntimeProductCandidate],
    *,
    account_total_value: float | None = None,
    current_weight: float | None = None,
    minimum_trade_amount: float | None = None,
    initial_deploy_fraction: float = 0.40,
    transaction_fee_rate: dict[str, float] | None = None,
    wrapper_slippage_rate: dict[str, float] | None = None,
) -> ExecutionPlanItem:
    ordered_candidates = sorted(candidates, key=_candidate_sort_key)
    primary_runtime_candidate = ordered_candidates[0]
    primary_product = primary_runtime_candidate.candidate
    alternate_runtime_candidates = ordered_candidates[1:]
    alternate_products = [item.candidate for item in alternate_runtime_candidates]
    bucket_policy_audits = [
        item.policy_news_audit
        for item in ordered_candidates
        if item.policy_news_audit is not None and item.policy_news_audit.realtime_eligible and item.policy_news_audit.score
    ]
    item_policy_news_audit = primary_runtime_candidate.policy_news_audit
    if (
        bucket != "satellite"
        and item_policy_news_audit is not None
        and item_policy_news_audit.influence_scope == "none"
        and bucket_policy_audits
    ):
        strongest_bucket_audit = max(bucket_policy_audits, key=lambda audit: abs(float(audit.score or 0.0)))
        item_policy_news_audit = replace(
            strongest_bucket_audit,
            influence_scope="core_mild",
            notes=list(strongest_bucket_audit.notes)
            + ["policy/news signal matched the bucket but did not displace the core primary product"],
        )
    rationale = [
        f"该执行项承接资金桶 {bucket} 的建议权重。",
        "主推产品按高流动性、低费用、低复杂度优先排序。",
    ]
    if primary_runtime_candidate.valuation_audit is not None:
        audit = primary_runtime_candidate.valuation_audit
        if audit.status == "observed" and audit.passed_filters:
            rationale.append("主推产品已基于真实估值结果通过正式筛选：PE<=40，估值分位<=30%。")
        elif audit.status == "not_applicable":
            rationale.append("该产品不适用 PE/估值分位筛选，已显式标记 valuation:not_applicable。")
    if item_policy_news_audit is not None:
        audit = item_policy_news_audit
        if audit.realtime_eligible and audit.score:
            rationale.append("主推产品已吸收真实政策/新闻材料的动态评分排序。")
        elif not audit.realtime_eligible:
            rationale.append("当前没有可用的真实政策/新闻材料，本次未启用实时政策/新闻评分。")
        elif audit.influence_scope == "core_mild":
            rationale.append("核心仓仅接受温和政策/新闻影响，热点信号不会直接推翻核心排序。")
    if alternate_products:
        rationale.append(f"同时保留 {len(alternate_products)} 个替代产品，避免把候选隐藏成黑箱答案。")

    current_weight = None if current_weight is None else round(float(current_weight), 4)
    target_amount = None
    current_amount = None
    trade_direction: str | None = None
    trade_amount = None
    initial_trade_amount = None
    deferred_trade_amount = None
    estimated_fee = None
    estimated_slippage = None
    violates_minimum_trade = False
    if account_total_value is not None:
        total_value = float(account_total_value)
        target_amount = round(total_value * float(target_weight), 2)
        current_amount = round(total_value * float(current_weight or 0.0), 2)
        delta = round(target_amount - current_amount, 2)
        if abs(delta) <= 1e-6:
            trade_direction = "hold"
            trade_amount = 0.0
            initial_trade_amount = 0.0
            deferred_trade_amount = 0.0
        else:
            trade_direction = "buy" if delta > 0 else "sell"
            trade_amount = round(abs(delta), 2)
            initial_trade_amount = round(trade_amount * float(initial_deploy_fraction), 2)
            deferred_trade_amount = round(trade_amount - initial_trade_amount, 2)
            fee_rate = float((transaction_fee_rate or {}).get(bucket, 0.0) or 0.0)
            slip_rate = float(
                (wrapper_slippage_rate or {}).get(
                    primary_product.wrapper_type,
                    _WRAPPER_SLIPPAGE_RATE.get(primary_product.wrapper_type, 0.0),
                )
                or 0.0
            )
            estimated_fee = round(trade_amount * fee_rate, 2)
            estimated_slippage = round(trade_amount * slip_rate, 2)
            if minimum_trade_amount is not None and 0.0 < trade_amount < float(minimum_trade_amount):
                violates_minimum_trade = True

    return ExecutionPlanItem(
        asset_bucket=bucket,
        target_weight=round(float(target_weight), 4),
        current_weight=current_weight,
        current_amount=current_amount,
        target_amount=target_amount,
        trade_direction=trade_direction,
        trade_amount=trade_amount,
        initial_trade_amount=initial_trade_amount,
        deferred_trade_amount=deferred_trade_amount,
        estimated_fee=estimated_fee,
        estimated_slippage=estimated_slippage,
        violates_minimum_trade=violates_minimum_trade,
        primary_product_id=primary_product.product_id,
        alternate_product_ids=[product.product_id for product in alternate_products],
        rationale=rationale,
        risk_labels=sorted(set(primary_product.risk_labels)),
        primary_product=primary_product,
        alternate_products=alternate_products,
        valuation_audit=primary_runtime_candidate.valuation_audit,
        policy_news_audit=item_policy_news_audit,
    )


def _proxy_kind(candidate: ProductCandidate) -> str:
    if candidate.wrapper_type == "stock":
        return "single_stock_history"
    if candidate.wrapper_type == "etf":
        return "listed_fund_price_proxy"
    if candidate.wrapper_type == "cash_mgmt":
        return "cash_management_nav_proxy"
    if candidate.wrapper_type == "fund" and ("qdii" in candidate.tags or candidate.region != "CN"):
        return "qdii_nav_proxy"
    if candidate.wrapper_type == "fund":
        return "fund_nav_proxy"
    if candidate.wrapper_type == "bond":
        return "bond_price_proxy"
    return "registered_proxy"


def _build_product_proxy_spec(candidate: ProductCandidate) -> ProductProxySpec:
    proxy_ref = f"{candidate.provider_source}:{candidate.provider_symbol or candidate.product_id}"
    return ProductProxySpec(
        product_id=candidate.product_id,
        proxy_kind=_proxy_kind(candidate),
        proxy_ref=proxy_ref,
        confidence=_PROXY_CONFIDENCE_BY_WRAPPER.get(candidate.wrapper_type, 0.70),
        confidence_data_status="manual_annotation",
        confidence_disclosure="proxy confidence is a heuristic wrapper-level mapping, not observed market coverage or empirical fit quality.",
        source_ref=proxy_ref,
        data_status="manual_annotation",
    )


def _attach_proxy_specs(runtime_candidates: list[RuntimeProductCandidate]) -> tuple[list[RuntimeProductCandidate], list[ProductProxySpec]]:
    proxy_specs: list[ProductProxySpec] = []
    enriched: list[RuntimeProductCandidate] = []
    for runtime_candidate in runtime_candidates:
        proxy_spec = _build_product_proxy_spec(runtime_candidate.candidate)
        proxy_specs.append(proxy_spec)
        enriched.append(replace(runtime_candidate, proxy_spec=proxy_spec))
    return enriched, proxy_specs


def _build_proxy_universe_summary(
    *,
    normalized_targets: dict[str, float],
    runtime_candidates: list[RuntimeProductCandidate],
    selected_items: list[ExecutionPlanItem],
    product_proxy_specs: list[ProductProxySpec],
) -> ProxyUniverseSummary:
    requested_buckets = sorted(bucket for bucket, weight in normalized_targets.items() if weight > 0)
    covered_buckets = sorted({_normalize_bucket(item.asset_bucket) for item in selected_items})
    uncovered_buckets = [bucket for bucket in requested_buckets if bucket not in covered_buckets]
    covered_regions = sorted(
        {
            str(product.region or "CN")
            for item in selected_items
            for product in [item.primary_product, *item.alternate_products]
        }
    )
    return ProxyUniverseSummary(
        solving_mode="proxy_universe",
        proxy_scope="selected_plan_items",
        covered_asset_buckets=covered_buckets,
        uncovered_asset_buckets=uncovered_buckets,
        covered_regions=covered_regions,
        product_proxy_count=len(product_proxy_specs),
        runtime_candidate_proxy_count=len(runtime_candidates),
        data_status="manual_annotation",
        claims_real_product_history=False,
        disclosure=(
            "当前仍是代理宇宙求解：plan 级 proxy 披露仅覆盖执行计划中实际选中的产品，"
            "不是整个 runtime candidate pool，也不应解读为每个产品都已有独立历史序列进入求解器。"
        ),
    )


def _build_selected_plan_proxy_specs(items: list[ExecutionPlanItem]) -> list[ProductProxySpec]:
    selected_products: dict[str, ProductCandidate] = {}
    for item in items:
        selected_products[item.primary_product.product_id] = item.primary_product
        for product in item.alternate_products:
            selected_products[product.product_id] = product
    return [
        _build_product_proxy_spec(candidate)
        for candidate in sorted(selected_products.values(), key=lambda candidate: candidate.product_id)
    ]


def _build_execution_realism_summary(
    *,
    items: list[ExecutionPlanItem],
    account_total_value: float | None,
    available_cash: float | None,
    liquidity_reserve_min: float | None,
    minimum_trade_amount: float | None,
    transaction_fee_rate: dict[str, float] | None,
) -> ExecutionRealismSummary | None:
    if account_total_value is None:
        return None

    total_value = float(account_total_value)
    total_target_amount = round(
        sum(float(item.target_amount or 0.0) for item in items),
        2,
    )
    cash_target_amount = round(
        sum(float(item.target_amount or 0.0) for item in items if item.asset_bucket == "cash_liquidity"),
        2,
    )
    amount_closure_delta = round(total_target_amount - total_value, 2)
    cash_reserve_target_amount = (
        None
        if liquidity_reserve_min is None
        else round(total_value * float(liquidity_reserve_min), 2)
    )
    tiny_trade_buckets = sorted({item.asset_bucket for item in items if item.violates_minimum_trade})
    estimated_total_fee = round(sum(float(item.estimated_fee or 0.0) for item in items), 2)
    estimated_total_slippage = round(sum(float(item.estimated_slippage or 0.0) for item in items), 2)
    initial_buy_amount = round(
        sum(float(item.initial_trade_amount or 0.0) for item in items if item.trade_direction == "buy"),
        2,
    )
    initial_sell_amount = round(
        sum(float(item.initial_trade_amount or 0.0) for item in items if item.trade_direction == "sell"),
        2,
    )
    fundable_initial_cash = None
    if available_cash is not None:
        reserve_after_cash = max(
            float(available_cash) - float(cash_reserve_target_amount or 0.0),
            0.0,
        )
        fundable_initial_cash = round(
            reserve_after_cash + initial_sell_amount - estimated_total_fee - estimated_total_slippage,
            2,
        )
    reasons: list[str] = []
    if cash_reserve_target_amount is not None and cash_target_amount + 1e-6 < cash_reserve_target_amount:
        reasons.append("cash_reserve_conflict")
    for bucket in tiny_trade_buckets:
        reasons.append(f"tiny_trade:{bucket}")
    if abs(amount_closure_delta) > 1.0:
        reasons.append("account_amount_not_closed")
    if fundable_initial_cash is not None and fundable_initial_cash + 1e-6 < initial_buy_amount:
        reasons.append("initial_deploy_cash_shortfall")

    return ExecutionRealismSummary(
        executable=not reasons,
        account_total_value=round(total_value, 2),
        available_cash=None if available_cash is None else round(float(available_cash), 2),
        cash_reserve_target_amount=cash_reserve_target_amount,
        initial_buy_amount=initial_buy_amount,
        initial_sell_amount=initial_sell_amount,
        fundable_initial_cash=fundable_initial_cash,
        minimum_trade_amount=None if minimum_trade_amount is None else round(float(minimum_trade_amount), 2),
        total_target_amount=total_target_amount,
        cash_target_amount=cash_target_amount,
        amount_closure_delta=amount_closure_delta,
        estimated_total_fee=estimated_total_fee,
        estimated_total_slippage=estimated_total_slippage,
        execution_cost_data_status="prior_default",
        execution_cost_disclosure="当前交易费与滑点仅按默认/启发式口径估计，不是券商实盘观测成本。",
        tax_estimate_status="not_modeled",
        tiny_trade_buckets=tiny_trade_buckets,
        reasons=reasons,
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
    *,
    runtime_candidates: list[ProductCandidate] | list[RuntimeProductCandidate] | None = None,
    valuation_inputs: dict[str, Any] | None = None,
    valuation_result: dict[str, Any] | None = None,
    policy_news_signals: list[dict[str, Any]] | list[Any] | None = None,
) -> tuple[list[RuntimeProductCandidate], CandidateFilterBreakdown]:
    if runtime_candidates is None:
        staged_candidates = list(enumerate(registry))
    else:
        staged_candidates = []
        for index, entry in enumerate(runtime_candidates):
            if isinstance(entry, RuntimeProductCandidate):
                staged_candidates.append((entry.registry_index, entry.candidate))
            else:
                staged_candidates.append((index, entry))
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
    staged_candidates, stage = _apply_stage(
        "theme_restrictions",
        staged_candidates,
        lambda candidate: _theme_reason(candidate, restriction_filter),
    )
    stages.append(stage)

    dropped_reasons: dict[str, int] = {}
    for stage in stages:
        for reason, count in stage.dropped_reasons.items():
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + count

    runtime_candidates, stage, valuation_audit_summary = _apply_valuation_stage(
        staged_candidates,
        valuation_inputs=valuation_inputs,
        valuation_result=valuation_result,
    )
    stages.append(stage)
    for reason, count in stage.dropped_reasons.items():
        dropped_reasons[reason] = dropped_reasons.get(reason, 0) + count
    runtime_candidates, policy_news_audit_summary = apply_policy_news_scores(
        runtime_candidates,
        policy_news_signals,
    )
    stages.append(
        CandidateFilterStage(
            stage_name="policy_news_scoring",
            input_count=len(runtime_candidates),
            output_count=len(runtime_candidates),
            dropped_reasons={},
            audit_fields=policy_news_audit_summary,
        )
    )
    return runtime_candidates, CandidateFilterBreakdown(
        registry_candidate_count=len(registry),
        runtime_candidate_count=len(runtime_candidates),
        stages=stages,
        dropped_reasons=dropped_reasons,
        valuation_audit_summary=valuation_audit_summary,
        policy_news_audit_summary=policy_news_audit_summary,
    )


def build_execution_plan(
    *,
    source_run_id: str,
    source_allocation_id: str,
    bucket_targets: dict[str, float],
    restrictions: list[str] | None = None,
    plan_version: int = 1,
    catalog: list[ProductCandidate] | None = None,
    runtime_candidates: list[ProductCandidate] | list[RuntimeProductCandidate] | None = None,
    valuation_inputs: dict[str, Any] | None = None,
    valuation_result: dict[str, Any] | None = None,
    policy_news_signals: list[dict[str, Any]] | list[Any] | None = None,
    account_total_value: float | None = None,
    current_weights: dict[str, float] | None = None,
    available_cash: float | None = None,
    liquidity_reserve_min: float | None = None,
    minimum_trade_amount: float | None = 500.0,
    initial_deploy_fraction: float = 0.40,
    transaction_fee_rate: dict[str, float] | None = None,
    wrapper_slippage_rate: dict[str, float] | None = None,
) -> ExecutionPlan:
    normalized_targets = _normalize_bucket_targets(bucket_targets)
    normalized_current_weights = _normalize_bucket_targets(current_weights or {})
    restriction_filter = _compile_restrictions(restrictions)
    registry = list(catalog or load_builtin_catalog())
    runtime_candidate_pool, candidate_filter_breakdown = _build_runtime_candidate_pool(
        registry,
        restriction_filter,
        runtime_candidates=runtime_candidates,
        valuation_inputs=valuation_inputs,
        valuation_result=valuation_result,
        policy_news_signals=policy_news_signals,
    )
    runtime_candidate_pool, _runtime_pool_proxy_specs = _attach_proxy_specs(runtime_candidate_pool)
    grouped_candidates: dict[str, list[RuntimeProductCandidate]] = defaultdict(list)

    for runtime_candidate in runtime_candidate_pool:
        grouped_candidates[_normalize_bucket(runtime_candidate.candidate.asset_bucket)].append(runtime_candidate)

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
        items.append(
            _build_item(
                bucket,
                target_weight,
                bucket_candidates,
                account_total_value=account_total_value,
                current_weight=normalized_current_weights.get(bucket, 0.0),
                minimum_trade_amount=minimum_trade_amount,
                initial_deploy_fraction=initial_deploy_fraction,
                transaction_fee_rate=transaction_fee_rate,
                wrapper_slippage_rate=wrapper_slippage_rate,
            )
        )

    execution_realism_summary = _build_execution_realism_summary(
        items=items,
        account_total_value=account_total_value,
        available_cash=available_cash,
        liquidity_reserve_min=liquidity_reserve_min,
        minimum_trade_amount=minimum_trade_amount,
        transaction_fee_rate=transaction_fee_rate,
    )
    if execution_realism_summary is not None and not execution_realism_summary.executable:
        warnings.extend(
            [
                f"执行真实性约束未通过: {reason}"
                for reason in execution_realism_summary.reasons
                if f"执行真实性约束未通过: {reason}" not in warnings
            ]
        )

    product_proxy_specs = _build_selected_plan_proxy_specs(items)
    proxy_universe_summary = _build_proxy_universe_summary(
        normalized_targets=normalized_targets,
        runtime_candidates=runtime_candidate_pool,
        selected_items=items,
        product_proxy_specs=product_proxy_specs,
    )

    return ExecutionPlan(
        plan_id=f"{source_run_id}:{source_allocation_id}",
        source_run_id=source_run_id,
        source_allocation_id=source_allocation_id,
        items=items,
        warnings=warnings,
        plan_version=max(int(plan_version), 1),
        registry_candidate_count=len(registry),
        runtime_candidate_count=len(runtime_candidate_pool),
        runtime_candidates=runtime_candidate_pool,
        product_proxy_specs=product_proxy_specs,
        proxy_universe_summary=proxy_universe_summary,
        execution_realism_summary=execution_realism_summary,
        candidate_filter_breakdown=candidate_filter_breakdown,
        valuation_audit_summary=dict(candidate_filter_breakdown.valuation_audit_summary or {}),
        policy_news_audit_summary=dict(candidate_filter_breakdown.policy_news_audit_summary or {}),
    )
