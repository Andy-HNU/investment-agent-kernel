from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from frontdesk.service import run_frontdesk_onboarding
import orchestrator.engine as orchestrator_engine
from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


def _profile(*, account_profile_id: str = "user_portfolio_contract") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=100_000.0,
        monthly_contribution=8_000.0,
        goal_amount=1_200_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.45,
            "bond_cn": 0.25,
            "gold": 0.10,
            "cash_liquidity": 0.20,
        },
    )


def _profile_bundle_with_user_portfolio(
    profile: UserOnboardingProfile,
    *,
    user_portfolio: list[dict[str, object]],
    as_of: str = "2026-04-07T00:00:00Z",
):
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    bundle.raw_inputs = deepcopy(bundle.raw_inputs)
    bundle.raw_inputs["user_portfolio"] = deepcopy(user_portfolio)
    return bundle


@pytest.mark.contract
def test_user_portfolio_is_evaluated_as_entered_without_rewrite(monkeypatch, tmp_path):
    user_portfolio = [
        {"product_id": "cn_equity_dividend_etf", "target_weight": 0.25},
        {"product_id": "cn_equity_csi300_etf", "target_weight": 0.25},
        {"product_id": "cn_gold_etf", "target_weight": 0.10},
        {"product_id": "cn_cash_money_fund", "target_weight": 0.40},
    ]
    profile = _profile(account_profile_id="user_portfolio_no_rewrite")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["requested_structure_visibility"]["rewrite_applied"] is False
    assert result["requested_structure_visibility"]["requested_structure"] == user_portfolio
    assert [item["primary_product_id"] for item in result["pending_execution_plan"]["items"]] == [
        "cn_equity_dividend_etf",
        "cn_equity_csi300_etf",
        "cn_gold_etf",
        "cn_cash_money_fund",
    ]
    assert [item["target_weight"] for item in result["pending_execution_plan"]["items"]] == [
        0.25,
        0.25,
        0.10,
        0.40,
    ]
    assert result["unknown_product_resolution"]["state"] == "recognized"


@pytest.mark.contract
def test_unrecognized_product_blocks_strict_formal_until_user_resolves(monkeypatch, tmp_path):
    user_portfolio = [
        {"product_id": "mystery_fund_x", "target_weight": 1.0},
    ]
    profile = _profile(account_profile_id="user_portfolio_unknown_product")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_unknown.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "unrecognized_requires_user_action"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is True
    assert result["unknown_product_resolution"]["items"][0]["product_state"] == "unrecognized_product"
    assert result["pending_execution_plan"]["items"][0]["primary_product_id"] == "mystery_fund_x"
    assert result["pending_execution_plan"]["items"][0]["target_weight"] == 1.0
    assert result["run_outcome_status"] == "blocked"
    product_explanation = result["product_explanations"]["mystery_fund_x"]
    assert product_explanation["quality_labels"] == []
    assert product_explanation["suggested_action"] is None
    assert product_explanation["success_delta_if_removed"] is None


@pytest.mark.contract
def test_user_selected_proxy_can_proceed_without_strict_block(monkeypatch, tmp_path):
    user_portfolio = [
        {
            "product_id": "mystery_fund_proxy",
            "target_weight": 0.30,
            "selected_proxy_product_id": "cn_cash_money_fund",
        },
        {"product_id": "cn_gold_etf", "target_weight": 0.70},
    ]
    profile = _profile(account_profile_id="user_portfolio_proxy")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_proxy.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "user_selected_proxy"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is False
    assert result["unknown_product_resolution"]["items"][0]["resolution_state"] == "user_selected_proxy"
    assert result["pending_execution_plan"]["items"][0]["primary_product_id"] == "cn_cash_money_fund"
    assert result["pending_execution_plan"]["items"][0]["target_weight"] == 0.30
    assert result["run_outcome_status"] in {"completed", "degraded"}


