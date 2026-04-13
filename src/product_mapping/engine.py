from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from shared.audit import AuditWindow, DataStatus, ExecutionPolicy, FailureArtifact, coerce_data_status, coerce_execution_policy
from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.profile_parser import parse_profile_semantics
from shared.providers.timeseries import fetch_timeseries

from product_mapping.cardinality import BucketCardinalityPreference, BucketCountResolution, resolve_bucket_count
from product_mapping.construction import (
    build_bucket_construction_explanation,
    build_bucket_subset,
    profile_aware_candidate_sort_key,
    split_bucket_weight,
)
from product_mapping.catalog import load_builtin_catalog
from product_mapping.policy_news import apply_policy_news_scores
from product_mapping.search_expansion import SearchExpansionLevels, normalize_search_expansion_level
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
    RecommendationRankingContext,
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
_FEE_RETURN_DRAG = {"low": 0.0015, "medium": 0.0030, "high": 0.0050}
_LIQUIDITY_RETURN_DRAG = {"high": 0.0, "medium": 0.0010, "low": 0.0025}
_LIQUIDITY_VOL_MULTIPLIER = {"high": 1.00, "medium": 1.04, "low": 1.10}
_WRAPPER_RETURN_PREMIUM = {
    "stock": 0.0060,
    "etf": 0.0010,
    "fund": 0.0,
    "cash_mgmt": -0.0010,
    "bond": 0.0,
    "other": 0.0,
}
_WRAPPER_VOL_MULTIPLIER = {
    "stock": 1.12,
    "etf": 1.02,
    "fund": 1.04,
    "cash_mgmt": 0.30,
    "bond": 0.95,
    "other": 1.05,
}
_CORE_TAKE_PROFIT_THRESHOLD = 0.12
_SATELLITE_TAKE_PROFIT_THRESHOLD = 0.15
_DRAWDOWN_ADD_BUY_THRESHOLD = 0.10
_REBALANCE_BAND = 0.10
_PRODUCT_SIMULATION_CACHE_DIR = Path.home() / ".cache" / "investment_system" / "timeseries"


@dataclass(frozen=True)
class _RestrictionFilter:
    allowed_buckets: set[str]
    forbidden_buckets: set[str]
    allowed_wrappers: set[str]
    forbidden_wrappers: set[str]
    allowed_regions: set[str]
    forbidden_regions: set[str]
    forbidden_themes: set[str]
    forbidden_risk_labels: set[str]
    qdii_allowed: bool | None
    warnings: list[str]


