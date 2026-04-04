from __future__ import annotations

import pytest

from product_mapping import (
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    build_execution_plan,
    load_builtin_catalog,
)
from product_mapping.types import CandidateFilterBreakdown, RuntimeProductCandidate


@pytest.mark.contract
def test_builtin_catalog_covers_first_wave_buckets_with_typed_candidates():
    catalog = load_builtin_catalog()

    assert catalog
    assert all(isinstance(candidate, ProductCandidate) for candidate in catalog)
    assert {"equity_cn", "bond_cn", "gold", "cash_liquidity"}.issubset(
        {candidate.asset_bucket for candidate in catalog}
    )
    assert any(candidate.wrapper_type == "stock" for candidate in catalog)
    assert any(candidate.region != "CN" for candidate in catalog)


@pytest.mark.contract
def test_build_execution_plan_returns_typed_items_and_surfaces_alternates():
    plan = build_execution_plan(
        source_run_id="run_product_mapping_contract",
        source_allocation_id="allocation_alpha",
        bucket_targets={
            "equity_cn": 0.50,
            "bond_cn": 0.25,
            "gold": 0.15,
            "cash": 0.10,
            "satellite": 0.05,
        },
        restrictions=[],
    )

    assert isinstance(plan, ExecutionPlan)
    assert plan.status == "draft"
    assert plan.confirmation_required is True
    assert all(isinstance(item, ExecutionPlanItem) for item in plan.items)
    assert all(isinstance(candidate, RuntimeProductCandidate) for candidate in plan.runtime_candidates)
    assert isinstance(plan.candidate_filter_breakdown, CandidateFilterBreakdown)
    assert plan.registry_candidate_count >= plan.runtime_candidate_count > 0

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert isinstance(equity_item.primary_product, ProductCandidate)
    assert equity_item.primary_product_id == equity_item.primary_product.product_id
    assert equity_item.alternate_product_ids
    assert [product.product_id for product in equity_item.alternate_products] == equity_item.alternate_product_ids


@pytest.mark.contract
def test_build_execution_plan_normalizes_documented_cash_liquidity_bucket_alias():
    plan = build_execution_plan(
        source_run_id="run_cash_liquidity_alias",
        source_allocation_id="allocation_alias",
        bucket_targets={"cash / liquidity": 0.10},
        restrictions=[],
    )

    assert [item.asset_bucket for item in plan.items] == ["cash_liquidity"]
    assert plan.items[0].primary_product.asset_bucket == "cash_liquidity"
    assert all("当前没有可用产品候选" not in warning for warning in plan.warnings)


@pytest.mark.contract
def test_build_execution_plan_respects_do_not_touch_stocks_restriction():
    plan = build_execution_plan(
        source_run_id="run_no_stock",
        source_allocation_id="allocation_beta",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.35,
            "gold": 0.10,
            "cash_liquidity": 0.10,
        },
        restrictions=["不碰股票"],
    )

    assert "equity_cn" in {item.asset_bucket for item in plan.items}
    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")
    assert equity_item.primary_product.wrapper_type in {"etf", "fund"}
    assert all(product.wrapper_type != "stock" for product in [equity_item.primary_product, *equity_item.alternate_products])
    assert any("不碰股票" in warning for warning in plan.warnings)
    assert any("wrapper:stock" in reason for reason in plan.candidate_filter_breakdown.dropped_reasons)


@pytest.mark.contract
def test_build_execution_plan_respects_gold_and_cash_only_restriction():
    plan = build_execution_plan(
        source_run_id="run_gold_cash_only",
        source_allocation_id="allocation_gamma",
        bucket_targets={
            "equity_cn": 0.50,
            "bond_cn": 0.20,
            "gold": 0.20,
            "liquidity": 0.10,
        },
        restrictions=["只接受黄金和现金"],
    )

    assert {item.asset_bucket for item in plan.items} == {"gold", "cash_liquidity"}
    assert any("只接受黄金和现金" in warning for warning in plan.warnings)