@pytest.mark.contract
def test_estimated_non_formal_allowed_continues_in_degraded_mode(monkeypatch, tmp_path):
    user_portfolio = [
        {
            "product_id": "mystery_fund_estimate",
            "target_weight": 0.20,
            "allow_non_formal": True,
        },
        {"product_id": "cn_cash_money_fund", "target_weight": 0.80},
    ]
    profile = _profile(account_profile_id="user_portfolio_estimated")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_estimated.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "estimated_non_formal_allowed"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is False
    assert result["unknown_product_resolution"]["items"][0]["resolution_state"] == "estimated_non_formal_allowed"
    assert result["probability_engine_result"] is not None
    assert result["probability_engine_result"]["run_outcome_status"] in {"success", "degraded"}
    assert result["pending_execution_plan"]["items"][0]["primary_product_id"] == "mystery_fund_estimate"
    assert result["pending_execution_plan"]["items"][0]["target_weight"] == 0.20
    assert result["run_outcome_status"] == "degraded"


@pytest.mark.contract
def test_runtime_only_candidate_is_resolved_consistently_across_evaluation_and_plan(monkeypatch, tmp_path):
    from product_mapping import load_builtin_catalog

    builtin_candidate = next(item for item in load_builtin_catalog() if item.product_id == "cn_equity_csi300_etf")
    runtime_candidate = replace(
        builtin_candidate,
        product_id="runtime_equity_proxy",
        product_name="Runtime Equity Proxy",
    )
    user_portfolio = [
        {"product_id": "runtime_equity_proxy", "target_weight": 0.60},
        {"product_id": "cn_gold_etf", "target_weight": 0.40},
    ]
    profile = _profile(account_profile_id="user_portfolio_runtime_only")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)
    monkeypatch.setattr(
        "orchestrator.engine._extract_execution_plan_runtime_candidates",
        lambda envelope: [runtime_candidate],
    )

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_runtime_only.sqlite")

    assert result["unknown_product_resolution"]["state"] == "recognized"
    assert [item["primary_product_id"] for item in result["pending_execution_plan"]["items"]] == [
        "runtime_equity_proxy",
        "cn_gold_etf",
    ]
    assert result["pending_execution_plan"]["items"][0]["primary_product"]["product_id"] == "runtime_equity_proxy"


@pytest.mark.contract
def test_user_portfolio_probability_engine_result_is_populated_for_evaluation_mode(monkeypatch):
    user_portfolio = [
        {"product_id": "cn_equity_dividend_etf", "target_weight": 0.25},
        {"product_id": "cn_equity_csi300_etf", "target_weight": 0.25},
        {"product_id": "cn_gold_etf", "target_weight": 0.10},
        {"product_id": "cn_cash_money_fund", "target_weight": 0.40},
    ]
    profile = _profile(account_profile_id="user_portfolio_probability")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    bundle = _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio)
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "user_portfolio_probability"},
        raw_inputs=bundle.raw_inputs,
    ).to_dict()

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["probability_engine_result"] is not None
    assert result["probability_engine_result"]["run_outcome_status"] in {"success", "degraded"}
    assert result["probability_engine_result"]["output"]["primary_result"]["success_probability"] is not None
    assert result["probability_engine_result"]["output"]["primary_result"]["path_stats"]


