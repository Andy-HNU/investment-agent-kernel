from __future__ import annotations

import pytest

from product_mapping import (
    BucketConstructionExplanation,
    ExecutionPlan,
    ExecutionPlanItem,
    ProductExplanation,
    ProductGroupExplanation,
    ProductScenarioMetrics,
    ProductCandidate,
    build_portfolio_explanation_surfaces,
    load_builtin_catalog,
    build_execution_plan,
)
from probability_engine.contracts import (
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
)


def test_product_explanation_requires_full_scenario_ladder() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=0.1,
        terminal_mean_delta_if_removed=1000.0,
        drawdown_delta_if_removed=0.01,
        median_return_delta_if_removed=0.005,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=["high_expected_return"],
        suggested_action="keep",
    )

    assert {
        item.scenario_kind for item in explanation.scenario_metrics
    } == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }


def test_product_explanation_preserves_optional_none_fields() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=None,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=None,
        median_return_delta_if_removed=None,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=[],
        suggested_action=None,
    )

    assert explanation.scenario_metrics[0].annualized_range is None
    assert explanation.scenario_metrics[0].terminal_value_range is None
    assert explanation.success_delta_if_removed is None
    assert explanation.terminal_mean_delta_if_removed is None
    assert explanation.drawdown_delta_if_removed is None
    assert explanation.median_return_delta_if_removed is None
    assert explanation.suggested_action is None


def test_product_explanation_defaults_suggested_action_to_none() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=None,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=None,
        median_return_delta_if_removed=None,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=[],
    )

    assert explanation.suggested_action is None


def test_product_explanation_rejects_incomplete_scenario_ladder() -> None:
    with pytest.raises(ValueError, match="full five-scenario ladder"):
        ProductExplanation(
            product_id="cn_equity_dividend_etf",
            role_in_portfolio="main_growth",
            scenario_metrics=[
                ProductScenarioMetrics(
                    scenario_kind="historical_replay",
                    annualized_range=(0.01, 0.02),
                    terminal_value_range=(1.0, 2.0),
                    pressure_score=None,
                    pressure_level=None,
                ),
                ProductScenarioMetrics(
                    scenario_kind="current_market",
                    annualized_range=(0.01, 0.02),
                    terminal_value_range=(1.0, 2.0),
                    pressure_score=8.0,
                    pressure_level="L0_宽松",
                ),
            ],
            success_delta_if_removed=0.1,
            terminal_mean_delta_if_removed=1000.0,
            drawdown_delta_if_removed=0.01,
            median_return_delta_if_removed=0.005,
            highest_overlap_product_ids=[],
            highest_diversification_product_ids=[],
            quality_labels=["high_expected_return"],
            suggested_action="keep",
        )


def test_product_group_explanation_matches_spec_shape() -> None:
    explanation = ProductGroupExplanation(
        group_type="duplicate_exposure_group",
        product_ids=["cn_equity_dividend_etf", "cn_equity_low_vol_etf"],
        rationale="shared equity beta with overlapping core exposure",
        success_delta_if_removed=0.05,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=0.02,
        median_return_delta_if_removed=0.01,
    )

    assert explanation.group_type == "duplicate_exposure_group"
    assert explanation.product_ids == ["cn_equity_dividend_etf", "cn_equity_low_vol_etf"]
    assert explanation.rationale == "shared equity beta with overlapping core exposure"
    assert explanation.terminal_mean_delta_if_removed is None


def test_bucket_construction_explanation_matches_spec_shape() -> None:
    explanation = BucketConstructionExplanation(
        bucket="satellite",
        requested_count=5,
        actual_count=4,
        count_source="explicit_user",
        count_satisfied=False,
        unmet_reason="minimum_weight_breach",
        why_split=["strong user request", "diversification gain"],
        no_split_counterfactual=["single_product", "lower_cost"],
        member_roles={"satellite_alpha": "theme_offset", "satellite_beta": "diversifier"},
    )

    assert explanation.actual_count == 4
    assert explanation.count_source == "explicit_user"
    assert explanation.count_satisfied is False
    assert explanation.unmet_reason == "minimum_weight_breach"
    assert explanation.why_split == ["strong user request", "diversification gain"]
    assert explanation.no_split_counterfactual == ["single_product", "lower_cost"]
    assert explanation.member_roles == {
        "satellite_alpha": "theme_offset",
        "satellite_beta": "diversifier",
    }


