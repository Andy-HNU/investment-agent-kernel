from __future__ import annotations

import pytest

from product_mapping import (
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    build_candidate_product_context,
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
def test_build_candidate_product_context_preserves_history_window_days():
    context = build_candidate_product_context(
        source_allocation_id="allocation_history_window",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.25, "gold": 0.15},
        restrictions=[],
        historical_dataset={
            "audit_window": {
                "start_date": "2024-01-02",
                "end_date": "2026-04-03",
                "trading_days": 492,
                "observed_days": 480,
                "inferred_days": 12,
            }
        },
    )

    assert context["product_history_profiles"]
    assert all(item["observed_history_days"] == 492 for item in context["product_history_profiles"])
    assert all(item["inferred_history_days"] == 12 for item in context["product_history_profiles"])


@pytest.mark.contract
def test_build_candidate_product_context_emits_product_simulation_input_from_selected_products(monkeypatch):
    runtime_pool = [
        ProductCandidate(
            product_id="ts_equity_core",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="510300.SH",
            tags=["core"],
        ),
        ProductCandidate(
            product_id="ts_bond_core",
            product_name="国债ETF",
            asset_bucket="bond_cn",
            product_family="defense",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="511010.SH",
            tags=["bond", "defense"],
        ),
        ProductCandidate(
            product_id="ts_gold_core",
            product_name="黄金ETF",
            asset_bucket="gold",
            product_family="defense",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="518880.SH",
            tags=["gold"],
        ),
    ]

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin):  # type: ignore[no-untyped-def]
        rows = {
            "510300.SH": [
                {"date": "2026-04-01", "close": 1.0},
                {"date": "2026-04-02", "close": 1.05},
                {"date": "2026-04-03", "close": 1.07},
            ],
            "511010.SH": [
                {"date": "2026-04-01", "close": 1.0},
                {"date": "2026-04-02", "close": 1.01},
                {"date": "2026-04-03", "close": 1.015},
            ],
            "518880.SH": [
                {"date": "2026-04-01", "close": 1.0},
                {"date": "2026-04-02", "close": 0.99},
                {"date": "2026-04-03", "close": 1.02},
            ],
        }[spec.symbol]
        return rows, pin

    monkeypatch.setattr("product_mapping.engine.fetch_timeseries", _fake_fetch_timeseries)

    context = build_candidate_product_context(
        source_allocation_id="allocation_product_simulation",
        bucket_targets={"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.15},
        restrictions=[],
        runtime_candidates=runtime_pool,
        historical_dataset={
            "source_name": "tinyshare",
            "audit_window": {
                "start_date": "2026-04-01",
                "end_date": "2026-04-03",
                "trading_days": 3,
                "observed_days": 3,
                "inferred_days": 0,
            },
        },
    )

    assert context["product_probability_method"] == "product_independent_path"
    simulation_input = context["product_simulation_input"]
    assert simulation_input is not None


@pytest.mark.contract
def test_build_execution_plan_surfaces_proxy_valuation_modes_and_signal_triggers():
    runtime_pool = [
        ProductCandidate(
            product_id="ts_equity_core_etf",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="510300.SH",
            tags=["core", "broad_market"],
        ),
        ProductCandidate(
            product_id="ts_satellite_energy_etf",
            product_name="能源ETF",
            asset_bucket="satellite",
            product_family="satellite",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="159930.SZ",
            tags=["satellite", "cyclical", "energy"],
            risk_labels=["权益波动"],
        ),
        ProductCandidate(
            product_id="ts_bond_core_etf",
            product_name="国债ETF",
            asset_bucket="bond_cn",
            product_family="defense",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="511010.SH",
            tags=["bond", "defense"],
        ),
    ]
    product_universe_result = {
        "source_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
        "as_of": "2026-04-05",
        "products": {
            candidate.product_id: {
                "status": "observed",
                "tradable": True,
                "source_name": "tinyshare_runtime_catalog",
                "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
                "as_of": "2026-04-05",
                "data_status": "observed",
            }
            for candidate in runtime_pool
        },
    }
    valuation_result = {
        "source_status": "observed",
        "source_name": "tinyshare_runtime_valuation",
        "source_ref": "tinyshare://daily_basic?trade_date=20260403",
        "as_of": "2026-04-05",
        "bucket_proxies": {
            "equity_cn": {
                "status": "observed",
                "pe_ratio": 18.0,
                "pb_ratio": 2.1,
                "percentile": 0.22,
                "valuation_mode": "index_proxy",
                "data_status": "computed_from_observed",
                "audit_window": {
                    "start_date": "2025-04-03",
                    "end_date": "2026-04-03",
                    "trading_days": 243,
                    "observed_days": 243,
                    "inferred_days": 0,
                },
                "source_ref": "tinyshare://valuation/equity_cn",
                "as_of": "2026-04-05",
            },
            "satellite": {
                "status": "observed",
                "pe_ratio": 22.0,
                "pb_ratio": 2.6,
                "percentile": 0.18,
                "valuation_mode": "holdings_proxy",
                "data_status": "computed_from_observed",
                "audit_window": {
                    "start_date": "2025-04-03",
                    "end_date": "2026-04-03",
                    "trading_days": 243,
                    "observed_days": 243,
                    "inferred_days": 0,
                },
                "source_ref": "tinyshare://valuation/satellite",
                "as_of": "2026-04-05",
            },
        },
        "products": {},
    }
    policy_news_signals = [
        {
            "signal_id": "sig_energy_001",
            "as_of": "2026-04-05T12:00:00Z",
            "source_type": "policy",
            "source_refs": ["claw://policy/energy"],
            "source_name": "claw_skill",
            "published_at": "2026-04-04T08:00:00Z",
            "direction": "positive",
            "strength": 0.8,
            "confidence": 0.9,
            "target_buckets": ["satellite"],
            "target_tags": ["energy"],
        }
    ]

    plan = build_execution_plan(
        source_run_id="run_proxy_valuation_and_signals",
        source_allocation_id="allocation_proxy_valuation_and_signals",
        bucket_targets={"equity_cn": 0.50, "satellite": 0.15, "bond_cn": 0.35},
        restrictions=[],
        catalog=runtime_pool,
        runtime_candidates=runtime_pool,
        product_universe_inputs={"requested": True, "require_observed_source": True},
        product_universe_result=product_universe_result,
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result=valuation_result,
        policy_news_signals=policy_news_signals,
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")
    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert equity_item.valuation_audit is not None
    assert equity_item.valuation_audit.valuation_mode == "index_proxy"
    assert equity_item.valuation_audit.passed_filters is True
    assert satellite_item.valuation_audit is not None
    assert satellite_item.valuation_audit.valuation_mode == "holdings_proxy"
    assert satellite_item.policy_news_audit is not None
    assert satellite_item.policy_news_audit.matched_signal_ids == ["sig_energy_001"]
    assert plan.maintenance_policy_summary["triggered_signal_ids"] == ["sig_energy_001"]
    assert plan.maintenance_policy_summary["signal_data_status"] == ["computed_from_observed", "observed"]
    assert plan.maintenance_policy_summary["signal_confidence_data_status"] == ["inferred", "observed"]


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
def test_build_execution_plan_accepts_canonical_theme_token_without_collapsing_satellite_bucket():
    restricted = build_execution_plan(
        source_run_id="run_theme_forbidden_canonical",
        source_allocation_id="allocation_theme_forbidden_canonical",
        bucket_targets={"satellite": 0.20},
        restrictions=["forbidden_theme:technology"],
    )

    satellite_item = next(item for item in restricted.items if item.asset_bucket == "satellite")

    assert "technology" not in satellite_item.primary_product.tags
    assert restricted.runtime_candidate_count > 0
    assert any("theme:technology" in reason for reason in restricted.candidate_filter_breakdown.dropped_reasons)


@pytest.mark.contract
def test_build_execution_plan_filters_high_risk_products_when_requested():
    restricted = build_execution_plan(
        source_run_id="run_high_risk_forbidden",
        source_allocation_id="allocation_high_risk_forbidden",
        bucket_targets={"equity_cn": 0.50, "bond_cn": 0.30, "gold": 0.20, "satellite": 0.10},
        restrictions=["no_high_risk_products"],
    )

    assert any("risk_label:high_risk_product" in reason for reason in restricted.candidate_filter_breakdown.dropped_reasons)
    assert all(
        "主题波动" not in item.primary_product.risk_labels and item.primary_product.wrapper_type != "stock"
        for item in restricted.items
    )


@pytest.mark.contract
def test_build_execution_plan_filters_runtime_pool_by_observed_product_universe_result():
    unrestricted = build_execution_plan(
        source_run_id="run_universe_unrestricted",
        source_allocation_id="allocation_universe_unrestricted",
        bucket_targets={"equity_cn": 0.60, "satellite": 0.20, "bond_cn": 0.20},
        restrictions=[],
    )
    restricted = build_execution_plan(
        source_run_id="run_universe_observed_filter",
        source_allocation_id="allocation_universe_observed_filter",
        bucket_targets={"equity_cn": 0.60, "satellite": 0.20, "bond_cn": 0.20},
        restrictions=[],
        product_universe_inputs={"requested": True, "require_observed_source": True},
        product_universe_result={
            "source_status": "observed",
            "source_name": "akshare_product_universe",
            "source_ref": "akshare:product_universe:cn",
            "as_of": "2026-04-04",
            "products": {
                "510880": {"status": "observed", "tradable": True},
                "510300": {"status": "observed", "tradable": True},
                "012390": {"status": "observed", "tradable": False},
                "511010": {"status": "observed", "tradable": True},
                "000402": {"status": "observed", "tradable": False},
                "159995": {"status": "observed", "tradable": False},
                "562500": {"status": "observed", "tradable": False},
                "159930": {"status": "observed", "tradable": True},
            },
        },
    )

    assert restricted.runtime_candidate_count < unrestricted.runtime_candidate_count
    assert any(
        "product_universe:not_tradable" in reason
        for reason in restricted.candidate_filter_breakdown.dropped_reasons
    )
    assert restricted.candidate_filter_breakdown.product_universe_audit_summary["source_status"] == "observed"
    assert restricted.candidate_filter_breakdown.product_universe_audit_summary["dropped_candidate_count"] >= 1
    assert restricted.summary()["product_universe_audit_summary"]["source_name"] == "akshare_product_universe"


@pytest.mark.contract
def test_build_execution_plan_uses_observed_product_proxy_specs_when_available():
    plan = build_execution_plan(
        source_run_id="run_observed_proxy_specs",
        source_allocation_id="allocation_observed_proxy_specs",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.25, "gold": 0.15},
        restrictions=[],
        product_proxy_result={
            "products": {
                "cn_equity_dividend_etf": {
                    "status": "observed",
                    "proxy_kind": "observed_total_return_proxy",
                    "proxy_ref": "akshare:fund:510880",
                    "confidence": 0.91,
                    "confidence_data_status": "computed_from_observed",
                    "confidence_disclosure": "proxy confidence is backed by observed coverage metadata.",
                    "source_ref": "akshare:proxy:510880",
                    "data_status": "observed",
                    "as_of": "2026-04-04",
                }
            }
        },
    )

    dividend_spec = next(spec for spec in plan.product_proxy_specs if spec.product_id == "cn_equity_dividend_etf")
    assert dividend_spec.proxy_kind == "observed_total_return_proxy"
    assert dividend_spec.proxy_ref == "akshare:fund:510880"
    assert dividend_spec.data_status == "observed"
    assert dividend_spec.confidence_data_status == "computed_from_observed"
    assert dividend_spec.as_of == "2026-04-04"
    assert plan.summary()["proxy_universe_summary"]["data_status"] in {"observed", "computed_from_observed"}


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
def test_build_execution_plan_marks_unrequested_dynamic_sources_as_not_requested():
    plan = build_execution_plan(
        source_run_id="run_not_requested_sources",
        source_allocation_id="allocation_not_requested_sources",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.40},
        restrictions=[],
    )

    assert plan.candidate_filter_breakdown.product_universe_audit_summary["requested"] is False
    assert plan.candidate_filter_breakdown.product_universe_audit_summary["source_status"] == "not_requested"
    assert plan.valuation_audit_summary["requested"] is False
    assert plan.valuation_audit_summary["source_status"] == "not_requested"


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
                "510880": {
                    "status": "observed",
                    "pe_ratio": 18.0,
                    "pb_ratio": 2.1,
                    "percentile": 0.22,
                    "data_status": "observed",
                    "audit_window": {
                        "start_date": "2016-04-04",
                        "end_date": "2026-04-04",
                        "trading_days": 2420,
                        "observed_days": 2420,
                        "inferred_days": 0,
                    },
                },
                "510300": {"status": "observed", "pe_ratio": 45.0, "percentile": 0.18},
                "012390": {"status": "observed", "pe_ratio": 20.0, "percentile": 0.42},
            },
        },
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert equity_item.primary_product_id == "cn_equity_dividend_etf"
    assert equity_item.valuation_audit is not None
    assert equity_item.valuation_audit.status == "observed"
    assert equity_item.valuation_audit.pb_ratio == 2.1
    assert equity_item.valuation_audit.data_status == "observed"
    assert equity_item.valuation_audit.audit_window is not None
    assert equity_item.valuation_audit.audit_window.trading_days == 2420
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
def test_build_execution_plan_uses_bucket_proxy_valuation_for_equity_fund_wrappers():
    plan = build_execution_plan(
        source_run_id="run_bucket_proxy_valuation",
        source_allocation_id="allocation_bucket_proxy_valuation",
        bucket_targets={"equity_cn": 1.0},
        restrictions=[],
        catalog=[
            ProductCandidate(
                product_id="eq_fund",
                product_name="宽基指数基金",
                asset_bucket="equity_cn",
                product_family="core",
                wrapper_type="fund",
                provider_source="unit_test",
                provider_symbol="EQFUND",
                tags=["equity", "core"],
            )
        ],
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result={
            "source_status": "observed",
            "source_name": "tinyshare_runtime_valuation",
            "source_ref": "tinyshare://daily_basic?trade_date=20260403",
            "as_of": "2026-04-05",
            "products": {},
            "bucket_proxies": {
                "equity_cn": {
                    "status": "observed",
                    "pe_ratio": 18.0,
                    "pb_ratio": 2.1,
                    "percentile": 0.22,
                    "data_status": "computed_from_observed",
                    "audit_window": {
                        "start_date": "2026-04-03",
                        "end_date": "2026-04-03",
                        "trading_days": 1,
                        "observed_days": 1,
                        "inferred_days": 0,
                    },
                    "source_ref": "tinyshare://daily_basic?trade_date=20260403&subject=equity_cn_proxy",
                    "as_of": "2026-04-05",
                }
            },
        },
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert equity_item.valuation_audit is not None
    assert equity_item.valuation_audit.status == "observed"
    assert equity_item.valuation_audit.pe_ratio == pytest.approx(18.0, abs=1e-6)
    assert equity_item.valuation_audit.passed_filters is True
    assert equity_item.valuation_audit.audit_window is not None
    assert equity_item.valuation_audit.audit_window.trading_days == 1
    assert plan.valuation_audit_summary["applicable_candidate_count"] == 1
    assert plan.valuation_audit_summary["passed_candidate_count"] == 1
    assert equity_item.valuation_audit.valuation_mode == "index_proxy"


@pytest.mark.contract
def test_build_execution_plan_uses_theme_proxy_valuation_for_satellite_wrappers():
    plan = build_execution_plan(
        source_run_id="run_theme_proxy_valuation",
        source_allocation_id="allocation_theme_proxy_valuation",
        bucket_targets={"satellite": 1.0},
        restrictions=[],
        catalog=[
            ProductCandidate(
                product_id="sat_energy_etf",
                product_name="能源ETF",
                asset_bucket="satellite",
                product_family="satellite",
                wrapper_type="etf",
                provider_source="unit_test",
                provider_symbol="159930.SZ",
                tags=["satellite", "cyclical", "energy"],
            )
        ],
        valuation_inputs={"requested": True, "require_observed_source": True},
        valuation_result={
            "source_status": "observed",
            "source_name": "tinyshare_runtime_valuation",
            "source_ref": "tinyshare://daily_basic?trade_date=20260403",
            "as_of": "2026-04-05",
            "products": {},
            "theme_proxies": {
                "cyclical": {
                    "status": "observed",
                    "pe_ratio": 16.0,
                    "pb_ratio": 1.8,
                    "percentile": 0.18,
                    "data_status": "computed_from_observed",
                    "audit_window": {
                        "start_date": "2026-04-03",
                        "end_date": "2026-04-03",
                        "trading_days": 1,
                        "observed_days": 1,
                        "inferred_days": 0,
                    },
                    "source_ref": "tinyshare://daily_basic?trade_date=20260403&theme=cyclical",
                    "as_of": "2026-04-05",
                }
            },
        },
    )

    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert satellite_item.valuation_audit is not None
    assert satellite_item.valuation_audit.status == "observed"
    assert satellite_item.valuation_audit.pe_ratio == pytest.approx(16.0, abs=1e-6)
    assert satellite_item.valuation_audit.passed_filters is True
    assert satellite_item.valuation_audit.valuation_mode == "holdings_proxy"
    assert satellite_item.valuation_audit.source_ref == "tinyshare://daily_basic?trade_date=20260403&theme=cyclical"
    assert plan.valuation_audit_summary["passed_candidate_count"] == 1


@pytest.mark.contract
def test_build_execution_plan_uses_dynamic_policy_news_score_for_satellite_ranking():
    plan = build_execution_plan(
        source_run_id="run_policy_news_satellite",
        source_allocation_id="allocation_policy_news_satellite",
        bucket_targets={"satellite": 0.20, "equity_cn": 0.40, "bond_cn": 0.40},
        restrictions=["forbidden_theme:technology"],
        policy_news_signals=[
            {
                "signal_id": "signal-tech-positive",
                "as_of": "2026-04-04T15:00:00Z",
                "published_at": "2026-03-26T12:00:00Z",
                "source_type": "news",
                "source_name": "newswire",
                "source_refs": ["https://example.com/news/tech"],
                "direction": "bullish",
                "strength": 0.9,
                "confidence": 0.85,
                "decay_half_life_days": 7.0,
                "target_buckets": ["satellite"],
                "target_tags": ["technology"],
            },
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
    assert satellite_item.policy_news_audit.data_status == "computed_from_observed"
    assert satellite_item.policy_news_audit.confidence_data_status == "inferred"
    assert satellite_item.policy_news_audit.recency_days == pytest.approx(1.125, abs=1e-6)
    assert satellite_item.policy_news_audit.decay_weight == pytest.approx(0.5 ** (1.125 / 7.0), abs=1e-6)
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
    assert satellite_item.policy_news_audit.data_status == "manual_annotation"
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
        bucket_targets={"equity_cn": 1.0},
        restrictions=[],
    )

    summary = plan.summary()
    selected_product_ids = {
        product.product_id
        for item in plan.items
        for product in [item.primary_product, *item.alternate_products]
    }
    summary_proxy_ids = {spec["product_id"] for spec in summary["product_proxy_specs"]}

    assert summary["proxy_universe_summary"]["solving_mode"] == "proxy_universe"
    assert summary["proxy_universe_summary"]["proxy_scope"] == "selected_plan_items"
    assert summary["proxy_universe_summary"]["covered_asset_buckets"] == ["equity_cn"]
    assert summary["proxy_universe_summary"]["product_proxy_count"] == len(summary["product_proxy_specs"])
    assert summary["proxy_universe_summary"]["runtime_candidate_proxy_count"] == plan.runtime_candidate_count
    assert summary["proxy_universe_summary"]["data_status"] == "manual_annotation"
    assert "代理宇宙求解" in summary["proxy_universe_summary"]["disclosure"]
    assert summary["product_proxy_specs"]
    assert summary_proxy_ids == selected_product_ids
    assert all(spec["data_status"] == "manual_annotation" for spec in summary["product_proxy_specs"])
    assert all(spec["confidence_data_status"] == "manual_annotation" for spec in summary["product_proxy_specs"])
    assert all("heuristic" in spec["confidence_disclosure"] for spec in summary["product_proxy_specs"])


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
    cash_item = next(item for item in plan.items if item.asset_bucket == "cash_liquidity")

    assert gold_item.current_amount == pytest.approx(9_999.5, abs=1.0)
    assert gold_item.target_amount == pytest.approx(4_725.0, abs=1e-6)
    assert gold_item.trade_direction == "sell"
    assert gold_item.trade_amount == pytest.approx(5_274.5, abs=1.0)
    assert cash_item.target_amount == pytest.approx(3_500.0, abs=1e-6)
    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.executable is True
    assert plan.execution_realism_summary.cash_reserve_target_amount == pytest.approx(3_500.0, abs=1e-6)
    assert plan.execution_realism_summary.cash_target_amount == pytest.approx(3_500.0, abs=1e-6)
    assert plan.execution_realism_summary.amount_closure_delta == pytest.approx(0.0, abs=1e-6)
    assert plan.execution_realism_summary.estimated_total_fee is not None
    assert plan.execution_realism_summary.estimated_total_fee > 0.0
    assert plan.execution_realism_summary.reasons == []
    assert any("现金/流动性底仓" in warning for warning in plan.warnings)

@pytest.mark.contract
def test_build_execution_plan_treats_unallocated_residual_as_cash_for_closure_checks():
    plan = build_execution_plan(
        source_run_id="run_execution_realism_implicit_cash",
        source_allocation_id="allocation_execution_realism_implicit_cash",
        bucket_targets={
            "equity_cn": 0.4864,
            "bond_cn": 0.3182,
            "gold": 0.15,
        },
        restrictions=[],
        account_total_value=18_000.0,
        current_weights={
            "cash_liquidity": 12_000.0 / 18_000.0,
            "gold": 6_000.0 / 18_000.0,
        },
        available_cash=12_000.0,
        liquidity_reserve_min=0.10,
        minimum_trade_amount=500.0,
        transaction_fee_rate={
            "equity_cn": 0.003,
            "bond_cn": 0.001,
            "gold": 0.001,
        },
    )

    cash_item = next(item for item in plan.items if item.asset_bucket == "cash_liquidity")

    assert plan.execution_realism_summary is not None
    assert cash_item.target_amount == pytest.approx(1_800.0, abs=1e-6)
    assert plan.execution_realism_summary.cash_target_amount == pytest.approx(1_800.0, abs=1e-6)
    assert plan.execution_realism_summary.amount_closure_delta == pytest.approx(0.0, abs=1e-6)
    assert plan.execution_realism_summary.executable is True
    assert "account_amount_not_closed" not in plan.execution_realism_summary.reasons
    assert "cash_reserve_conflict" not in plan.execution_realism_summary.reasons


@pytest.mark.contract
def test_build_execution_plan_parks_missing_bucket_weight_into_cash_liquidity_bucket():
    plan = build_execution_plan(
        source_run_id="run_execution_realism_missing_bucket_parked",
        source_allocation_id="allocation_execution_realism_missing_bucket_parked",
        bucket_targets={
            "equity_cn": 0.4864,
            "bond_cn": 0.3182,
            "gold": 0.15,
            "satellite": 0.0454,
        },
        restrictions=[],
        catalog=[
            ProductCandidate(
                product_id="eq1",
                product_name="Equity ETF",
                asset_bucket="equity_cn",
                product_family="core",
                wrapper_type="etf",
                provider_source="unit_test",
                provider_symbol="EQ1",
                tags=["equity"],
            ),
            ProductCandidate(
                product_id="bond1",
                product_name="Bond ETF",
                asset_bucket="bond_cn",
                product_family="defense",
                wrapper_type="etf",
                provider_source="unit_test",
                provider_symbol="BOND1",
                tags=["bond"],
            ),
            ProductCandidate(
                product_id="gold1",
                product_name="Gold ETF",
                asset_bucket="gold",
                product_family="defense",
                wrapper_type="etf",
                provider_source="unit_test",
                provider_symbol="GOLD1",
                tags=["gold"],
            ),
            ProductCandidate(
                product_id="cash1",
                product_name="Money Fund",
                asset_bucket="cash_liquidity",
                product_family="cash",
                wrapper_type="cash_mgmt",
                provider_source="unit_test",
                provider_symbol="CASH1",
                tags=["cash", "liquidity"],
            ),
        ],
        account_total_value=18_000.0,
        current_weights={
            "cash_liquidity": 12_000.0 / 18_000.0,
            "gold": 6_000.0 / 18_000.0,
        },
        available_cash=12_000.0,
        liquidity_reserve_min=0.10,
        minimum_trade_amount=500.0,
        transaction_fee_rate={
            "equity_cn": 0.003,
            "bond_cn": 0.001,
            "gold": 0.001,
            "cash_liquidity": 0.0,
        },
    )

    cash_item = next(item for item in plan.items if item.asset_bucket == "cash_liquidity")

    assert cash_item.target_amount == pytest.approx(1_800.0, abs=1e-6)
    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.cash_target_amount == pytest.approx(1_800.0, abs=1e-6)
    assert plan.execution_realism_summary.amount_closure_delta == pytest.approx(0.0, abs=1e-6)
    assert "account_amount_not_closed" not in plan.execution_realism_summary.reasons
    assert any("satellite" in warning and "现金/流动性桶" in warning for warning in plan.warnings)


@pytest.mark.contract
def test_build_execution_plan_does_not_treat_missing_requested_bucket_as_implicit_cash():
    catalog = [
        ProductCandidate(
            product_id="eq1",
            product_name="Equity ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="unit_test",
            provider_symbol="EQ1",
            tags=["equity"],
        )
    ]

    plan = build_execution_plan(
        source_run_id="run_execution_realism_missing_bucket",
        source_allocation_id="allocation_execution_realism_missing_bucket",
        bucket_targets={"equity_cn": 0.4, "bond_cn": 0.6},
        restrictions=[],
        catalog=catalog,
        account_total_value=1_000.0,
        current_weights={"cash_liquidity": 1.0},
        available_cash=1_000.0,
        liquidity_reserve_min=0.0,
        minimum_trade_amount=50.0,
    )

    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.executable is False
    assert plan.execution_realism_summary.cash_target_amount == pytest.approx(0.0, abs=1e-6)
    assert plan.execution_realism_summary.amount_closure_delta == pytest.approx(-600.0, abs=1e-6)
    assert "account_amount_not_closed" in plan.execution_realism_summary.reasons
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


@pytest.mark.contract
def test_build_execution_plan_flags_initial_deploy_cash_shortfall_after_reserve_and_costs():
    plan = build_execution_plan(
        source_run_id="run_execution_realism_cash_shortfall",
        source_allocation_id="allocation_execution_realism_cash_shortfall",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.35,
            "gold": 0.15,
            "satellite": 0.05,
        },
        restrictions=[],
        account_total_value=1_000.0,
        current_weights={"cash_liquidity": 1.0},
        available_cash=1_000.0,
        liquidity_reserve_min=0.80,
        minimum_trade_amount=50.0,
        transaction_fee_rate={
            "equity_cn": 0.003,
            "bond_cn": 0.001,
            "gold": 0.001,
            "satellite": 0.004,
        },
    )

    assert plan.execution_realism_summary is not None
    assert plan.execution_realism_summary.executable is False
    assert plan.execution_realism_summary.initial_buy_amount == pytest.approx(80.0, abs=1e-6)
    assert plan.execution_realism_summary.fundable_initial_cash is not None
    assert plan.execution_realism_summary.fundable_initial_cash > plan.execution_realism_summary.initial_buy_amount
    assert "initial_deploy_cash_shortfall" not in plan.execution_realism_summary.reasons
    assert "tiny_trade:gold" in plan.execution_realism_summary.reasons
    assert "tiny_trade:satellite" in plan.execution_realism_summary.reasons