@pytest.mark.contract
def test_build_execution_plan_filters_qdii_and_overseas_candidates_from_runtime_pool():
    unrestricted = build_execution_plan(
        source_run_id="run_qdii_allowed",
        source_allocation_id="allocation_delta",
        bucket_targets={"equity_cn": 0.65, "satellite": 0.20, "bond_cn": 0.15},
        restrictions=[],
    )
    restricted = build_execution_plan(
        source_run_id="run_qdii_forbidden",
        source_allocation_id="allocation_delta",
        bucket_targets={"equity_cn": 0.65, "satellite": 0.20, "bond_cn": 0.15},
        restrictions=["不买QDII"],
    )

    assert any(candidate.candidate.region != "CN" for candidate in unrestricted.runtime_candidates)
    assert all(candidate.candidate.region == "CN" for candidate in restricted.runtime_candidates)
    assert restricted.runtime_candidate_count < unrestricted.runtime_candidate_count
    assert any("region:non_cn" in reason or "tag:qdii" in reason for reason in restricted.candidate_filter_breakdown.dropped_reasons)


@pytest.mark.contract
def test_build_execution_plan_accepts_explicit_runtime_candidate_pool():
    registry = load_builtin_catalog()
    runtime_pool = [
        candidate
        for candidate in registry
        if candidate.product_id in {"cn_equity_dividend_etf", "cn_bond_gov_etf", "cn_gold_etf"}
    ]

    plan = build_execution_plan(
        source_run_id="run_explicit_runtime_pool",
        source_allocation_id="allocation_explicit_runtime_pool",
        bucket_targets={"equity_cn": 0.50, "bond_cn": 0.30, "gold": 0.20},
        restrictions=[],
        catalog=registry,
        runtime_candidates=runtime_pool,
    )

    assert plan.registry_candidate_count == len(registry)
    assert plan.runtime_candidate_count == 3
    assert {item.primary_product_id for item in plan.items} == {
        "cn_equity_dividend_etf",
        "cn_bond_gov_etf",
        "cn_gold_etf",
    }


@pytest.mark.contract
def test_build_execution_plan_filters_theme_without_collapsing_satellite_bucket():
    unrestricted = build_execution_plan(
        source_run_id="run_theme_allowed",
        source_allocation_id="allocation_theme_allowed",
        bucket_targets={"satellite": 0.20},
        restrictions=[],
    )
    restricted = build_execution_plan(
        source_run_id="run_theme_forbidden",
        source_allocation_id="allocation_theme_forbidden",
        bucket_targets={"satellite": 0.20},
        restrictions=["不碰科技"],
    )

    unrestricted_satellite = next(item for item in unrestricted.items if item.asset_bucket == "satellite")
    restricted_satellite = next(item for item in restricted.items if item.asset_bucket == "satellite")

    assert unrestricted_satellite.primary_product_id != restricted_satellite.primary_product_id
    assert "technology" not in restricted_satellite.primary_product.tags
    assert restricted.runtime_candidate_count < unrestricted.runtime_candidate_count
    assert any("theme:technology" in reason for reason in restricted.candidate_filter_breakdown.dropped_reasons)


@pytest.mark.contract
def test_build_execution_plan_does_not_claim_low_valuation_filter_without_observed_source():
    plan = build_execution_plan(
        source_run_id="run_missing_valuation_source",
        source_allocation_id="allocation_missing_valuation_source",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.40},
        restrictions=[],
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result={
            "source_status": "missing",
            "source_name": "akshare_dynamic_valuation",
            "source_ref": "akshare:valuation:missing",
            "as_of": "2026-04-04",
            "products": {},
        },
    )

    assert "equity_cn" not in {item.asset_bucket for item in plan.items}
    assert "bond_cn" in {item.asset_bucket for item in plan.items}
    assert any(
        "valuation:missing_observed_source" in reason
        for reason in plan.candidate_filter_breakdown.dropped_reasons
    )
    assert plan.valuation_audit_summary["source_status"] == "missing"
    assert plan.valuation_audit_summary["applicable_candidate_count"] >= 1
    assert plan.valuation_audit_summary["non_applicable_candidate_count"] >= 1