def _product_universe_source_summary(
    universe_inputs: dict[str, Any] | None,
    universe_result: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = dict(universe_inputs or {})
    result = dict(universe_result or {})
    requested = bool(inputs.get("requested") or universe_result is not None)
    return {
        "requested": requested,
        "require_observed_source": bool(inputs.get("require_observed_source", False)),
        "source_status": str(result.get("source_status") or ("missing" if requested else "not_requested")),
        "source_name": result.get("source_name"),
        "source_ref": result.get("source_ref"),
        "as_of": result.get("as_of"),
        "snapshot_id": result.get("snapshot_id"),
        "item_count": result.get("item_count"),
        "data_status": result.get("data_status"),
    }


def _resolve_product_universe_payload(
    candidate: ProductCandidate,
    universe_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not universe_result:
        return None
    product_map = dict(universe_result.get("products") or {})
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


def _normalize_bucket(bucket: str) -> str:
    normalized = str(bucket).strip().lower()
    return _BUCKET_ALIASES.get(normalized, normalized)


def _normalize_bucket_targets(bucket_targets: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for bucket, weight in bucket_targets.items():
        canonical_bucket = _normalize_bucket(bucket)
        normalized[canonical_bucket] = round(normalized.get(canonical_bucket, 0.0) + float(weight), 4)
    return normalized


def _merge_cash_parking_and_reserve(
    bucket_targets: dict[str, float],
    *,
    parked_cash_weight: float,
    liquidity_reserve_min: float | None,
) -> dict[str, float]:
    adjusted = {bucket: max(float(weight or 0.0), 0.0) for bucket, weight in bucket_targets.items()}
    if parked_cash_weight > 0.0:
        adjusted["cash_liquidity"] = adjusted.get("cash_liquidity", 0.0) + parked_cash_weight
    current_non_cash = sum(weight for bucket, weight in adjusted.items() if bucket != "cash_liquidity")
    current_cash = max(adjusted.get("cash_liquidity", 0.0), max(1.0 - current_non_cash, 0.0))
    desired_cash = max(current_cash, float(liquidity_reserve_min or 0.0))
    if current_non_cash > 0.0 and current_non_cash > max(1.0 - desired_cash, 0.0) + 1e-9:
        scale = max(1.0 - desired_cash, 0.0) / current_non_cash
        for bucket, weight in list(adjusted.items()):
            if bucket == "cash_liquidity":
                continue
            adjusted[bucket] = weight * scale
        adjusted["cash_liquidity"] = desired_cash
    else:
        adjusted["cash_liquidity"] = desired_cash
    return _normalize_bucket_targets(adjusted)


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
    forbidden_risk_labels = {str(label).strip().lower() for label in parsed.forbidden_risk_labels}
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
        forbidden_risk_labels={label for label in forbidden_risk_labels if label},
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


_HIGH_RISK_PRODUCT_LABELS = {
    "个股波动",
    "集中度",
    "主题波动",
    "汇率波动",
    "海外市场",
}


def _risk_reason(candidate: ProductCandidate, restriction_filter: _RestrictionFilter) -> str | None:
    if "high_risk_product" not in restriction_filter.forbidden_risk_labels:
        return None
    candidate_risk_labels = {str(label).strip() for label in candidate.risk_labels}
    if candidate.wrapper_type == "stock":
        return "risk_label:high_risk_product"
    if candidate_risk_labels & _HIGH_RISK_PRODUCT_LABELS:
        return "risk_label:high_risk_product"
    return None


def _profile_aware_candidate_sort_key(
    runtime_candidate: RuntimeProductCandidate,
    *,
    bucket: str,
    ranking_context: RecommendationRankingContext | None,
) -> tuple[float, ...]:
    return profile_aware_candidate_sort_key(
        runtime_candidate,
        bucket=bucket,
        ranking_context=ranking_context,
    )


def _candidate_sort_key(
    runtime_candidate: RuntimeProductCandidate,
    *,
    bucket: str,
    ranking_context: RecommendationRankingContext | None,
) -> tuple[float | int | str, ...]:
    candidate = runtime_candidate.candidate
    return (
        *_profile_aware_candidate_sort_key(
            runtime_candidate,
            bucket=bucket,
            ranking_context=ranking_context,
        ),
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
    if candidate.wrapper_type != "stock":
        theme_map = dict(valuation_result.get("theme_proxies") or {})
        normalized_tags = {str(tag).strip().lower() for tag in candidate.tags}
        for theme in ("technology", "cyclical", "consumer", "healthcare", "defensive"):
            if theme in normalized_tags and theme in theme_map:
                payload = dict(theme_map.get(theme) or {})
                payload.setdefault("product_key", f"theme:{theme}")
                payload.setdefault("valuation_mode", "holdings_proxy")
                return payload
        bucket_map = dict(valuation_result.get("bucket_proxies") or {})
        bucket_key = _normalize_bucket(candidate.asset_bucket)
        if bucket_key and bucket_key in bucket_map:
            payload = dict(bucket_map.get(bucket_key) or {})
            payload.setdefault("product_key", f"bucket:{bucket_key}")
            payload.setdefault("valuation_mode", "holdings_proxy" if bucket_key == "satellite" else "index_proxy")
            return payload
    return None


def _valuation_source_summary(
    valuation_inputs: dict[str, Any] | None,
    valuation_result: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = dict(valuation_inputs or {})
    result = dict(valuation_result or {})
    requested = bool(inputs.get("requested") or valuation_result is not None)
    return {
        "requested": requested,
        "require_observed_source": bool(inputs.get("require_observed_source", False)),
        "source_status": str(result.get("source_status") or ("missing" if requested else "not_requested")),
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
            valuation_mode="not_applicable",
            source_name=summary["source_name"],
            source_ref=summary["source_ref"],
            as_of=summary["as_of"],
            passed_filters=None,
            reason="valuation:not_applicable",
        ), None

    payload = _resolve_valuation_payload(candidate, valuation_result)
    payload_data_status = None
    payload_source_name = summary["source_name"]
    payload_source_ref = summary["source_ref"]
    payload_as_of = summary["as_of"]
    if payload is not None and payload.get("data_status") is not None:
        payload_data_status = coerce_data_status(payload.get("data_status")).value
    if payload is not None:
        payload_source_name = str(payload.get("source_name") or payload_source_name)
        payload_source_ref = str(payload.get("source_ref") or payload_source_ref)
        payload_as_of = str(payload.get("as_of") or payload_as_of)
    elif summary["source_status"] == "observed":
        payload_data_status = DataStatus.OBSERVED.value
    if (
        summary["source_status"] != "observed"
        or not payload
        or str(payload.get("status") or "missing") != "observed"
    ):
        if summary["source_status"] == "observed" and payload is None and candidate.wrapper_type != "stock":
            return ProductValuationAudit(
                status="not_applicable",
                valuation_mode="not_applicable",
                source_name=payload_source_name,
                source_ref=payload_source_ref,
                as_of=payload_as_of,
                data_status=payload_data_status or DataStatus.MANUAL_ANNOTATION.value,
                passed_filters=None,
                reason="valuation:not_applicable",
            ), None
        reason = "valuation:missing_observed_source"
        audit = ProductValuationAudit(
            status="missing_source",
            valuation_mode=None,
            source_name=payload_source_name,
            source_ref=payload_source_ref,
            as_of=payload_as_of,
            data_status=payload_data_status or DataStatus.PRIOR_DEFAULT.value,
            passed_filters=False,
            reason=reason,
        )
        if summary["require_observed_source"]:
            return audit, reason
        return audit, None

    pe_ratio = payload.get("pe_ratio")
    pb_ratio = payload.get("pb_ratio")
    percentile = payload.get("percentile")
    valuation_mode = str(payload.get("valuation_mode") or ("direct_observed" if candidate.wrapper_type == "stock" else "index_proxy"))
    audit_window = AuditWindow.from_any(payload.get("audit_window"))
    if pe_ratio is None or percentile is None:
        reason = "valuation:missing_metrics"
        return ProductValuationAudit(
            status="missing_metrics",
            valuation_mode=valuation_mode,
            source_name=payload_source_name,
            source_ref=payload_source_ref,
            as_of=payload_as_of,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            percentile=percentile,
            data_status=payload_data_status or DataStatus.OBSERVED.value,
            audit_window=audit_window,
            passed_filters=False,
            reason=reason,
        ), reason

    pe_ratio = float(pe_ratio)
    percentile = float(percentile)
    pb_ratio = None if pb_ratio is None else float(pb_ratio)
    if pe_ratio > _VALUATION_MAX_PE:
        reason = "valuation:pe_above_40"
        return ProductValuationAudit(
            status="observed",
            valuation_mode=valuation_mode,
            source_name=payload_source_name,
            source_ref=payload_source_ref,
            as_of=payload_as_of,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            percentile=percentile,
            data_status=payload_data_status or DataStatus.OBSERVED.value,
            audit_window=audit_window,
            passed_filters=False,
            reason=reason,
        ), reason
    if percentile > _VALUATION_MAX_PERCENTILE:
        reason = "valuation:percentile_above_0.30"
        return ProductValuationAudit(
            status="observed",
            valuation_mode=valuation_mode,
            source_name=payload_source_name,
            source_ref=payload_source_ref,
            as_of=payload_as_of,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            percentile=percentile,
            data_status=payload_data_status or DataStatus.OBSERVED.value,
            audit_window=audit_window,
            passed_filters=False,
            reason=reason,
        ), reason
    return ProductValuationAudit(
        status="observed",
        valuation_mode=valuation_mode,
        source_name=payload_source_name,
        source_ref=payload_source_ref,
        as_of=payload_as_of,
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        percentile=percentile,
        data_status=payload_data_status or DataStatus.OBSERVED.value,
        audit_window=audit_window,
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
    ranking_context: RecommendationRankingContext | None = None,
    primary_runtime_candidate: RuntimeProductCandidate | None = None,
    account_total_value: float | None = None,
    current_weight: float | None = None,
    minimum_trade_amount: float | None = None,
    initial_deploy_fraction: float = 0.40,
    transaction_fee_rate: dict[str, float] | None = None,
    wrapper_slippage_rate: dict[str, float] | None = None,
) -> ExecutionPlanItem:
    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: _candidate_sort_key(
            candidate,
            bucket=bucket,
            ranking_context=ranking_context,
        ),
    )
    if primary_runtime_candidate is not None:
        forced_product_id = primary_runtime_candidate.candidate.product_id
        primary_runtime_candidate = next(
            (item for item in ordered_candidates if item.candidate.product_id == forced_product_id),
            primary_runtime_candidate,
        )
        alternate_runtime_candidates = [
            item for item in ordered_candidates if item.candidate.product_id != primary_runtime_candidate.candidate.product_id
        ]
    else:
        primary_runtime_candidate = ordered_candidates[0]
        alternate_runtime_candidates = ordered_candidates[1:]
    primary_product = primary_runtime_candidate.candidate
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
        if current_weight is not None:
            current_amount = round(total_value * float(current_weight), 2)
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
    trigger_conditions: list[str] = []
    if trade_direction == "buy" and initial_trade_amount is not None:
        trigger_conditions.append(
            f"首笔执行 {initial_trade_amount:.2f} 元；剩余 {float(deferred_trade_amount or 0.0):.2f} 元在回撤达到10%时分批执行。"
        )
    elif trade_direction == "sell" and initial_trade_amount is not None:
        trigger_conditions.append(
            f"首笔卖出 {initial_trade_amount:.2f} 元；剩余 {float(deferred_trade_amount or 0.0):.2f} 元在再平衡触发时继续执行。"
        )
    if bucket == "satellite":
        trigger_conditions.append("若卫星仓收益达到15%，分批止盈并回补现金底仓。")
    elif bucket != "cash_liquidity":
        trigger_conditions.append("若核心仓收益达到12%，分批止盈并回到目标权重带。")
    if bucket != "cash_liquidity":
        trigger_conditions.append("当目标权重偏离超过10%时，执行再平衡。")
    else:
        trigger_conditions.append("保持现金/流动性底仓，用于后续补仓与执行缓冲。")

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
        trigger_conditions=trigger_conditions,
        primary_product_id=primary_product.product_id,
        alternate_product_ids=[product.product_id for product in alternate_products],
        rationale=rationale,
        risk_labels=sorted(set(primary_product.risk_labels)),
        primary_product=primary_product,
        alternate_products=alternate_products,
        valuation_audit=primary_runtime_candidate.valuation_audit,
        policy_news_audit=item_policy_news_audit,
    )


def _build_maintenance_policy_summary(
    *,
    items: list[ExecutionPlanItem],
    cash_reserve_target_amount: float | None,
    initial_deploy_fraction: float,
) -> dict[str, Any]:
    triggered_signal_ids = sorted(
        {
            signal_id
            for item in items
            for signal_id in list((item.policy_news_audit.matched_signal_ids if item.policy_news_audit is not None else []) or [])
            if str(signal_id).strip()
        }
    )
    triggered_product_ids = sorted(
        {
            item.primary_product_id
            for item in items
            if item.policy_news_audit is not None
            and item.policy_news_audit.realtime_eligible
            and bool(item.policy_news_audit.matched_signal_ids)
        }
    )
    signal_data_statuses = sorted(
        {
            str(item.policy_news_audit.data_status or "").strip()
            for item in items
            if item.policy_news_audit is not None and str(item.policy_news_audit.data_status or "").strip()
        }
    )
    signal_confidence_statuses = sorted(
        {
            str(item.policy_news_audit.confidence_data_status or "").strip()
            for item in items
            if item.policy_news_audit is not None and str(item.policy_news_audit.confidence_data_status or "").strip()
        }
    )
    return {
        "initial_deploy_fraction": round(float(initial_deploy_fraction), 4),
        "drawdown_add_buy_threshold": _DRAWDOWN_ADD_BUY_THRESHOLD,
        "core_take_profit_threshold": _CORE_TAKE_PROFIT_THRESHOLD,
        "satellite_take_profit_threshold": _SATELLITE_TAKE_PROFIT_THRESHOLD,
        "rebalance_band": _REBALANCE_BAND,
        "cash_reserve_target_amount": cash_reserve_target_amount,
        "covered_buckets": [item.asset_bucket for item in items],
        "triggered_signal_ids": triggered_signal_ids,
        "triggered_product_ids": triggered_product_ids,
        "signal_data_status": signal_data_statuses[0] if len(signal_data_statuses) == 1 else signal_data_statuses,
        "signal_confidence_data_status": (
            signal_confidence_statuses[0] if len(signal_confidence_statuses) == 1 else signal_confidence_statuses
        ),
        "disclosure": (
            "当前维护规则为账户层执行政策：首笔40%，剩余仓位在回撤10%时分批执行；"
            "核心仓止盈阈值12%，卫星仓止盈阈值15%，权重偏离10%触发再平衡。"
        ),
    }


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


def _resolve_product_proxy_payload(
    candidate: ProductCandidate,
    proxy_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = dict(proxy_result or {})
    products = dict(result.get("products") or {})
    keys = [
        candidate.product_id,
        str(candidate.provider_symbol or "").strip(),
        f"{candidate.provider_source}:{candidate.provider_symbol or candidate.product_id}",
    ]
    for key in keys:
        if key and key in products:
            return dict(products.get(key) or {})
    return None


def _build_product_proxy_spec(
    candidate: ProductCandidate,
    proxy_result: dict[str, Any] | None = None,
) -> ProductProxySpec:
    proxy_ref = f"{candidate.provider_source}:{candidate.provider_symbol or candidate.product_id}"
    payload = _resolve_product_proxy_payload(candidate, proxy_result)
    if payload and str(payload.get("status") or "").strip().lower() == "observed":
        confidence = float(payload.get("confidence", _PROXY_CONFIDENCE_BY_WRAPPER.get(candidate.wrapper_type, 0.70)) or 0.0)
        confidence_status = str(payload.get("confidence_data_status") or "observed")
        confidence_disclosure = str(
            payload.get("confidence_disclosure")
            or "proxy confidence is backed by observed proxy coverage metadata, not a pure heuristic wrapper score."
        )
        observed_proxy_ref = str(payload.get("proxy_ref") or proxy_ref)
        observed_source_ref = str(payload.get("source_ref") or observed_proxy_ref)
        observed_data_status = str(payload.get("data_status") or "observed")
        return ProductProxySpec(
            product_id=candidate.product_id,
            proxy_kind=str(payload.get("proxy_kind") or _proxy_kind(candidate)),
            proxy_ref=observed_proxy_ref,
            confidence=confidence,
            confidence_data_status=confidence_status,
            confidence_disclosure=confidence_disclosure,
            source_ref=observed_source_ref,
            data_status=observed_data_status,
            as_of=str(payload.get("as_of") or "") or None,
        )
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


def _attach_proxy_specs(
    runtime_candidates: list[RuntimeProductCandidate],
    *,
    proxy_result: dict[str, Any] | None = None,
) -> tuple[list[RuntimeProductCandidate], list[ProductProxySpec]]:
    proxy_specs: list[ProductProxySpec] = []
    enriched: list[RuntimeProductCandidate] = []
    for runtime_candidate in runtime_candidates:
        proxy_spec = _build_product_proxy_spec(runtime_candidate.candidate, proxy_result)
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
    proxy_data_status = "manual_annotation"
    if product_proxy_specs:
        statuses = {str(spec.data_status or "").strip() for spec in product_proxy_specs if str(spec.data_status or "").strip()}
        if statuses == {"observed"}:
            proxy_data_status = "observed"
        elif statuses and statuses != {"manual_annotation"}:
            proxy_data_status = "computed_from_observed"
    return ProxyUniverseSummary(
        solving_mode="proxy_universe",
        proxy_scope="selected_plan_items",
        covered_asset_buckets=covered_buckets,
        uncovered_asset_buckets=uncovered_buckets,
        covered_regions=covered_regions,
        product_proxy_count=len(product_proxy_specs),
        runtime_candidate_proxy_count=len(runtime_candidates),
        data_status=proxy_data_status,
        claims_real_product_history=False,
        disclosure=(
            "当前仍是代理宇宙求解：plan 级 proxy 披露仅覆盖执行计划中实际选中的产品，"
            "不是整个 runtime candidate pool，也不应解读为每个产品都已有独立历史序列进入求解器。"
        ),
    )


def _build_selected_plan_proxy_specs(
    items: list[ExecutionPlanItem],
    *,
    proxy_result: dict[str, Any] | None = None,
) -> list[ProductProxySpec]:
    selected_products: dict[str, ProductCandidate] = {}
    for item in items:
        selected_products[item.primary_product.product_id] = item.primary_product
        for product in item.alternate_products:
            selected_products[product.product_id] = product
    return [
        _build_product_proxy_spec(candidate, proxy_result)
        for candidate in sorted(selected_products.values(), key=lambda candidate: candidate.product_id)
    ]


def _proxy_spec_by_product_id(product_proxy_specs: list[ProductProxySpec]) -> dict[str, ProductProxySpec]:
    return {spec.product_id: spec for spec in product_proxy_specs}


def _policy_return_adjustment(policy_news_audit: ProductPolicyNewsAudit | None) -> float:
    if policy_news_audit is None or not policy_news_audit.realtime_eligible:
        return 0.0
    score = float(policy_news_audit.score or 0.0)
    if policy_news_audit.influence_scope == "satellite_dynamic":
        return max(min(score * 0.010, 0.010), -0.010)
    if policy_news_audit.influence_scope == "core_mild":
        return max(min(score * 0.004, 0.004), -0.004)
    return 0.0


def _policy_volatility_multiplier(policy_news_audit: ProductPolicyNewsAudit | None) -> float:
    if policy_news_audit is None or not policy_news_audit.realtime_eligible:
        return 1.0
    score = abs(float(policy_news_audit.score or 0.0))
    if policy_news_audit.influence_scope == "satellite_dynamic":
        return 1.0 + min(score * 0.08, 0.12)
    if policy_news_audit.influence_scope == "core_mild":
        return 1.0 + min(score * 0.03, 0.05)
    return 1.0


def _product_context_adjustment(
    item: ExecutionPlanItem,
    proxy_spec: ProductProxySpec | None,
) -> tuple[float, float]:
    primary = item.primary_product
    return_adjustment = 0.0
    volatility_multiplier = 1.0

    return_adjustment -= _FEE_RETURN_DRAG.get(primary.fee_tier, 0.0030)
    return_adjustment -= _LIQUIDITY_RETURN_DRAG.get(primary.liquidity_tier, 0.0010)
    return_adjustment += _WRAPPER_RETURN_PREMIUM.get(primary.wrapper_type, 0.0)
    volatility_multiplier *= _LIQUIDITY_VOL_MULTIPLIER.get(primary.liquidity_tier, 1.04)
    volatility_multiplier *= _WRAPPER_VOL_MULTIPLIER.get(primary.wrapper_type, 1.04)

    if "qdii" in primary.tags or str(primary.region or "").upper() != "CN":
        return_adjustment += 0.0030
        volatility_multiplier *= 1.08

    if item.valuation_audit is not None and item.valuation_audit.status == "observed":
        if item.valuation_audit.passed_filters:
            return_adjustment += 0.0040
        elif item.valuation_audit.passed_filters is False:
            return_adjustment -= 0.0030

    return_adjustment += _policy_return_adjustment(item.policy_news_audit)
    volatility_multiplier *= _policy_volatility_multiplier(item.policy_news_audit)

    if proxy_spec is not None:
        confidence_penalty = max(0.0, 0.90 - float(proxy_spec.confidence or 0.0))
        return_adjustment -= confidence_penalty * 0.02
        if str(proxy_spec.data_status or "").strip() != "observed":
            volatility_multiplier *= 1.04

    return round(return_adjustment, 6), round(volatility_multiplier, 6)


def _product_simulation_provider(candidate: ProductCandidate, preferred_provider: str | None) -> str:
    provider_source = str(candidate.provider_source or "").strip().lower()
    provider_symbol = str(candidate.provider_symbol or "").strip().upper()
    if "tinyshare" in provider_source:
        return "tinyshare"
    if "baostock" in provider_source:
        return "baostock"
    if "yfinance" in provider_source:
        return "yfinance"
    if preferred_provider:
        return preferred_provider
    if provider_symbol.endswith((".SH", ".SZ", ".BJ")):
        return "tinyshare"
    return "yfinance"


def _product_simulation_symbol(candidate: ProductCandidate, provider: str) -> str | None:
    symbol = str(candidate.provider_symbol or "").strip()
    if not symbol:
        return None
    if provider != "yfinance":
        return symbol
    upper = symbol.upper()
    if upper.endswith(".SH"):
        return upper.replace(".SH", ".SS")
    return upper


def _product_return_series_from_rows(rows: list[dict[str, Any]]) -> list[float]:
    closes = [float(item["close"]) for item in rows if item.get("close") is not None]
    if len(closes) < 2:
        return []
    return [(closes[idx] / closes[idx - 1]) - 1.0 for idx in range(1, len(closes))]


def _product_observation_dates_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    dates = [str(item.get("date")).strip() for item in rows if item.get("close") is not None and item.get("date")]
    if len(dates) < 2:
        return []
    return dates[1:]


def _synthetic_cash_observation_dates(
    history_window: AuditWindow,
    *,
    reference_dates: list[str] | None,
) -> list[str]:
    if reference_dates:
        return [str(item).strip() for item in reference_dates if str(item).strip()]
    trading_days = int(history_window.trading_days or 0)
    if trading_days <= 1:
        end_date = str(history_window.end_date or "").strip()
        return [end_date] if end_date else []
    try:
        current = date.fromisoformat(str(history_window.start_date))
    except Exception:
        return []
    dates: list[str] = []
    while len(dates) < trading_days - 1:
        current += timedelta(days=1)
        dates.append(current.isoformat())
    return dates


def _preloaded_product_simulation_payload(
    historical_dataset: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = (historical_dataset or {}).get("product_simulation_input")
    if isinstance(payload, dict):
        return dict(payload)
    payload = (historical_dataset or {}).get("product_simulation_inputs")
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _preloaded_product_simulation_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        return []
    return [dict(item) for item in raw_products if isinstance(item, dict)]


def _preloaded_product_simulation_values(values: Any) -> list[Any]:
    if not isinstance(values, list):
        return []
    return list(values)


def _preloaded_product_simulation_entry(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    return dict(values)


def _preloaded_product_simulation_map(
    historical_dataset: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    payload = _preloaded_product_simulation_payload(historical_dataset)
    products = {}
    for item in _preloaded_product_simulation_products(payload):
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        products[product_id] = item
    return products


def _build_product_simulation_input(
    items: list[ExecutionPlanItem],
    *,
    historical_dataset: dict[str, Any] | None,
    history_window: AuditWindow | None,
    formal_path_required: bool = False,
    execution_policy: ExecutionPolicy | str | None = None,
) -> dict[str, Any] | None:
    if not items or history_window is None or not history_window.start_date or not history_window.end_date:
        return None
    formal_policy = (
        coerce_execution_policy(execution_policy or ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED.value)
        if formal_path_required
        else None
    )
    strict_formal = formal_policy == ExecutionPolicy.FORMAL_STRICT
    preferred_provider = str((historical_dataset or {}).get("source_name") or "").strip().lower() or None
    cache = DatasetCache(base_dir=_PRODUCT_SIMULATION_CACHE_DIR)
    preloaded_payload = _preloaded_product_simulation_payload(historical_dataset)
    preloaded_products = _preloaded_product_simulation_map(historical_dataset)
    preloaded_frequency = str(preloaded_payload.get("frequency") or "daily").strip() or "daily"
    products: list[dict[str, Any]] = []
    observed_count = 0
    inferred_count = 0
    missing_count = 0
    reference_dates: list[str] | None = None
    cash_items: list[ExecutionPlanItem] = []
    for item in items:
        if item.asset_bucket == "cash_liquidity":
            cash_items.append(item)
            continue
        candidate = item.primary_product
        preloaded = _preloaded_product_simulation_entry(preloaded_products.get(candidate.product_id))
        if preloaded:
            return_series = [float(value) for value in _preloaded_product_simulation_values(preloaded.get("return_series"))]
            observation_dates = [
                str(value).strip()
                for value in _preloaded_product_simulation_values(preloaded.get("observation_dates"))
                if str(value).strip()
            ]
            if return_series:
                if observation_dates and len(observation_dates) == len(return_series) and reference_dates is None:
                    reference_dates = list(observation_dates)
                observed_count += 1
                products.append(
                    {
                        "product_id": candidate.product_id,
                        "asset_bucket": item.asset_bucket,
                        "target_weight": float(item.target_weight or 0.0),
                        "return_series": return_series,
                        "observation_dates": observation_dates,
                        "source_ref": str(preloaded.get("source_ref") or f"observed://product_simulation/{candidate.product_id}"),
                        "data_status": str(preloaded.get("data_status") or DataStatus.OBSERVED.value),
                        "frequency": str(preloaded.get("frequency") or preloaded_frequency),
                        "observed_start_date": preloaded.get("observed_start_date") or history_window.start_date,
                        "observed_end_date": preloaded.get("observed_end_date") or history_window.end_date,
                        "observed_points": int(preloaded.get("observed_points") or len(return_series)),
                        "inferred_points": int(preloaded.get("inferred_points") or 0),
                    }
                )
                continue
        provider = _product_simulation_provider(candidate, preferred_provider)
        symbol = _product_simulation_symbol(candidate, provider)
        if not symbol:
            missing_count += 1
            continue
        spec = DatasetSpec(
            kind="timeseries",
            dataset_id="product_simulation",
            provider=provider,
            symbol=symbol,
        )
        pin = VersionPin(
            version_id=f"{provider}:{symbol}:{history_window.start_date}:{history_window.end_date}:product_simulation",
            source_ref=f"{provider}://{symbol}?start={history_window.start_date}&end={history_window.end_date}",
        )
        try:
            rows, used_pin = fetch_timeseries(
                spec,
                pin=pin,
                cache=cache,
                allow_fallback=not formal_path_required,
                return_used_pin=True,
            )
        except Exception:
            missing_count += 1
            continue
        return_series = _product_return_series_from_rows(rows)
        if not return_series:
            missing_count += 1
            continue
        observation_dates = _product_observation_dates_from_rows(rows)
        if observation_dates and reference_dates is None:
            reference_dates = list(observation_dates)
        observed_count += 1
        products.append(
            {
                "product_id": candidate.product_id,
                "asset_bucket": item.asset_bucket,
                "target_weight": float(item.target_weight or 0.0),
                "return_series": return_series,
                "observation_dates": observation_dates,
                "source_ref": str(used_pin.source_ref or pin.source_ref),
                "data_status": (
                    DataStatus.OBSERVED.value
                    if used_pin.version_id == pin.version_id
                    else DataStatus.COMPUTED_FROM_OBSERVED.value
                ),
                "frequency": "daily",
                "observed_start_date": history_window.start_date,
                "observed_end_date": history_window.end_date,
                "observed_points": len(return_series),
                "inferred_points": 0,
            }
        )
    for item in cash_items:
        synthetic_dates = _synthetic_cash_observation_dates(
            history_window,
            reference_dates=reference_dates,
        )
        if not synthetic_dates:
            missing_count += 1
            continue
        inferred_count += 1
        products.append(
            {
                "product_id": item.primary_product.product_id,
                "asset_bucket": item.asset_bucket,
                "target_weight": float(item.target_weight or 0.0),
                "return_series": [0.0 for _ in synthetic_dates],
                "observation_dates": synthetic_dates,
                "source_ref": (
                    f"synthetic://cash_liquidity?start={history_window.start_date}&end={history_window.end_date}"
                ),
                "data_status": DataStatus.INFERRED.value,
                "frequency": "daily",
                "observed_start_date": history_window.start_date,
                "observed_end_date": history_window.end_date,
                "observed_points": 0,
                "inferred_points": len(synthetic_dates),
            }
        )
    if not products:
        if formal_policy is not None and items:
            run_outcome_status = "blocked" if strict_formal else "degraded"
            blocking_predicates = ["product_simulation_series_unavailable"] if strict_formal else []
            degradation_reasons = [] if strict_formal else ["product_simulation_series_unavailable"]
            failure_artifact = FailureArtifact(
                request_identity={"component": "product_simulation_input"},
                requested_result_category="formal_independent_result",
                execution_policy=formal_policy.value,
                disclosure_policy="diagnostic_only",
                failed_stage="evidence_completeness",
                blocking_predicates=blocking_predicates or ["product_simulation_series_unavailable"],
                missing_evidence_refs={"product_timeseries": "missing_observed_product_returns"},
                next_recoverable_actions=["collect_product_return_series"],
                trustworthy_partial_diagnostics=False,
            )
            return {
                "products": [],
                "frequency": "daily",
                "simulation_method": "product_estimated_path",
                "audit_window": history_window.to_dict(),
                "coverage_summary": {
                    "selected_product_count": len(items),
                    "observed_product_count": observed_count,
                    "inferred_product_count": inferred_count,
                    "missing_product_count": max(missing_count, 0),
                },
                "formal_path_preflight": {
                    "formal_path_required": True,
                    "execution_policy": formal_policy.value,
                    "run_outcome_status": run_outcome_status,
                    "degradation_reasons": degradation_reasons,
                    "blocking_predicates": blocking_predicates,
                    "estimation_basis": "proxy_path",
                },
                "failure_artifact": failure_artifact.to_dict(),
            }
        return None
    formal_path_preflight = {
        "formal_path_required": formal_path_required,
        "execution_policy": None if formal_policy is None else formal_policy.value,
        "run_outcome_status": "completed",
        "degradation_reasons": [],
        "blocking_predicates": [],
    }
    failure_artifact = None
    simulation_method = "product_independent_path"
    if missing_count > 0:
        simulation_method = "product_estimated_path"
        if formal_policy is not None:
            run_outcome_status = "blocked" if strict_formal else "degraded"
            blocking_predicates = ["product_independent_coverage_incomplete"] if strict_formal else []
            degradation_reasons = [] if strict_formal else ["product_independent_coverage_incomplete"]
            formal_path_preflight = {
                "formal_path_required": True,
                "execution_policy": formal_policy.value,
                "run_outcome_status": run_outcome_status,
                "degradation_reasons": degradation_reasons,
                "blocking_predicates": blocking_predicates,
                "estimation_basis": "proxy_path",
            }
            failure_artifact = FailureArtifact(
                request_identity={"component": "product_simulation_input"},
                requested_result_category="formal_independent_result",
                execution_policy=formal_policy.value,
                disclosure_policy="diagnostic_only",
                failed_stage="evidence_completeness",
                blocking_predicates=blocking_predicates or ["product_independent_coverage_incomplete"],
                available_evidence_refs={"product_timeseries": "partial_observed_product_returns"},
                missing_evidence_refs={"product_timeseries": "missing_observed_product_returns"},
                next_recoverable_actions=["collect_missing_product_return_series"],
                trustworthy_partial_diagnostics=False,
            ).to_dict()
    return {
        "products": products,
        "frequency": preloaded_frequency if preloaded_products else "daily",
        "simulation_method": simulation_method,
        "audit_window": dict(preloaded_payload.get("audit_window") or history_window.to_dict()),
        "coverage_summary": {
            "selected_product_count": len(items),
            "observed_product_count": observed_count,
            "inferred_product_count": inferred_count,
            "missing_product_count": max(missing_count, 0),
        },
        "formal_path_preflight": formal_path_preflight,
        "failure_artifact": failure_artifact,
    }


def build_candidate_product_context(
    *,
    source_allocation_id: str,
    bucket_targets: dict[str, float],
    restrictions: list[str] | None = None,
    catalog: list[ProductCandidate] | None = None,
    runtime_candidates: list[ProductCandidate] | list[RuntimeProductCandidate] | None = None,
    product_universe_inputs: dict[str, Any] | None = None,
    product_universe_result: dict[str, Any] | None = None,
    valuation_inputs: dict[str, Any] | None = None,
    valuation_result: dict[str, Any] | None = None,
    policy_news_signals: list[dict[str, Any]] | list[Any] | None = None,
    product_proxy_result: dict[str, Any] | None = None,
    historical_dataset: dict[str, Any] | None = None,
    formal_path_required: bool = False,
    execution_policy: ExecutionPolicy | str | None = None,
) -> dict[str, Any]:
    preview_plan = build_execution_plan(
        source_run_id="solver_preview",
        source_allocation_id=source_allocation_id,
        bucket_targets=bucket_targets,
        restrictions=restrictions,
        catalog=catalog,
        runtime_candidates=runtime_candidates,
        product_universe_inputs=product_universe_inputs,
        product_universe_result=product_universe_result,
        valuation_inputs=valuation_inputs,
        valuation_result=valuation_result,
        policy_news_signals=policy_news_signals,
        product_proxy_result=product_proxy_result,
        formal_path_required=formal_path_required,
        execution_policy=execution_policy,
        account_total_value=None,
        current_weights=None,
        available_cash=None,
        liquidity_reserve_min=None,
        minimum_trade_amount=None,
    )
    proxy_specs = _proxy_spec_by_product_id(preview_plan.product_proxy_specs)
    history_window = AuditWindow.from_any((historical_dataset or {}).get("audit_window"))
    bucket_expected_return_adjustments: dict[str, float] = {}
    bucket_volatility_multipliers: dict[str, float] = {}
    selected_product_ids: list[str] = []
    selected_proxy_refs: list[str] = []
    history_profiles: list[dict[str, Any]] = []
    notes: list[str] = list(preview_plan.warnings)
    for item in preview_plan.items:
        proxy_spec = proxy_specs.get(item.primary_product.product_id)
        return_adjustment, volatility_multiplier = _product_context_adjustment(item, proxy_spec)
        bucket_expected_return_adjustments[item.asset_bucket] = return_adjustment
        bucket_volatility_multipliers[item.asset_bucket] = volatility_multiplier
        selected_product_ids.append(item.primary_product.product_id)
        if proxy_spec is not None:
            selected_proxy_refs.append(proxy_spec.proxy_ref)
        history_profiles.append(
            {
                "product_id": item.primary_product.product_id,
                "source_ref": None if proxy_spec is None else proxy_spec.source_ref,
                "observed_history_days": None if history_window is None else history_window.trading_days,
                "inferred_history_days": None if history_window is None else history_window.inferred_days,
                "inference_weight": 1.0 if proxy_spec is not None and proxy_spec.data_status == "observed" else 0.85,
                "data_status": "manual_annotation" if proxy_spec is None else proxy_spec.data_status,
            }
        )
    if preview_plan.proxy_universe_summary is not None and preview_plan.proxy_universe_summary.disclosure:
        notes.append(preview_plan.proxy_universe_summary.disclosure)
    product_simulation_input = _build_product_simulation_input(
        preview_plan.items,
        historical_dataset=historical_dataset,
        history_window=history_window,
        formal_path_required=formal_path_required,
        execution_policy=execution_policy,
    )
    product_probability_method = "product_estimated_path"
    formal_path_preflight = dict(preview_plan.formal_path_preflight or {})
    failure_artifact = None if preview_plan.failure_artifact is None else dict(preview_plan.failure_artifact)
    if product_simulation_input is not None:
        coverage_summary = dict(product_simulation_input.get("coverage_summary") or {})
        covered_count = int(coverage_summary.get("observed_product_count") or 0) + int(
            coverage_summary.get("inferred_product_count") or 0
        )
        if product_simulation_input.get("formal_path_preflight"):
            formal_path_preflight = dict(product_simulation_input.get("formal_path_preflight") or {})
        if product_simulation_input.get("failure_artifact") is not None:
            failure_artifact = dict(product_simulation_input.get("failure_artifact") or {})
        if covered_count == int(coverage_summary.get("selected_product_count") or 0) and int(
            coverage_summary.get("missing_product_count") or 0
        ) == 0:
            product_probability_method = "product_independent_path"
        elif formal_path_required:
            product_probability_method = "product_estimated_path"
        else:
            product_probability_method = "product_proxy_path"
    return {
        "allocation_name": source_allocation_id,
        "product_probability_method": product_probability_method,
        "bucket_expected_return_adjustments": bucket_expected_return_adjustments,
        "bucket_volatility_multipliers": bucket_volatility_multipliers,
        "selected_product_ids": selected_product_ids,
        "selected_proxy_refs": selected_proxy_refs,
        "product_history_profiles": history_profiles,
        "product_simulation_input": product_simulation_input,
        "formal_path_preflight": formal_path_preflight,
        "failure_artifact": failure_artifact,
        "notes": notes,
    }


def _build_execution_realism_summary(
    *,
    items: list[ExecutionPlanItem],
    account_total_value: float | None,
    requested_total_amount: float | None,
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
    explicit_cash_target_amount = round(
        sum(float(item.target_amount or 0.0) for item in items if item.asset_bucket == "cash_liquidity"),
        2,
    )
    effective_requested_total_amount = (
        total_target_amount if requested_total_amount is None else round(float(requested_total_amount), 2)
    )
    implicit_cash_target_amount = round(
        max(total_value - max(total_target_amount, effective_requested_total_amount), 0.0),
        2,
    )
    cash_target_amount = round(explicit_cash_target_amount + implicit_cash_target_amount, 2)
    amount_closure_delta = round(total_target_amount + implicit_cash_target_amount - total_value, 2)
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


def _apply_product_universe_stage(
    staged_candidates: list[tuple[int, ProductCandidate]],
    *,
    universe_inputs: dict[str, Any] | None,
    universe_result: dict[str, Any] | None,
) -> tuple[list[tuple[int, ProductCandidate]], CandidateFilterStage, dict[str, Any]]:
    summary = _product_universe_source_summary(universe_inputs, universe_result)
    if not summary["requested"]:
        return staged_candidates, CandidateFilterStage(
            stage_name="product_universe",
            input_count=len(staged_candidates),
            output_count=len(staged_candidates),
            dropped_reasons={},
            audit_fields=summary,
        ), {
            **summary,
            "applicable_candidate_count": 0,
            "observed_candidate_count": 0,
            "tradable_candidate_count": 0,
            "dropped_candidate_count": 0,
        }

    dropped_reasons: dict[str, int] = {}
    kept: list[tuple[int, ProductCandidate]] = []
    applicable_count = 0
    observed_count = 0
    tradable_count = 0
    dropped_count = 0
    source_status = summary["source_status"]

    for registry_index, candidate in staged_candidates:
        payload = _resolve_product_universe_payload(candidate, universe_result)
        if payload is None:
            if summary["require_observed_source"]:
                reason = "product_universe:missing_observed_entry"
                dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
                dropped_count += 1
                continue
            kept.append((registry_index, candidate))
            continue

        applicable_count += 1
        entry_status = str(payload.get("status") or source_status or "missing").strip().lower()
        if entry_status == "observed":
            observed_count += 1
        if source_status != "observed" or entry_status != "observed":
            if summary["require_observed_source"]:
                reason = "product_universe:missing_observed_source"
                dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
                dropped_count += 1
                continue
            kept.append((registry_index, candidate))
            continue

        tradable = payload.get("tradable")
        if tradable is None:
            tradable = payload.get("tradeable")
        if bool(tradable):
            tradable_count += 1
            kept.append((registry_index, candidate))
            continue

        reason = "product_universe:not_tradable"
        dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
        dropped_count += 1

    audit_summary = {
        **summary,
        "applicable_candidate_count": applicable_count,
        "observed_candidate_count": observed_count,
        "tradable_candidate_count": tradable_count,
        "dropped_candidate_count": dropped_count,
    }
    return kept, CandidateFilterStage(
        stage_name="product_universe",
        input_count=len(staged_candidates),
        output_count=len(kept),
        dropped_reasons=dropped_reasons,
        audit_fields=audit_summary,
    ), audit_summary


def _build_runtime_candidate_pool(
    registry: list[ProductCandidate],
    restriction_filter: _RestrictionFilter,
    *,
    runtime_candidates: list[ProductCandidate] | list[RuntimeProductCandidate] | None = None,
    product_universe_inputs: dict[str, Any] | None = None,
    product_universe_result: dict[str, Any] | None = None,
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
    product_universe_audit_summary: dict[str, Any] = {}

    staged_candidates, stage = _apply_stage("availability", staged_candidates, _availability_reason)
    stages.append(stage)
    staged_candidates, stage, product_universe_audit_summary = _apply_product_universe_stage(
        staged_candidates,
        universe_inputs=product_universe_inputs,
        universe_result=product_universe_result,
    )
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
    staged_candidates, stage = _apply_stage(
        "risk_restrictions",
        staged_candidates,
        lambda candidate: _risk_reason(candidate, restriction_filter),
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
        product_universe_audit_summary=product_universe_audit_summary,
        valuation_audit_summary=valuation_audit_summary,
        policy_news_audit_summary=policy_news_audit_summary,
    )


def build_execution_plan(
    *,
    source_run_id: str,
    source_allocation_id: str,
    bucket_targets: dict[str, float],
    bucket_count_preferences: list[BucketCardinalityPreference] | None = None,
    goal_horizon_months: int | None = None,
    risk_preference: str | None = None,
    max_drawdown_tolerance: float | None = None,
    current_market_pressure_score: float | None = None,
    required_return_gap: float | None = None,
    implied_required_annual_return: float | None = None,
    restrictions: list[str] | None = None,
    plan_version: int = 1,
    catalog: list[ProductCandidate] | None = None,
    runtime_candidates: list[ProductCandidate] | list[RuntimeProductCandidate] | None = None,
    product_universe_inputs: dict[str, Any] | None = None,
    product_universe_result: dict[str, Any] | None = None,
    valuation_inputs: dict[str, Any] | None = None,
    valuation_result: dict[str, Any] | None = None,
    policy_news_signals: list[dict[str, Any]] | list[Any] | None = None,
    product_proxy_result: dict[str, Any] | None = None,
    account_total_value: float | None = None,
    current_weights: dict[str, float] | None = None,
    available_cash: float | None = None,
    liquidity_reserve_min: float | None = None,
    minimum_trade_amount: float | None = 500.0,
    initial_deploy_fraction: float = 0.40,
    transaction_fee_rate: dict[str, float] | None = None,
    wrapper_slippage_rate: dict[str, float] | None = None,
    search_expansion_level: str = SearchExpansionLevels.L0_COMPACT,
    formal_path_required: bool = False,
    execution_policy: ExecutionPolicy | str | None = None,
) -> ExecutionPlan:
    formal_policy = (
        coerce_execution_policy(execution_policy or ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED.value)
        if formal_path_required
        else None
    )
    normalized_targets = _normalize_bucket_targets(bucket_targets)
    normalized_current_weights = _normalize_bucket_targets(current_weights or {})
    restriction_filter = _compile_restrictions(restrictions)
    if catalog is not None:
        registry = list(catalog)
    elif runtime_candidates is not None:
        registry = [
            entry.candidate if isinstance(entry, RuntimeProductCandidate) else entry
            for entry in runtime_candidates
        ]
    elif formal_policy is not None:
        registry = []
    else:
        registry = list(load_builtin_catalog())
    runtime_candidate_pool, candidate_filter_breakdown = _build_runtime_candidate_pool(
        registry,
        restriction_filter,
        runtime_candidates=runtime_candidates,
        product_universe_inputs=product_universe_inputs,
        product_universe_result=product_universe_result,
        valuation_inputs=valuation_inputs,
        valuation_result=valuation_result,
        policy_news_signals=policy_news_signals,
    )
    runtime_candidate_pool, _runtime_pool_proxy_specs = _attach_proxy_specs(
        runtime_candidate_pool,
        proxy_result=product_proxy_result,
    )
    grouped_candidates: dict[str, list[RuntimeProductCandidate]] = defaultdict(list)

    for runtime_candidate in runtime_candidate_pool:
        grouped_candidates[_normalize_bucket(runtime_candidate.candidate.asset_bucket)].append(runtime_candidate)

    if not grouped_candidates.get("cash_liquidity") and formal_policy is None:
        cash_fallback_candidates = [
            RuntimeProductCandidate(candidate=item, registry_index=-1)
            for item in (list(catalog) if catalog is not None else list(load_builtin_catalog()))
            if _normalize_bucket(item.asset_bucket) == "cash_liquidity"
        ]
        if cash_fallback_candidates:
            grouped_candidates["cash_liquidity"].extend(cash_fallback_candidates)

    parked_cash_weight = 0.0
    adjusted_targets = dict(normalized_targets)
    warnings = list(restriction_filter.warnings)
    formal_path_preflight: dict[str, Any] = {
        "formal_path_required": formal_path_required,
        "execution_policy": None if formal_policy is None else formal_policy.value,
        "run_outcome_status": "completed",
    }
    failure_artifact = None
    product_universe_failure_artifact = (
        (product_universe_inputs or {}).get("failure_artifact")
        or (product_universe_result or {}).get("failure_artifact")
    )
    valuation_failure_artifact = (
        (valuation_inputs or {}).get("failure_artifact")
        or (valuation_result or {}).get("failure_artifact")
    )
    if formal_policy is not None and product_universe_failure_artifact is not None:
        failure_artifact = dict(product_universe_failure_artifact)
        formal_path_preflight = {
            "formal_path_required": True,
            "execution_policy": formal_policy.value,
            "run_outcome_status": "blocked",
            "blocking_predicates": list((failure_artifact or {}).get("blocking_predicates") or []),
            "degradation_reasons": [],
        }
        warnings.append("formal_path_blocked=product_universe_unavailable")
    elif formal_policy is not None and valuation_failure_artifact is not None:
        failure_artifact = dict(valuation_failure_artifact)
        formal_path_preflight = {
            "formal_path_required": True,
            "execution_policy": formal_policy.value,
            "run_outcome_status": "blocked",
            "blocking_predicates": list((failure_artifact or {}).get("blocking_predicates") or []),
            "degradation_reasons": [],
        }
        warnings.append("formal_path_blocked=valuation_unavailable")
    for bucket, target_weight in list(normalized_targets.items()):
        if target_weight <= 0:
            continue
        if bucket == "cash_liquidity":
            continue
        if bucket in restriction_filter.forbidden_buckets:
            warnings.append(f"资金桶 {bucket} 因用户限制被排除。")
            warnings.append(f"资金桶 {bucket} 的目标权重已临时停泊到现金/流动性桶。")
            parked_cash_weight += float(target_weight)
            adjusted_targets[bucket] = 0.0
            continue
        if restriction_filter.allowed_buckets and bucket not in restriction_filter.allowed_buckets:
            warnings.append(f"资金桶 {bucket} 不在用户允许范围内，已从执行计划移除。")
            warnings.append(f"资金桶 {bucket} 的目标权重已临时停泊到现金/流动性桶。")
            parked_cash_weight += float(target_weight)
            adjusted_targets[bucket] = 0.0
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            warnings.append(f"资金桶 {bucket} 当前没有可用产品候选。")
            warnings.append(f"资金桶 {bucket} 的目标权重已临时停泊到现金/流动性桶。")
            parked_cash_weight += float(target_weight)
            adjusted_targets[bucket] = 0.0

    if parked_cash_weight > 0.0 or liquidity_reserve_min is not None:
        adjusted_targets = _merge_cash_parking_and_reserve(
            adjusted_targets,
            parked_cash_weight=parked_cash_weight,
            liquidity_reserve_min=liquidity_reserve_min,
        )
        if liquidity_reserve_min is not None:
            warnings.append(
                f"已为执行计划预留现金/流动性底仓 {float(liquidity_reserve_min):.0%}，并按比例缩放非现金目标。"
            )

    items: list[ExecutionPlanItem] = []
    bucket_explanations: dict[str, Any] = {}
    bucket_suggestions: dict[str, dict[str, Any]] = {}
    bucket_count_preference_lookup = {
        str(preference.bucket).strip(): preference for preference in list(bucket_count_preferences or [])
    }
    effective_risk_preference = str(risk_preference or "moderate")
    effective_max_drawdown_tolerance = 0.20 if max_drawdown_tolerance is None else float(max_drawdown_tolerance)
    normalized_search_expansion_level = normalize_search_expansion_level(search_expansion_level)
    for bucket, target_weight in adjusted_targets.items():
        if target_weight <= 0:
            continue
        if bucket in restriction_filter.forbidden_buckets:
            continue
        if restriction_filter.allowed_buckets and bucket not in restriction_filter.allowed_buckets:
            continue
        bucket_candidates = grouped_candidates.get(bucket, [])
        if not bucket_candidates:
            continue
        bucket_weight = float(target_weight)
        resolved_goal_horizon_months = (
            int(goal_horizon_months)
            if goal_horizon_months is not None
            else (24 if bucket_weight >= 0.20 else 12)
        )
        ranking_context = RecommendationRankingContext(
            required_annual_return=implied_required_annual_return,
            goal_horizon_months=resolved_goal_horizon_months,
            risk_preference=effective_risk_preference,
            max_drawdown_tolerance=effective_max_drawdown_tolerance,
            market_pressure_score=current_market_pressure_score,
        )
        count_resolution = resolve_bucket_count(
            bucket=bucket,
            bucket_weight=bucket_weight,
            horizon_months=resolved_goal_horizon_months,
            goal_horizon_months=resolved_goal_horizon_months,
            risk_preference=effective_risk_preference,
            max_drawdown_tolerance=effective_max_drawdown_tolerance,
            current_market_pressure_score=current_market_pressure_score,
            required_return_gap=required_return_gap,
            implied_required_annual_return=implied_required_annual_return,
            explicit_request=bucket_count_preference_lookup.get(bucket),
        )
        selected_members = build_bucket_subset(
            bucket=bucket,
            bucket_weight=bucket_weight,
            requested_resolution=count_resolution,
            candidates=bucket_candidates,
            search_expansion_level=normalized_search_expansion_level,
            ranking_context=ranking_context,
        )
        bucket_construction_explanation = build_bucket_construction_explanation(
            bucket=bucket,
            bucket_weight=bucket_weight,
            requested_resolution=count_resolution,
            selected_members=selected_members,
            candidates=bucket_candidates,
            search_expansion_level=normalized_search_expansion_level,
            ranking_context=ranking_context,
        )
        if bucket_construction_explanation.unmet_reason:
            warnings.append(f"资金桶 {bucket} 结构约束未完全满足: {bucket_construction_explanation.unmet_reason}")
        if (
            bucket in {"equity_cn", "satellite", "bond_cn"}
            and bucket_construction_explanation.diagnostic_codes
            and bucket_count_preference_lookup.get(bucket) is not None
        ):
            suggested_resolution = resolve_bucket_count(
                bucket=bucket,
                bucket_weight=bucket_weight,
                horizon_months=resolved_goal_horizon_months,
                goal_horizon_months=resolved_goal_horizon_months,
                risk_preference=effective_risk_preference,
                max_drawdown_tolerance=effective_max_drawdown_tolerance,
                current_market_pressure_score=current_market_pressure_score,
                required_return_gap=required_return_gap,
                implied_required_annual_return=implied_required_annual_return,
                explicit_request=None,
                persisted_preference=None,
            )
            suggested_members = build_bucket_subset(
                bucket=bucket,
                bucket_weight=bucket_weight,
                requested_resolution=suggested_resolution,
                candidates=bucket_candidates,
                search_expansion_level=normalized_search_expansion_level,
                ranking_context=ranking_context,
            )
            suggested_explanation = build_bucket_construction_explanation(
                bucket=bucket,
                bucket_weight=bucket_weight,
                requested_resolution=suggested_resolution,
                selected_members=suggested_members,
                candidates=bucket_candidates,
                search_expansion_level=normalized_search_expansion_level,
                ranking_context=ranking_context,
            )
            bucket_suggestions[bucket] = {
                "member_product_ids": [member.candidate.product_id for member in suggested_members],
                "explanation": suggested_explanation.to_dict(),
                "diagnostic_codes": list(suggested_explanation.diagnostic_codes),
            }
        split_target_weights = split_bucket_weight(bucket_weight, len(selected_members))
        current_bucket_weight = normalized_current_weights.get(bucket)
        split_current_weights = (
            split_bucket_weight(float(current_bucket_weight), len(selected_members))
            if len(selected_members) == 1 and current_bucket_weight is not None
            else [None] * len(selected_members)
        )
        bucket_explanations[bucket] = bucket_construction_explanation
        for selected_member, member_target_weight, member_current_weight in zip(
            selected_members,
            split_target_weights,
            split_current_weights,
        ):
            items.append(
                _build_item(
                    bucket,
                    member_target_weight,
                    selected_members,
                    ranking_context=ranking_context,
                    primary_runtime_candidate=selected_member,
                    account_total_value=account_total_value,
                    current_weight=member_current_weight,
                    minimum_trade_amount=minimum_trade_amount,
                    initial_deploy_fraction=initial_deploy_fraction,
                    transaction_fee_rate=transaction_fee_rate,
                    wrapper_slippage_rate=wrapper_slippage_rate,
                )
            )

    execution_realism_summary = _build_execution_realism_summary(
        items=items,
        account_total_value=account_total_value,
        requested_total_amount=(
            None
            if account_total_value is None
            else sum(max(float(weight or 0.0), 0.0) * float(account_total_value) for weight in adjusted_targets.values())
        ),
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

    product_proxy_specs = _build_selected_plan_proxy_specs(
        items,
        proxy_result=product_proxy_result,
    )
    proxy_universe_summary = _build_proxy_universe_summary(
        normalized_targets=adjusted_targets,
        runtime_candidates=runtime_candidate_pool,
        selected_items=items,
        product_proxy_specs=product_proxy_specs,
    )
    maintenance_policy_summary = _build_maintenance_policy_summary(
        items=items,
        cash_reserve_target_amount=(
            None if execution_realism_summary is None else execution_realism_summary.cash_reserve_target_amount
        ),
        initial_deploy_fraction=initial_deploy_fraction,
    )

    return ExecutionPlan(
        plan_id=f"{source_run_id}:{source_allocation_id}",
        source_run_id=source_run_id,
        source_allocation_id=source_allocation_id,
        items=items,
        bucket_construction_explanations=bucket_explanations,
        bucket_construction_suggestions=bucket_suggestions,
        warnings=warnings,
        plan_version=max(int(plan_version), 1),
        registry_candidate_count=len(registry),
        runtime_candidate_count=len(runtime_candidate_pool),
        runtime_candidates=runtime_candidate_pool,
        product_proxy_specs=product_proxy_specs,
        proxy_universe_summary=proxy_universe_summary,
        execution_realism_summary=execution_realism_summary,
        maintenance_policy_summary=maintenance_policy_summary,
        candidate_filter_breakdown=candidate_filter_breakdown,
        valuation_audit_summary=dict(candidate_filter_breakdown.valuation_audit_summary or {}),
        policy_news_audit_summary=dict(candidate_filter_breakdown.policy_news_audit_summary or {}),
        formal_path_preflight=formal_path_preflight,
        failure_artifact=failure_artifact,
    )
