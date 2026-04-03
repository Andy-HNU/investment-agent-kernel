from __future__ import annotations

import pytest

from product_mapping import build_execution_plan, load_builtin_catalog
from product_mapping.selection import normalize_user_restrictions


@pytest.mark.contract
def test_builtin_catalog_covers_v12_product_families_and_wrappers():
    catalog = load_builtin_catalog()

    assert {"equity_cn", "bond_cn", "gold", "cash_liquidity", "satellite"}.issubset(
        {candidate.asset_bucket for candidate in catalog}
    )
    assert {"etf", "fund", "cash_mgmt", "single_stock"}.issubset(
        {candidate.wrapper_type for candidate in catalog}
    )


@pytest.mark.contract
def test_no_stock_disallows_single_stocks_but_keeps_index_wrappers():
    restrictions = normalize_user_restrictions(["不买股票"])

    assert "single_stock" in restrictions.forbidden_wrappers
    assert "equity_cn" not in restrictions.forbidden_exposures


@pytest.mark.contract
def test_build_execution_plan_keeps_equity_bucket_when_only_single_stocks_are_forbidden():
    plan = build_execution_plan(
        source_run_id="run_no_single_stock",
        source_allocation_id="allocation_no_single_stock",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.30,
            "gold": 0.15,
            "cash_liquidity": 0.10,
        },
        restrictions=["不买股票"],
    )

    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")

    assert equity_item.primary_product.wrapper_type != "single_stock"
    assert all(product.wrapper_type != "single_stock" for product in equity_item.alternate_products)
    assert any("禁个股" in warning for warning in plan.warnings)


@pytest.mark.contract
def test_build_execution_plan_returns_multi_product_slices_and_evidence_for_major_buckets():
    plan = build_execution_plan(
        source_run_id="run_multi_product_selection",
        source_allocation_id="allocation_multi_product_selection",
        bucket_targets={
            "equity_cn": 0.40,
            "bond_cn": 0.30,
            "gold": 0.15,
            "cash_liquidity": 0.10,
            "satellite": 0.05,
        },
        restrictions=[],
    )

    by_bucket = {item.asset_bucket: item for item in plan.items}

    assert len(by_bucket["equity_cn"].recommended_products) >= 2
    assert len(by_bucket["bond_cn"].recommended_products) >= 2
    assert len(by_bucket["gold"].recommended_products) >= 2
    assert len(by_bucket["cash_liquidity"].recommended_products) >= 2
    assert len(by_bucket["satellite"].recommended_products) >= 2
    assert by_bucket["equity_cn"].selection_evidence["core_or_satellite"] == "core"
    assert by_bucket["satellite"].selection_evidence["core_or_satellite"] == "satellite"
    assert "selection_reason" in by_bucket["bond_cn"].selection_evidence


@pytest.mark.contract
def test_build_execution_plan_filters_technology_satellite_when_restriction_forbids_tech():
    plan = build_execution_plan(
        source_run_id="run_no_tech",
        source_allocation_id="allocation_no_tech",
        bucket_targets={"satellite": 0.12},
        restrictions=["不碰科技"],
    )

    satellite_item = next(item for item in plan.items if item.asset_bucket == "satellite")

    assert satellite_item.primary_product.product_id != "cn_satellite_chip_etf"
    assert all("technology" not in product.style_tags for product in satellite_item.recommended_products)
