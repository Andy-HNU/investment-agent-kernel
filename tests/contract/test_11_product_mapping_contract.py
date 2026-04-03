from __future__ import annotations

import pytest

from product_mapping import (
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    build_execution_plan,
    load_builtin_catalog,
)


@pytest.mark.contract
def test_builtin_catalog_covers_first_wave_buckets_with_typed_candidates():
    catalog = load_builtin_catalog()

    assert catalog
    assert all(isinstance(candidate, ProductCandidate) for candidate in catalog)
    assert {"equity_cn", "bond_cn", "gold", "cash_liquidity"}.issubset(
        {candidate.asset_bucket for candidate in catalog}
    )


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
        },
        restrictions=[],
    )

    assert isinstance(plan, ExecutionPlan)
    assert plan.status == "draft"
    assert plan.confirmation_required is True
    assert all(isinstance(item, ExecutionPlanItem) for item in plan.items)

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
    assert equity_item.primary_product.wrapper_type != "single_stock"
    assert all(product.wrapper_type != "single_stock" for product in equity_item.alternate_products)
    assert any("禁个股" in warning for warning in plan.warnings)


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