def _fake_probability_result(weights_by_product: dict[str, float], *, scenario_shift: float = 0.0) -> ProbabilityEngineRunResult:
    total_weight = sum(weights_by_product.values()) or 1.0
    normalized_weights = {product_id: weight / total_weight for product_id, weight in weights_by_product.items()}
    concentration = sum(weight * weight for weight in normalized_weights.values())
    success_probability = round(max(0.0, min(1.0, 0.78 - 0.30 * concentration)), 4)
    terminal_value_mean = round(100_000.0 + 24_000.0 * (1.0 - concentration), 2)
    cagr_p50 = round(0.04 + 0.03 * (1.0 - concentration), 4)
    drawdown_p95 = round(0.10 + 0.22 * concentration, 4)

    def _recipe_result(scenario_kind: str, *, offset: float) -> RecipeSimulationResult:
        return RecipeSimulationResult(
            recipe_name=f"recipe_{scenario_kind}",
            role="primary",
            success_probability=round(max(0.0, min(1.0, success_probability - offset * 0.01)), 4),
            success_probability_range=(round(max(0.0, success_probability - 0.03 - offset * 0.01), 4), round(min(1.0, success_probability + 0.03 + offset * 0.01), 4)),
            cagr_range=(round(cagr_p50 - 0.01 - offset * 0.005, 4), round(cagr_p50 + 0.01 + offset * 0.005, 4)),
            drawdown_range=(round(max(0.0, drawdown_p95 - 0.04 - offset * 0.01), 4), round(min(1.0, drawdown_p95 + 0.04 + offset * 0.01), 4)),
            sample_count=128,
            path_stats=PathStatsSummary(
                terminal_value_mean=round(terminal_value_mean - offset * 2_000.0, 2),
                terminal_value_p05=round(terminal_value_mean - 8_000.0 - offset * 2_000.0, 2),
                terminal_value_p50=round(terminal_value_mean - 2_000.0 - offset * 1_000.0, 2),
                terminal_value_p95=round(terminal_value_mean + 8_000.0 + offset * 2_000.0, 2),
                cagr_p05=round(cagr_p50 - 0.01 - offset * 0.005, 4),
                cagr_p50=round(cagr_p50 - offset * 0.002, 4),
                cagr_p95=round(cagr_p50 + 0.01 + offset * 0.005, 4),
                max_drawdown_p05=round(max(0.0, drawdown_p95 - 0.06 - offset * 0.01), 4),
                max_drawdown_p50=round(max(0.0, drawdown_p95 - 0.02 - offset * 0.005), 4),
                max_drawdown_p95=round(drawdown_p95 + offset * 0.01, 4),
                success_count=79,
                path_count=128,
            ),
            calibration_link_ref=f"evidence://contract/{scenario_kind}",
        )

    scenario_offsets = {
        "historical_replay": 0.0,
        "current_market": 0.3,
        "deteriorated_mild": 0.7,
        "deteriorated_moderate": 1.1,
        "deteriorated_severe": 1.6,
    }
    primary = _recipe_result("current_market", offset=scenario_offsets["current_market"])
    scenario_comparison = [
        {
            "scenario_kind": scenario_kind,
            "label": scenario_kind,
            "pressure": {
                "scenario_kind": scenario_kind,
                "market_pressure_score": float(index * 10 + 5),
                "market_pressure_level": f"L{index}_测试",
            }
            if scenario_kind != "historical_replay"
            else None,
            "recipe_result": _recipe_result(scenario_kind, offset=offset + scenario_shift),
        }
        for index, (scenario_kind, offset) in enumerate(scenario_offsets.items())
    ]
    return ProbabilityEngineRunResult(
        run_outcome_status="success",
        resolved_result_category="formal_independent_result",
        output=ProbabilityEngineOutput(
            primary_result=primary,
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=ProbabilityDisclosurePayload(
                published_point=success_probability,
                published_range=(round(max(0.0, success_probability - 0.02), 4), round(min(1.0, success_probability + 0.02), 4)),
                disclosure_level="point_and_range",
                confidence_level="medium",
                challenger_gap=None,
                stress_gap=None,
                gap_total=None,
                widening_method="contract_fixture",
            ),
            evidence_refs=["evidence://contract/probability"],
            current_market_pressure={
                "scenario_kind": "current_market",
                "market_pressure_score": 25.0,
                "market_pressure_level": "L1_中性偏紧",
            },
            scenario_comparison=scenario_comparison,
        ),
        failure_artifact=None,
    )