@pytest.mark.contract
def test_build_execution_plan_filters_observed_valuation_by_pe_and_percentile_rules():
    plan = build_execution_plan(
        source_run_id="run_observed_valuation_filter",
        source_allocation_id="allocation_observed_valuation_filter",
        bucket_targets={"equity_cn": 1.0},
        restrictions=[],
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result={
            "source_status": "observed",
            "source_name": "akshare_dynamic_valuation",
            "source_ref": "akshare:valuation:equity_cn",
            "as_of": "2026-04-04",
            "products": {
                "510880": {"status": "observed", "pe_ratio": 18.0, "percentile": 0.22},
                "510300": {"status": "observed", "pe_ratio": 45.0, "percentile": 0.18},
                "012390": {"status": "observed", "pe_ratio": 20.0, "percentile": 0.42},
            },
        },
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert equity_item.primary_product_id == "cn_equity_dividend_etf"
    assert equity_item.valuation_audit is not None
    assert equity_item.valuation_audit.status == "observed"
    assert equity_item.valuation_audit.passed_filters is True
    assert any("valuation:pe_above_40" in reason for reason in plan.candidate_filter_breakdown.dropped_reasons)
    assert any(
        "valuation:percentile_above_0.30" in reason
        for reason in plan.candidate_filter_breakdown.dropped_reasons
    )
    assert plan.valuation_audit_summary["passed_candidate_count"] == 1


@pytest.mark.contract
def test_build_execution_plan_marks_non_applicable_products_with_explicit_valuation_reason():
    plan = build_execution_plan(
        source_run_id="run_non_applicable_valuation",
        source_allocation_id="allocation_non_applicable_valuation",
        bucket_targets={"gold": 0.50, "cash_liquidity": 0.50},
        restrictions=[],
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result={
            "source_status": "observed",
            "source_name": "akshare_dynamic_valuation",
            "source_ref": "akshare:valuation:partial",
            "as_of": "2026-04-04",
            "products": {},
        },
    )

    gold_item = next(item for item in plan.items if item.asset_bucket == "gold")
    cash_item = next(item for item in plan.items if item.asset_bucket == "cash_liquidity")

    assert gold_item.valuation_audit is not None
    assert gold_item.valuation_audit.reason == "valuation:not_applicable"
    assert cash_item.valuation_audit is not None
    assert cash_item.valuation_audit.reason == "valuation:not_applicable"
    assert plan.valuation_audit_summary["non_applicable_candidate_count"] >= 2


@pytest.mark.contract
def test_build_execution_plan_uses_dynamic_policy_news_score_for_satellite_ranking():
    plan = build_execution_plan(
        source_run_id="run_policy_news_satellite",
        source_allocation_id="allocation_policy_news_satellite",
        bucket_targets={"satellite": 0.20, "equity_cn": 0.40, "bond_cn": 0.40},
        restrictions=[],
        policy_news_signals=[
            {
                "signal_id": "signal-energy-positive",
                "as_of": "2026-04-04T15:00:00Z",
                "published_at": "2026-04-03T12:00:00Z",
                "source_type": "news",
                "source_name": "newswire",
                "source_refs": ["https://example.com/news/energy"],
                "direction": "bullish",
                "strength": 0.9,
                "confidence": 0.85,
                "decay_half_life_days": 7.0,
                "target_buckets": ["satellite"],
                "target_tags": ["cyclical"],
            }
        ],
    )

    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert satellite_item.primary_product_id == "cn_satellite_energy_etf"
    assert satellite_item.policy_news_audit is not None
    assert satellite_item.policy_news_audit.realtime_eligible is True
    assert satellite_item.policy_news_audit.score > 0.0
    assert plan.policy_news_audit_summary["source_status"] == "observed"
    assert plan.policy_news_audit_summary["realtime_eligible"] is True


@pytest.mark.contract
def test_build_execution_plan_does_not_claim_realtime_policy_news_without_real_materials():
    plan = build_execution_plan(
        source_run_id="run_policy_news_missing_materials",
        source_allocation_id="allocation_policy_news_missing_materials",
        bucket_targets={"satellite": 0.20},
        restrictions=[],
        policy_news_signals=[
            {
                "signal_id": "signal-missing-materials",
                "as_of": "2026-04-04T15:00:00Z",
                "source_type": "analysis",
                "direction": "bullish",
                "strength": 0.9,
                "confidence": 0.85,
                "target_buckets": ["satellite"],
                "target_tags": ["cyclical"],
            }
        ],
    )

    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert satellite_item.primary_product_id == "cn_satellite_chip_etf"
    assert satellite_item.policy_news_audit is not None
    assert satellite_item.policy_news_audit.realtime_eligible is False
    assert plan.policy_news_audit_summary["source_status"] == "missing_materials"
    assert plan.policy_news_audit_summary["realtime_eligible"] is False


@pytest.mark.contract
def test_build_execution_plan_limits_policy_news_to_mild_core_influence():
    plan = build_execution_plan(
        source_run_id="run_policy_news_core_mild",
        source_allocation_id="allocation_policy_news_core_mild",
        bucket_targets={"equity_cn": 1.0},
        restrictions=[],
        policy_news_signals=[
            {
                "signal_id": "signal-low-vol-positive",
                "as_of": "2026-04-04T15:00:00Z",
                "published_at": "2026-04-04T12:00:00Z",
                "source_type": "policy",
                "source_name": "policy_feed",
                "source_refs": ["https://example.com/policy/low-vol"],
                "direction": "bullish",
                "strength": 1.0,
                "confidence": 1.0,
                "decay_half_life_days": 5.0,
                "target_products": ["cn_equity_low_vol_fund"],
            }
        ],
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert equity_item.primary_product_id == "cn_equity_csi300_etf"
    assert equity_item.policy_news_audit is not None
    assert equity_item.policy_news_audit.influence_scope == "core_mild"
    assert plan.policy_news_audit_summary["core_influence_capped"] is True


@pytest.mark.contract
def test_build_execution_plan_summary_surfaces_proxy_universe_disclosure_and_specs():
    plan = build_execution_plan(
        source_run_id="run_proxy_universe_summary",
        source_allocation_id="allocation_proxy_universe",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.25,
            "gold": 0.10,
            "cash_liquidity": 0.10,
            "satellite": 0.10,
        },
        restrictions=[],
    )

    summary = plan.summary()

    assert summary["proxy_universe_summary"]["solving_mode"] == "proxy_universe"
    assert "equity_cn" in summary["proxy_universe_summary"]["covered_asset_buckets"]
    assert "bond_cn" in summary["proxy_universe_summary"]["covered_asset_buckets"]
    assert "gold" in summary["proxy_universe_summary"]["covered_asset_buckets"]
    assert summary["proxy_universe_summary"]["product_proxy_count"] >= plan.runtime_candidate_count
    assert "代理宇宙求解" in summary["proxy_universe_summary"]["disclosure"]
    assert summary["product_proxy_specs"]
    assert any(spec["product_id"] == "qdii_hk_tech_fund" for spec in summary["product_proxy_specs"])
    assert all(spec["data_status"] == "manual_annotation" for spec in summary["product_proxy_specs"])


@pytest.mark.contract
def test_build_execution_plan_surfaces_execution_realism_amounts_and_cash_reserve_conflict():
    plan = build_execution_plan(
        source_run_id="run_execution_realism_conflict",
        source_allocation_id="allocation_execution_realism_conflict",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.35,
            "gold": 0.15,
            "satellite": 0.05,
        },
        restrictions=[],
        account_total_value=35_000.0,
        current_weights={
            "cash_liquidity": 0.7143,
            "gold": 0.2857,
        },
        available_cash=25_000.0,
        liquidity_reserve_min=0.10,
        minimum_trade_amount=500.0,
        transaction_fee_rate={
            "equity_cn": 0.003,
            "bond_cn": 0.001,
            "gold": 0.001,
            "satellite": 0.004,
        },
    )

    gold_item = next(item for item in plan.items if item.asset_bucket == "gold")

    assert gold_item.current_amount == pytest.approx(9_999.5, abs=1.0)
    assert gold_item.target_amount == pytest.approx(5_250.0, abs=1e-6)
    assert gold_item.trade_direction == "sell"
    assert gold_item.trade_amount == pytest.approx(4_749.5, abs=1.0)
    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.executable is False
    assert plan.execution_realism_summary.cash_reserve_target_amount == pytest.approx(3_500.0, abs=1e-6)
    assert plan.execution_realism_summary.estimated_total_fee is not None
    assert plan.execution_realism_summary.estimated_total_fee > 0.0
    assert "cash_reserve_conflict" in plan.execution_realism_summary.reasons


@pytest.mark.contract
def test_build_execution_plan_flags_tiny_trade_buckets_below_minimum_amount():
    plan = build_execution_plan(
        source_run_id="run_execution_realism_tiny_trade",
        source_allocation_id="allocation_execution_realism_tiny_trade",
        bucket_targets={
            "cash_liquidity": 0.99,
            "satellite": 0.01,
        },
        restrictions=[],
        account_total_value=35_000.0,
        current_weights={"cash_liquidity": 1.0},
        available_cash=35_000.0,
        liquidity_reserve_min=0.05,
        minimum_trade_amount=500.0,
    )

    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert satellite_item.trade_amount == pytest.approx(350.0, abs=1e-6)
    assert satellite_item.violates_minimum_trade is True
    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.executable is False
    assert plan.execution_realism_summary.tiny_trade_buckets == ["cash_liquidity", "satellite"]