@pytest.mark.contract
def test_user_portfolio_engine_error_fallback_keeps_explanations_neutral_and_skips_counterfactual_reruns(monkeypatch):
    user_portfolio = [
        {"product_id": "cn_equity_dividend_etf", "target_weight": 0.60},
        {"product_id": "cn_gold_etf", "target_weight": 0.40},
    ]
    profile = _profile(account_profile_id="user_portfolio_engine_error_fallback")
    bundle = _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio)
    call_count = 0

    def _flaky_probability_engine(sim_input):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("synthetic engine failure")
        return {
            "run_outcome_status": "success",
            "resolved_result_category": "formal_strict_result",
            "output": {
                "primary_result": {
                    "recipe_name": "unexpected_counterfactual",
                    "role": "primary",
                    "success_probability": 0.9,
                    "success_probability_range": (0.85, 0.95),
                    "cagr_range": (0.04, 0.08),
                    "drawdown_range": (0.05, 0.10),
                    "sample_count": 8,
                    "path_stats": {
                        "terminal_value_mean": 123000.0,
                        "terminal_value_p05": 100000.0,
                        "terminal_value_p50": 121000.0,
                        "terminal_value_p95": 130000.0,
                        "cagr_p05": 0.03,
                        "cagr_p50": 0.06,
                        "cagr_p95": 0.09,
                        "max_drawdown_p05": 0.02,
                        "max_drawdown_p50": 0.04,
                        "max_drawdown_p95": 0.10,
                        "success_count": 7,
                        "path_count": 8,
                    },
                    "calibration_link_ref": "evidence://unexpected_counterfactual",
                },
                "challenger_results": [],
                "stress_results": [],
                "model_disagreement": {},
                "probability_disclosure_payload": {
                    "published_point": 0.9,
                    "published_range": (0.85, 0.95),
                    "disclosure_level": "point_and_range",
                    "confidence_level": "high",
                    "challenger_gap": None,
                    "stress_gap": None,
                    "gap_total": None,
                    "widening_method": "unexpected_counterfactual",
                },
                "evidence_refs": [],
                "current_market_pressure": None,
                "scenario_comparison": [],
            },
            "failure_artifact": None,
        }

    monkeypatch.setattr(orchestrator_engine, "_build_product_simulation_input", lambda *args, **kwargs: {"synthetic": True})
    monkeypatch.setattr(
        orchestrator_engine,
        "_build_probability_engine_run_input",
        lambda **kwargs: (
            {
                "current_positions": [
                    {"product_id": "cn_equity_dividend_etf", "weight": 0.60, "market_value": 60000.0, "units": 60000.0},
                    {"product_id": "cn_gold_etf", "weight": 0.40, "market_value": 40000.0, "units": 40000.0},
                ],
                "products": [
                    {"product_id": "cn_equity_dividend_etf", "asset_bucket": "equity_cn"},
                    {"product_id": "cn_gold_etf", "asset_bucket": "gold"},
                ],
                "recipes": [{"recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1"}],
            },
            None,
        ),
    )
    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _flaky_probability_engine)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "user_portfolio_engine_error_fallback"},
        raw_inputs=bundle.raw_inputs,
    ).to_dict()

    assert call_count == 1
    assert result["probability_engine_result"]["run_outcome_status"] == "degraded"
    explanation = result["product_explanations"]["cn_equity_dividend_etf"]
    assert explanation["success_delta_if_removed"] is None
    assert explanation["quality_labels"] == []
    assert explanation["suggested_action"] is None


@pytest.mark.contract
def test_user_excluded_product_continues_without_strict_block(monkeypatch, tmp_path):
    user_portfolio = [
        {
            "product_id": "mystery_fund_drop",
            "target_weight": 0.20,
            "exclude": True,
        },
        {"product_id": "cn_gold_etf", "target_weight": 0.80},
    ]
    profile = _profile(account_profile_id="user_portfolio_excluded")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_excluded.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "user_excluded_product"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is False
    assert result["unknown_product_resolution"]["items"][0]["resolution_state"] == "user_excluded_product"
    assert all(item["primary_product_id"] != "mystery_fund_drop" for item in result["pending_execution_plan"]["items"])
    assert [item["primary_product_id"] for item in result["pending_execution_plan"]["items"]] == [
        "cn_gold_etf",
    ]
    assert [item["target_weight"] for item in result["pending_execution_plan"]["items"]] == [
        0.80,
    ]


@pytest.mark.contract
def test_strict_unrecognized_user_portfolio_does_not_call_probability_engine_even_if_inputs_are_buildable(monkeypatch):
    user_portfolio = [
        {"product_id": "mystery_fund_x", "target_weight": 1.0},
    ]
    profile = _profile(account_profile_id="user_portfolio_strict_blocked_builder")
    bundle = _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio)

    monkeypatch.setattr(orchestrator_engine, "_build_product_simulation_input", lambda *args, **kwargs: {"synthetic": True})
    monkeypatch.setattr(
        orchestrator_engine,
        "_build_probability_engine_run_input",
        lambda **kwargs: ({"products": [{"product_id": "mystery_fund_x"}], "recipes": []}, None),
    )

    def _unexpected_run_probability_engine(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("strict_formal_blocked user portfolio must not invoke run_probability_engine")

    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _unexpected_run_probability_engine)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "user_portfolio_strict_blocked_builder"},
        raw_inputs=bundle.raw_inputs,
    ).to_dict()

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "unrecognized_requires_user_action"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is True
    assert result["probability_engine_result"] is not None
    assert result["probability_engine_result"]["run_outcome_status"] == "blocked"