def _execution_plan_for_three_products() -> ExecutionPlan:
    equity_a = ProductCandidate(
        product_id="equity_a",
        product_name="Equity A",
        asset_bucket="equity_cn",
        product_family="equity_family",
        wrapper_type="etf",
        provider_source="test",
        risk_labels=["style_offset"],
    )
    equity_b = ProductCandidate(
        product_id="equity_b",
        product_name="Equity B",
        asset_bucket="equity_cn",
        product_family="equity_family",
        wrapper_type="etf",
        provider_source="test",
        risk_labels=["style_offset"],
    )
    gold = ProductCandidate(
        product_id="gold_c",
        product_name="Gold C",
        asset_bucket="gold",
        product_family="gold_family",
        wrapper_type="etf",
        provider_source="test",
        risk_labels=["defensive"],
    )
    return ExecutionPlan(
        plan_id="test:plan",
        source_run_id="test",
        source_allocation_id="test",
        items=[
            ExecutionPlanItem(
                asset_bucket="equity_cn",
                target_weight=0.50,
                current_weight=None,
                current_amount=None,
                target_amount=None,
                trade_direction=None,
                trade_amount=None,
                initial_trade_amount=None,
                deferred_trade_amount=None,
                estimated_fee=None,
                estimated_slippage=None,
                violates_minimum_trade=False,
                trigger_conditions=[],
                primary_product_id="equity_a",
                alternate_product_ids=[],
                rationale=[],
                risk_labels=["style_offset"],
                primary_product=equity_a,
                alternate_products=[],
            ),
            ExecutionPlanItem(
                asset_bucket="equity_cn",
                target_weight=0.30,
                current_weight=None,
                current_amount=None,
                target_amount=None,
                trade_direction=None,
                trade_amount=None,
                initial_trade_amount=None,
                deferred_trade_amount=None,
                estimated_fee=None,
                estimated_slippage=None,
                violates_minimum_trade=False,
                trigger_conditions=[],
                primary_product_id="equity_b",
                alternate_product_ids=[],
                rationale=[],
                risk_labels=["style_offset"],
                primary_product=equity_b,
                alternate_products=[],
            ),
            ExecutionPlanItem(
                asset_bucket="gold",
                target_weight=0.20,
                current_weight=None,
                current_amount=None,
                target_amount=None,
                trade_direction=None,
                trade_amount=None,
                initial_trade_amount=None,
                deferred_trade_amount=None,
                estimated_fee=None,
                estimated_slippage=None,
                violates_minimum_trade=False,
                trigger_conditions=[],
                primary_product_id="gold_c",
                alternate_product_ids=[],
                rationale=[],
                risk_labels=["defensive"],
                primary_product=gold,
                alternate_products=[],
            ),
        ],
        bucket_construction_explanations={},
        bucket_construction_suggestions={},
        warnings=[],
        confirmation_required=False,
        plan_version=1,
        registry_candidate_count=3,
        runtime_candidate_count=3,
        runtime_candidates=[],
        product_proxy_specs=[],
        proxy_universe_summary=None,
        execution_realism_summary=None,
        maintenance_policy_summary={},
        candidate_filter_breakdown=None,
        valuation_audit_summary={},
        policy_news_audit_summary={},
        formal_path_preflight={},
        failure_artifact=None,
    )


def _probability_input_for_three_products() -> dict[str, object]:
    return {
        "current_positions": [
            {"product_id": "equity_a", "weight": 0.50, "market_value": 50_000.0, "units": 50_000.0},
            {"product_id": "equity_b", "weight": 0.30, "market_value": 30_000.0, "units": 30_000.0},
            {"product_id": "gold_c", "weight": 0.20, "market_value": 20_000.0, "units": 20_000.0},
        ],
        "products": [
            {"product_id": "equity_a", "asset_bucket": "equity_cn"},
            {"product_id": "equity_b", "asset_bucket": "equity_cn"},
            {"product_id": "gold_c", "asset_bucket": "gold"},
        ],
        "contribution_schedule": [
            {"date": "2026-04-14", "amount": 1_000.0, "target_weights": {"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20}}
        ],
        "recipes": [
            {
                "recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1",
                "role": "primary",
                "innovation_layer": "student_t",
                "volatility_layer": "factor_and_product_garch",
                "dependency_layer": "factor_level_dcc",
                "jump_layer": "systemic_plus_idio",
                "regime_layer": "markov_regime",
                "estimation_basis": "daily_product_formal",
                "dependency_scope": "factor",
                "path_count": 4000,
            }
        ],
        "challenger_path_count": 128,
        "stress_path_count": 64,
    }


def test_portfolio_explanation_surfaces_handle_missing_probability_result_safely() -> None:
    plan = _execution_plan_for_three_products()
    surfaces = build_portfolio_explanation_surfaces(execution_plan=plan, probability_engine_result=None)

    assert set(surfaces) == {
        "bucket_construction_explanations",
        "product_explanations",
        "product_group_explanations",
    }
    assert surfaces["product_explanations"]["equity_a"].success_delta_if_removed is None
    assert surfaces["product_explanations"]["equity_a"].scenario_metrics[0].pressure_level is None


def test_portfolio_explanation_surfaces_use_scenario_specific_summaries() -> None:
    plan = _execution_plan_for_three_products()
    probability_result = _fake_probability_result({"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20})
    surfaces = build_portfolio_explanation_surfaces(
        execution_plan=plan,
        probability_engine_result=probability_result,
        probability_engine_input=_probability_input_for_three_products(),
    )

    scenario_metrics = surfaces["product_explanations"]["equity_a"].scenario_metrics
    assert scenario_metrics[1].annualized_range != scenario_metrics[2].annualized_range
    assert scenario_metrics[2].annualized_range != scenario_metrics[4].annualized_range
    assert scenario_metrics[4].pressure_level == "L4_测试"


def test_portfolio_explanation_surfaces_recompute_leave_out_from_redistributed_weights(monkeypatch) -> None:
    plan = _execution_plan_for_three_products()
    probability_input = _probability_input_for_three_products()
    baseline = _fake_probability_result({"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20})
    captured_path_counts: list[tuple[list[int], int | None, int | None]] = []

    monkeypatch.setattr(
        "product_mapping.explanations.run_probability_engine",
        lambda sim_input: (
            captured_path_counts.append(
                (
                    [int(recipe.get("path_count") or 0) for recipe in list(sim_input.get("recipes") or [])],
                    sim_input.get("challenger_path_count"),
                    sim_input.get("stress_path_count"),
                )
            )
            or _fake_probability_result(
                {position["product_id"]: float(position["weight"]) for position in sim_input["current_positions"]}
            )
        ),
    )

    surfaces = build_portfolio_explanation_surfaces(
        execution_plan=plan,
        probability_engine_result=baseline,
        probability_engine_input=probability_input,
    )

    def _expected_delta(removed_product_id: str) -> float:
        weights = {"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20}
        removed_weight = weights.pop(removed_product_id)
        remaining_total = sum(weights.values())
        redistributed = {product_id: weight / remaining_total for product_id, weight in weights.items()}
        full_concentration = sum(weight * weight for weight in {"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20}.values())
        reduced_concentration = sum(weight * weight for weight in redistributed.values())
        full_success = round(max(0.0, min(1.0, 0.78 - 0.30 * full_concentration)), 4)
        reduced_success = round(max(0.0, min(1.0, 0.78 - 0.30 * reduced_concentration)), 4)
        return round(full_success - reduced_success, 4)

    equity_a = surfaces["product_explanations"]["equity_a"]
    equity_b = surfaces["product_explanations"]["equity_b"]
    assert equity_a.success_delta_if_removed != equity_b.success_delta_if_removed
    assert equity_a.success_delta_if_removed == pytest.approx(_expected_delta("equity_a"), abs=1e-4)
    assert equity_b.success_delta_if_removed == pytest.approx(_expected_delta("equity_b"), abs=1e-4)
    assert captured_path_counts
    assert all(max(recipe_counts or [0]) <= 1 for recipe_counts, _, _ in captured_path_counts)
    assert all((challenger_path_count or 0) <= 1 for _, challenger_path_count, _ in captured_path_counts)
    assert all((stress_path_count or 0) <= 1 for _, _, stress_path_count in captured_path_counts)
    assert surfaces["product_group_explanations"]["duplicate_exposure_group"].success_delta_if_removed is not None


def test_portfolio_explanation_surfaces_use_supplied_probability_runner_for_group_counterfactuals() -> None:
    plan = _execution_plan_for_three_products()
    probability_input = _probability_input_for_three_products()
    baseline = _fake_probability_result({"equity_a": 0.50, "equity_b": 0.30, "gold_c": 0.20})
    observed_weight_sets: list[tuple[tuple[str, float], ...]] = []

    def _runner(sim_input: dict[str, object]) -> ProbabilityEngineRunResult:
        weight_map = {
            str(position["product_id"]): float(position["weight"])
            for position in list(sim_input["current_positions"])
        }
        observed_weight_sets.append(tuple(sorted(weight_map.items())))
        return _fake_probability_result(weight_map)

    surfaces = build_portfolio_explanation_surfaces(
        execution_plan=plan,
        probability_engine_result=baseline,
        probability_engine_input=probability_input,
        probability_engine_runner=_runner,
    )

    assert len(observed_weight_sets) == 4
    assert tuple(sorted((("equity_b", 0.6), ("gold_c", 0.4)))) in observed_weight_sets
    assert tuple(sorted((("equity_a", 0.625), ("equity_b", 0.37499999999999994)))) in observed_weight_sets
    assert tuple(sorted((("equity_a", 0.7142857142857143), ("gold_c", 0.28571428571428575)))) in observed_weight_sets
    assert tuple(sorted((("gold_c", 1.0),))) in observed_weight_sets
    assert surfaces["product_group_explanations"]["duplicate_exposure_group"].success_delta_if_removed is not None


def test_portfolio_explanation_surfaces_include_top_level_sets(monkeypatch) -> None:
    catalog = load_builtin_catalog()
    equity = next(item for item in catalog if item.product_id == "cn_equity_dividend_etf")
    equity_peer = next(item for item in catalog if item.product_id == "cn_equity_csi300_etf")
    gold = next(item for item in catalog if item.product_id == "cn_gold_etf")
    cash = next(item for item in catalog if item.product_id == "cn_cash_money_fund")
    plan = build_execution_plan(
        source_run_id="explanation_surface_test",
        source_allocation_id="explanation_surface_alloc",
        bucket_targets={"equity_cn": 0.50, "gold": 0.10, "cash_liquidity": 0.40},
        catalog=[equity, equity_peer, gold, cash],
        runtime_candidates=[equity, equity_peer, gold, cash],
        formal_path_required=False,
        execution_policy="exploratory",
    )
    probability_weights = {item.primary_product_id: float(item.target_weight) for item in plan.items}
    probability_input = {
        "current_positions": [
            {
                "product_id": item.primary_product_id,
                "weight": float(item.target_weight),
                "market_value": round(100_000.0 * float(item.target_weight), 2),
                "units": round(100_000.0 * float(item.target_weight), 2),
            }
            for item in plan.items
        ],
        "products": [
            {"product_id": item.primary_product_id, "asset_bucket": item.asset_bucket}
            for item in plan.items
        ],
        "contribution_schedule": [
            {
                "date": "2026-04-14",
                "amount": 1_000.0,
                "target_weights": dict(probability_weights),
            }
        ],
    }
    monkeypatch.setattr(
        "product_mapping.explanations.run_probability_engine",
        lambda sim_input: _fake_probability_result(
            {position["product_id"]: float(position["weight"]) for position in sim_input["current_positions"]}
        ),
    )
    surfaces = build_portfolio_explanation_surfaces(
        execution_plan=plan,
        probability_engine_result=_fake_probability_result(probability_weights),
        probability_engine_input=probability_input,
    )

    assert set(surfaces) == {
        "bucket_construction_explanations",
        "product_explanations",
        "product_group_explanations",
    }
    assert set(surfaces["bucket_construction_explanations"]) == {"equity_cn", "gold", "cash_liquidity"}
    assert {item.scenario_kind for item in surfaces["product_explanations"]["cn_equity_dividend_etf"].scenario_metrics} == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }
    assert surfaces["product_explanations"]["cn_equity_dividend_etf"].success_delta_if_removed is not None
    assert any(
        group.group_type == "duplicate_exposure_group"
        for group in surfaces["product_group_explanations"].values()
    )
