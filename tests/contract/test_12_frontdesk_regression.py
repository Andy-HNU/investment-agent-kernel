from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile

import pytest

from frontdesk.service import (
    _frontdesk_summary,
    approve_frontdesk_execution_plan,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from frontdesk.storage import FrontdeskExecutionPlanRecord, FrontdeskStore, _compare_execution_plans
from orchestrator.engine import _build_execution_plan_summary, run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.formal_snapshot_helpers import (
    formal_market_raw_overrides as _support_formal_market_raw_overrides,
    observed_market_raw_overrides as _support_observed_market_raw_overrides,
    write_formal_snapshot_source,
)


def _profile(*, account_profile_id: str = "frontdesk_andy") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
    )


def _result_payload(profile: UserOnboardingProfile, *, as_of: str = "2026-03-30T00:00:00Z") -> tuple[dict, dict]:
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": f"{profile.account_profile_id}_{as_of}"},
        raw_inputs=bundle.raw_inputs,
    )
    return result.to_dict(), bundle.input_provenance


def _observed_external_snapshot_source(
    tmp_path: Path,
    profile: UserOnboardingProfile,
    *,
    as_of: str = "2026-03-30T00:00:00Z",
    market_raw_overrides: dict[str, object] | None = None,
) -> Path:
    effective_market_raw_overrides = deepcopy(_support_observed_market_raw_overrides())
    if market_raw_overrides:
        for key, value in dict(market_raw_overrides).items():
            effective_market_raw_overrides[key] = deepcopy(value)
    return write_formal_snapshot_source(
        tmp_path,
        profile,
        as_of=as_of,
        market_raw_overrides=effective_market_raw_overrides,
    )


def _user_portfolio_bundle(
    profile: UserOnboardingProfile,
    *,
    user_portfolio: list[dict[str, object]],
    as_of: str = "2026-03-30T00:00:00Z",
):
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    bundle.raw_inputs = deepcopy(bundle.raw_inputs)
    bundle.raw_inputs["user_portfolio"] = deepcopy(user_portfolio)
    return bundle


@pytest.mark.contract
def test_observed_external_snapshot_uses_non_repeating_factor_history_series(tmp_path):
    profile = _profile(account_profile_id="observed_series_user")
    snapshot_path = _observed_external_snapshot_source(tmp_path, profile)
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    products = (
        snapshot_payload["market_raw"]["historical_dataset"]["product_simulation_input"]["products"]
    )
    equity_series = next(item["return_series"] for item in products if item["product_id"] == "cn_equity_dividend_etf")
    historical_dataset = snapshot_payload["market_raw"]["historical_dataset"]
    factor_mapping = snapshot_payload["market_raw"]["probability_engine"]["factor_mapping"]

    assert len(equity_series) >= 16
    assert equity_series[:8] != equity_series[8:16]
    assert historical_dataset["source_name"] == "observed_market_history"
    assert historical_dataset["source_ref"].startswith("observed://")
    assert factor_mapping["source_name"] == "observed_product_level_factor_mapping"
    assert factor_mapping["source_ref"].startswith("observed://")


@pytest.mark.contract
def test_helper_formal_snapshot_keeps_repeated_acceptance_pattern(tmp_path):
    profile = _profile(account_profile_id="helper_series_user")
    snapshot_path = write_formal_snapshot_source(tmp_path, profile)
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    products = (
        snapshot_payload["market_raw"]["historical_dataset"]["product_simulation_input"]["products"]
    )
    equity_series = next(item["return_series"] for item in products if item["product_id"] == "cn_equity_dividend_etf")
    historical_dataset = snapshot_payload["market_raw"]["historical_dataset"]
    factor_mapping = snapshot_payload["market_raw"]["probability_engine"]["factor_mapping"]

    assert len(equity_series) >= 16
    assert equity_series[:8] == equity_series[8:16]
    assert historical_dataset["source_name"] == "helper_market_history"
    assert historical_dataset["source_ref"].startswith("helper://")
    assert factor_mapping["source_name"] == "helper_pattern_factor_mapping"
    assert factor_mapping["source_ref"].startswith("helper://")


@pytest.mark.contract
def test_frontdesk_summary_exposes_pressure_ladder_from_probability_engine_output() -> None:
    summary = _frontdesk_summary(
        account_profile_id="pressure_ladder_frontdesk",
        display_name="Andy",
        db_path=Path("/tmp/pressure_ladder_frontdesk.sqlite"),
        result_payload={
            "run_id": "run_pressure_ladder_frontdesk",
            "workflow_type": "onboarding",
            "status": "completed",
            "run_outcome_status": "completed",
            "resolved_result_category": "formal_independent_result",
            "decision_card": {},
            "probability_engine_result": {
                "run_outcome_status": "success",
                "resolved_result_category": "formal_strict_result",
                "output": {
                    "probability_disclosure_payload": {
                        "disclosure_level": "point_and_range",
                        "confidence_level": "medium",
                    },
                    "current_market_pressure": {
                        "scenario_kind": "current_market",
                        "market_pressure_score": 43.0,
                        "market_pressure_level": "L1_中性偏紧",
                    },
                    "scenario_comparison": [
                        {"scenario_kind": "historical_replay", "label": "历史回测", "pressure": None, "recipe_result": {}},
                        {"scenario_kind": "current_market", "label": "当前市场延续", "pressure": {"market_pressure_level": "L1_中性偏紧"}, "recipe_result": {}},
                        {"scenario_kind": "deteriorated_mild", "label": "若市场轻度恶化", "pressure": {"market_pressure_level": "L2_风险偏高"}, "recipe_result": {}},
                        {"scenario_kind": "deteriorated_moderate", "label": "若市场中度恶化", "pressure": {"market_pressure_level": "L2_风险偏高"}, "recipe_result": {}},
                        {"scenario_kind": "deteriorated_severe", "label": "若市场重度恶化", "pressure": {"market_pressure_level": "L3_高压"}, "recipe_result": {}},
                    ],
                },
            },
        },
    )

    assert summary["current_market_pressure"]["market_pressure_level"] == "L1_中性偏紧"
    assert [item["scenario_kind"] for item in summary["scenario_comparison"]] == [
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    ]
    assert [item["label"] for item in summary["scenario_ladder"]] == [
        "历史回测",
        "当前市场延续",
        "若市场轻度恶化",
        "若市场中度恶化",
        "若市场重度恶化",
    ]


@pytest.mark.contract
def test_frontdesk_summary_surfaces_recommendation_expansion_facts_from_execution_plan_summary() -> None:
    execution_plan_summary = _build_execution_plan_summary(
        {
            "plan_id": "plan_progressive",
            "plan_version": 1,
            "source_run_id": "run_progressive",
            "source_allocation_id": "compact_primary",
            "status": "draft",
            "search_expansion_level": "L0_compact",
            "recommendation_expansion": {
                "requested_search_expansion_level": "L1_expanded",
                "why_this_level_was_run": "user_requested_deeper_search",
                "why_search_stopped": "",
                "new_product_ids_added": [" equity_l1 ", "equity_l1", "", "gold_l1"],
                "products_removed": ["equity_l0", "equity_l0", ""],
                "expanded_alternatives": [
                    {
                        "recommendation_kind": "same_allocation_search_expansion",
                        "allocation_name": "compact_primary",
                        "search_expansion_level": "L1_expanded",
                        "difference_basis": {
                            "comparison_scope": "same_allocation_search_expansion",
                            "reference_allocation_name": "compact_primary",
                            "reference_search_expansion_level": "L0_compact",
                        },
                        "selected_product_ids": [" equity_l1 ", "equity_l1", "", "gold_l1"],
                        "new_product_ids_added": [" equity_l1 ", "equity_l1", "", "gold_l1"],
                        "products_removed": ["equity_l0", "equity_l0", ""],
                        "recommended_result": {"allocation_name": "compact_primary"},
                        "recommended_allocation": {"weights": {"equity_cn": 0.55}},
                    },
                    {},
                ],
            },
            "items": [],
        }
    )
    canonical_recommendation_expansion = execution_plan_summary["recommendation_expansion"]
    summary = _frontdesk_summary(
        account_profile_id="recommendation_expansion_frontdesk",
        display_name="Andy",
        db_path=Path("/tmp/recommendation_expansion_frontdesk.sqlite"),
        result_payload={
            "run_id": "run_recommendation_expansion_frontdesk",
            "workflow_type": "onboarding",
            "status": "completed",
            "run_outcome_status": "completed",
            "resolved_result_category": "formal_independent_result",
            "decision_card": {
                "execution_plan_summary": execution_plan_summary
            },
        },
    )

    expected_view = {
        "search_expansion_level": "L0_compact",
        "requested_search_expansion_level": "L1_expanded",
        "why_this_level_was_run": "user_requested_deeper_search",
        "why_search_stopped": None,
        "new_product_ids_added": ["equity_l1", "gold_l1"],
        "products_removed": ["equity_l0"],
        "expanded_alternatives": [
            {
                "recommendation_kind": "same_allocation_search_expansion",
                "allocation_name": "compact_primary",
                "search_expansion_level": "L1_expanded",
                "difference_basis": {
                    "comparison_scope": "same_allocation_search_expansion",
                    "reference_allocation_name": "compact_primary",
                    "reference_search_expansion_level": "L0_compact",
                },
                "selected_product_ids": ["equity_l1", "gold_l1"],
                "new_product_ids_added": ["equity_l1", "gold_l1"],
                "products_removed": ["equity_l0"],
            }
        ],
    }

    assert summary["recommendation_expansion_view"] == expected_view
    assert summary["decision_card"]["recommendation_expansion_view"] == expected_view
    assert summary["decision_card"]["execution_plan_summary"]["recommendation_expansion"] == canonical_recommendation_expansion
    assert "recommendation_expansion_view" not in summary["decision_card"]["execution_plan_summary"]


@pytest.mark.contract
def test_frontdesk_onboarding_enforces_formal_execution_policy(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def _fake_run_orchestrator(*, trigger, raw_inputs, prior_solver_output=None, prior_solver_input=None):  # type: ignore[no-untyped-def]
        captured["trigger"] = trigger
        captured["raw_inputs"] = dict(raw_inputs)
        return run_orchestrator(
            trigger=trigger,
            raw_inputs=raw_inputs,
            prior_solver_output=prior_solver_output,
            prior_solver_input=prior_solver_input,
        )

    monkeypatch.setattr("frontdesk.service.run_orchestrator", _fake_run_orchestrator)

    profile = _profile(account_profile_id="formal_policy_user")
    summary = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk.sqlite")

    assert summary["run_outcome_status"] in {"completed", "degraded", "blocked"}
    assert captured["raw_inputs"]["formal_path_required"] is True
    assert captured["raw_inputs"]["execution_policy"] == "formal_estimation_allowed"


@pytest.mark.contract
def test_frontdesk_persists_user_portfolio_evaluation_state(monkeypatch, tmp_path):
    profile = _profile(account_profile_id="persisted_user_portfolio")
    user_portfolio = [
        {"product_id": "cn_equity_csi300_etf", "target_weight": 0.35},
        {"product_id": "cn_gold_etf", "target_weight": 0.15},
        {"product_id": "cn_cash_money_fund", "target_weight": 0.50},
    ]

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _user_portfolio_bundle(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-03-30T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    summary = run_frontdesk_onboarding(profile, db_path=tmp_path / "persisted_user_portfolio.sqlite")

    assert summary["evaluation_mode"] == "user_specified_portfolio"
    assert summary["requested_structure_visibility"]["requested_structure"] == user_portfolio
    assert summary["requested_structure_result"]["requested_structure"] == user_portfolio
    assert summary["requested_structure_result"]["requested_structure_visibility"]["requested_structure"] == user_portfolio
    assert summary["system_suggested_alternative"] is not None
    if summary["system_suggested_alternative"].get("status") in {"not_generated", "unavailable"}:
        assert summary["system_suggested_alternative"]["status"] in {"not_generated", "unavailable"}
    else:
        assert summary["system_suggested_alternative"]["items"][0]["primary_product_id"] == "cn_equity_csi300_etf"
    assert [item["primary_product_id"] for item in summary["pending_execution_plan"]["items"]] == [
        "cn_equity_csi300_etf",
        "cn_gold_etf",
        "cn_cash_money_fund",
    ]
    assert [item["target_weight"] for item in summary["pending_execution_plan"]["items"]] == [
        0.35,
        0.15,
        0.50,
    ]
    assert summary["user_state"]["latest_result"]["evaluation_mode"] == "user_specified_portfolio"
    assert summary["user_state"]["latest_result"]["requested_structure_visibility"]["rewrite_applied"] is False
    assert summary["user_state"]["latest_result"]["unknown_product_resolution"]["state"] == "recognized"
    assert summary["decision_card"]["requested_structure_result"]["requested_structure"] == user_portfolio
    assert summary["decision_card"]["execution_plan_summary"]["requested_structure_result"]["requested_structure"] == user_portfolio
    assert summary["decision_card"]["system_suggested_alternative"] is not None
    if summary["decision_card"]["system_suggested_alternative"].get("status") in {"not_generated", "unavailable"}:
        assert summary["decision_card"]["system_suggested_alternative"]["status"] in {"not_generated", "unavailable"}
    else:
        assert summary["decision_card"]["system_suggested_alternative"]["items"][0]["primary_product_id"] == "cn_equity_csi300_etf"
    assert summary["decision_card"]["execution_plan_summary"]["system_suggested_alternative"]["status"] in {
        "not_generated",
        "unavailable",
        "available",
    }
    assert summary["decision_card"]["bucket_construction_explanations"] == summary["bucket_construction_explanations"]
    assert summary["decision_card"]["execution_plan_summary"]["bucket_construction_explanations"] == summary[
        "bucket_construction_explanations"
    ]


@pytest.mark.contract
def test_frontdesk_summary_uses_market_facing_product_labels_for_pending_items() -> None:
    from frontdesk.service import _frontdesk_summary

    summary = _frontdesk_summary(
        account_profile_id="market_label_frontdesk",
        display_name="Andy",
        db_path=Path("/tmp/market_label_frontdesk.sqlite"),
        result_payload={
            "evaluation_mode": "user_specified_portfolio",
            "requested_structure": [
                {"product_id": "cn_equity_dividend_etf", "target_weight": 1.0}
            ],
            "requested_structure_visibility": {
                "requested_structure": [
                    {"product_id": "cn_equity_dividend_etf", "target_weight": 1.0}
                ]
            },
            "unknown_product_resolution": {"state": "recognized"},
        },
        user_state={
            "pending_execution_plan": {
                "items": [
                    {
                        "primary_product_id": "cn_equity_dividend_etf",
                        "primary_product": {
                            "product_id": "cn_equity_dividend_etf",
                            "product_name": "红利ETF",
                            "provider_symbol": "510880",
                            "wrapper_type": "etf",
                        },
                    }
                ]
            }
        },
    )

    assert (
        summary["pending_execution_plan"]["items"][0]["primary_product"]["display_label"]
        == "红利ETF (510880, 场内ETF)"
    )
    assert (
        summary["requested_structure_result"]["items"][0]["primary_product"]["display_label"]
        == "红利ETF (510880, 场内ETF)"
    )


@pytest.mark.contract
def test_frontdesk_repeated_onboarding_and_monthly_keep_history(tmp_path):
    profile = _profile(account_profile_id="history_user")
    db_path = tmp_path / "frontdesk.sqlite"

    first_onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    second_onboarding = run_frontdesk_onboarding(profile, db_path=db_path)

    assert first_onboarding["status"] == "blocked"
    assert second_onboarding["status"] == "blocked"
    assert first_onboarding["formal_path_visibility"]["status"] == "blocked"
    assert second_onboarding["formal_path_visibility"]["status"] == "blocked"

    with pytest.raises(ValueError, match="no saved onboarding baseline"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
        )


@pytest.mark.parametrize(
    ("status", "expected_baseline_count"),
    [
        ("blocked", 0),
        ("degraded", 1),
    ],
)
@pytest.mark.contract
def test_frontdesk_blocked_or_partial_onboarding_baseline_gate(tmp_path, status, expected_baseline_count):
    profile = _profile(account_profile_id=f"{status}_user")
    db_path = tmp_path / f"{status}.sqlite"
    store = FrontdeskStore(db_path)
    store.initialize()

    bundle = build_user_onboarding_inputs(profile, as_of="2026-03-30T00:00:00Z")
    run_id = f"{profile.account_profile_id}_{status}"
    decision_card = {
        "card_type": "blocked" if status == "blocked" else "runtime_action",
        "status_badge": status,
        "summary": f"{status} onboarding",
        "recommended_action": "" if status == "blocked" else "review",
        "formal_path_visibility": {
            "status": status,
            "execution_eligible": False,
        },
    }
    result_payload: dict[str, object] = {
        "run_id": run_id,
        "workflow_type": "onboarding",
        "status": status,
        "decision_card": decision_card,
    }
    if status != "blocked":
        result_payload["goal_solver_output"] = {"generated_at": "2026-03-30T00:00:00Z"}
        result_payload["persistence_plan"] = {
            "artifact_records": {
                "execution_plan": {
                    "plan_id": f"{profile.account_profile_id}_plan",
                    "plan_version": 1,
                    "source_run_id": run_id,
                    "source_allocation_id": f"{profile.account_profile_id}_allocation",
                    "status": "draft",
                    "confirmation_required": True,
                    "payload": {
                        "plan_id": f"{profile.account_profile_id}_plan",
                        "plan_version": 1,
                        "source_run_id": run_id,
                        "source_allocation_id": f"{profile.account_profile_id}_allocation",
                        "status": "draft",
                        "confirmation_required": True,
                    },
                }
            }
        }

    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=result_payload,
        input_provenance=bundle.input_provenance,
    )

    with store.connect() as conn:
        baseline_count = conn.execute(
            "select count(*) from frontdesk_baselines where account_profile_id = ?",
            (profile.account_profile_id,),
        ).fetchone()[0]

    assert baseline_count == expected_baseline_count
    if expected_baseline_count == 0:
        assert store.get_latest_baseline(profile.account_profile_id) is None
    else:
        assert store.get_latest_baseline(profile.account_profile_id) is not None


@pytest.mark.contract
def test_frontdesk_followup_persists_decision_card_and_provenance(tmp_path):
    profile = _profile(account_profile_id="followup_user")
    db_path = tmp_path / "frontdesk.sqlite"

    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    store = FrontdeskStore(db_path)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    assert onboarding_summary["status"] == "blocked"
    assert onboarding_summary["formal_path_visibility"]["status"] == "blocked"
    assert snapshot is not None
    latest_run = snapshot["latest_run"]
    latest_decision_card = latest_run["decision_card"]
    serialized = json.dumps(latest_decision_card, ensure_ascii=False, sort_keys=True)

    assert latest_run["workflow_type"] == "onboarding"
    assert latest_decision_card["card_type"] == "blocked"
    assert latest_decision_card["formal_path_visibility"]["status"] == "blocked"
    assert latest_decision_card["input_provenance"]["counts"]["default_assumed"] >= 1
    assert "默认假设" in serialized

    with pytest.raises(ValueError, match="no saved onboarding baseline"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
        )


@pytest.mark.contract
def test_frontdesk_onboarding_surfaces_product_aware_probability_and_expanded_frontier(tmp_path):
    profile = _profile(account_profile_id="frontier_layer1_user")
    profile.current_total_assets = 18_000.0
    profile.monthly_contribution = 2_500.0
    profile.goal_amount = 124_203.16
    profile.goal_horizon_months = 36
    profile.max_drawdown_tolerance = 0.20
    profile.current_holdings = ""
    profile.current_weights = None
    db_path = tmp_path / "frontier_layer1.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    card = summary["user_state"]["decision_card"]
    frontier = card["frontier_analysis"]

    assert summary["status"] == "blocked"
    assert card["formal_path_visibility"]["status"] == "blocked"
    assert frontier.get("frontier_diagnostics") is None


@pytest.mark.contract
def test_frontdesk_onboarding_target_annual_return_keeps_required_return_non_negative(tmp_path):
    profile = _profile(account_profile_id="annual_target_layer1_user")
    profile.current_total_assets = 18_000.0
    profile.monthly_contribution = 2_500.0
    profile.goal_amount = 0.0
    profile.goal_horizon_months = 36
    profile.target_annual_return = 0.08
    profile.max_drawdown_tolerance = 0.20
    profile.current_holdings = ""
    profile.current_weights = None
    db_path = tmp_path / "frontdesk_annual_target.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    card = summary["user_state"]["decision_card"]

    assert summary["status"] == "blocked"
    assert card["formal_path_visibility"]["status"] == "blocked"
    assert card["frontier_analysis"].get("frontier_diagnostics") is None


@pytest.mark.contract
def test_frontdesk_external_snapshot_without_audit_window_is_non_formal(tmp_path):
    profile = _profile(account_profile_id="formal_path_external")
    db_path = tmp_path / "frontdesk.sqlite"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "market_raw": {
                    "expected_returns": {
                        "equity_cn": 0.08,
                        "bond_cn": 0.03,
                        "gold": 0.04,
                        "satellite": 0.10,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=snapshot_path,
    )

    visibility = summary["formal_path_visibility"]
    assert summary["status"] == "completed"
    assert summary["run_outcome_status"] == "degraded"
    assert summary["resolved_result_category"] == "degraded_formal_result"
    assert summary["disclosure_decision"]["disclosure_level"] == "range_only"
    assert visibility["status"] == "degraded"
    assert visibility["execution_eligible"] is False
    assert "market_raw.audit_window" in visibility["missing_audit_fields"]
    assert summary["user_state"]["formal_path_visibility"]["status"] == "degraded"
    assert any(record["field"] == "market_raw" and record["data_status"] == "observed" for record in summary["audit_records"])


@pytest.mark.contract
def test_frontdesk_onboarding_surfaces_layer1_product_aware_frontier_fields(tmp_path):
    profile = _profile(account_profile_id="layer1_frontier_user")
    profile.current_total_assets = 18_000.0
    profile.monthly_contribution = 2_500.0
    profile.goal_amount = 124_203.16
    profile.goal_horizon_months = 36
    profile.max_drawdown_tolerance = 0.20
    profile.goal_priority = "aspirational"
    profile.current_holdings = "cash, gold"
    profile.current_weights = None
    profile.restrictions = ["no_stock_picking", "no_high_risk_products"]
    profile.forbidden_themes = ["technology"]
    db_path = tmp_path / "layer1.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)

    decision_card = summary["user_state"]["decision_card"]
    key_metrics = decision_card["key_metrics"]
    probability_explanation = decision_card["probability_explanation"]
    frontier = decision_card["frontier_analysis"]
    assert summary["status"] == "blocked"
    assert decision_card["formal_path_visibility"]["status"] == "blocked"
    assert frontier.get("frontier_diagnostics") is None


@pytest.mark.contract
def test_frontdesk_inline_provider_marks_synthetic_demo_non_formal(tmp_path):
    profile = _profile(account_profile_id="formal_path_inline")
    db_path = tmp_path / "frontdesk.sqlite"

    summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_data_config={
            "adapter": "inline_snapshot",
            "provider_name": "inline_acceptance",
            "payload": {
                "market_raw": {
                    "expected_returns": {
                        "equity_cn": 0.08,
                        "bond_cn": 0.03,
                        "gold": 0.04,
                        "satellite": 0.10,
                    }
                }
            },
        },
    )

    visibility = summary["formal_path_visibility"]
    assert summary["status"] == "completed"
    assert summary["run_outcome_status"] == "degraded"
    assert summary["resolved_result_category"] == "degraded_formal_result"
    assert summary["disclosure_decision"]["disclosure_level"] == "range_only"
    assert visibility["status"] == "degraded"
    assert visibility["execution_eligible"] is False
    assert any("market_raw is backed by non-formal data_status=synthetic_demo" in reason for reason in visibility["reasons"])


@pytest.mark.contract
def test_frontdesk_execution_feedback_roundtrip_updates_snapshot(tmp_path):
    profile = _profile(account_profile_id="feedback_user")
    db_path = tmp_path / "frontdesk.sqlite"

    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    source_run_id = onboarding_summary["run_id"]

    store = FrontdeskStore(db_path)
    updated = store.record_execution_feedback(
        account_profile_id=profile.account_profile_id,
        source_run_id=source_run_id,
        user_executed=True,
        actual_action="rebalance_partial",
        executed_at="2026-03-31T08:00:00Z",
        note="执行了部分调仓",
        recorded_at="2026-03-31T08:30:00Z",
    )
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    user_state = store.load_user_state(profile.account_profile_id)

    assert updated.feedback_status == "executed"
    assert snapshot["execution_feedback"]["source_run_id"] == source_run_id
    assert snapshot["execution_feedback"]["actual_action"] == "rebalance_partial"
    assert snapshot["execution_feedback_summary"]["counts"]["executed"] == 1
    assert user_state["execution_feedback"]["note"] == "执行了部分调仓"


@pytest.mark.contract
def test_frontdesk_execution_feedback_requires_seeded_run(tmp_path):
    profile = _profile(account_profile_id="feedback_missing_seed")
    db_path = tmp_path / "frontdesk.sqlite"

    run_frontdesk_onboarding(profile, db_path=db_path)
    store = FrontdeskStore(db_path)

    with pytest.raises(ValueError, match="no execution feedback seed"):
        store.record_execution_feedback(
            account_profile_id=profile.account_profile_id,
            source_run_id="missing_run_id",
            user_executed=False,
            note="未执行",
            recorded_at="2026-03-31T09:00:00Z",
        )


@pytest.mark.contract
def test_frontdesk_approve_execution_plan_promotes_pending_and_supersedes_previous_active(tmp_path):
    profile = _profile(account_profile_id="approve_plan_user")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] == "blocked"
    assert onboarding_summary["formal_path_visibility"]["status"] == "blocked"
    assert onboarding_summary["user_state"]["pending_execution_plan"] is None

    store = FrontdeskStore(db_path)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    assert snapshot is not None
    assert snapshot["pending_execution_plan"] is None
    assert snapshot["active_execution_plan"] is None


@pytest.mark.contract
def test_frontdesk_execution_plan_comparison_distinguishes_split_bucket_members() -> None:
    active = FrontdeskExecutionPlanRecord(
        account_profile_id="comparison_user",
        plan_id="active_plan",
        plan_version=1,
        source_run_id="run_active",
        source_allocation_id="alloc_active",
        status="approved",
        confirmation_required=True,
        payload={
            "items": [
                {
                    "asset_bucket": "equity_cn",
                    "primary_product_id": "cn_equity_csi300_etf",
                    "target_weight": 0.20,
                },
                {
                    "asset_bucket": "equity_cn",
                    "primary_product_id": "cn_equity_dividend_etf",
                    "target_weight": 0.20,
                },
            ]
        },
        approved_at=None,
        superseded_by_plan_id=None,
        created_at="2026-04-13T00:00:00Z",
        updated_at="2026-04-13T00:00:00Z",
    )
    pending = FrontdeskExecutionPlanRecord(
        account_profile_id="comparison_user",
        plan_id="pending_plan",
        plan_version=1,
        source_run_id="run_pending",
        source_allocation_id="alloc_pending",
        status="draft",
        confirmation_required=True,
        payload={
            "items": [
                {
                    "asset_bucket": "equity_cn",
                    "primary_product_id": "cn_equity_dividend_etf",
                    "target_weight": 0.20,
                },
                {
                    "asset_bucket": "equity_cn",
                    "primary_product_id": "cn_equity_low_vol_fund",
                    "target_weight": 0.20,
                },
            ]
        },
        approved_at=None,
        superseded_by_plan_id=None,
        created_at="2026-04-13T00:00:00Z",
        updated_at="2026-04-13T00:00:00Z",
    )

    comparison = _compare_execution_plans(active, pending)

    assert comparison is not None
    assert comparison["changed_bucket_count"] == 2
    assert {item["item_key"] for item in comparison["bucket_changes"]} == {
        "equity_cn::cn_equity_csi300_etf",
        "equity_cn::cn_equity_low_vol_fund",
    }


@pytest.mark.contract
def test_frontdesk_snapshot_surfaces_execution_plan_comparison_for_pending_vs_active(tmp_path):
    profile = _profile(account_profile_id="plan_diff_user")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] == "blocked"
    assert onboarding_summary["formal_path_visibility"]["status"] == "blocked"
    assert onboarding_summary["user_state"]["pending_execution_plan"] is None

    snapshot = FrontdeskStore(db_path).get_frontdesk_snapshot(profile.account_profile_id)
    assert snapshot is not None
    assert snapshot["pending_execution_plan"] is None
    assert snapshot["active_execution_plan"] is None


@pytest.mark.parametrize("workflow_type", ["monthly", "quarterly"])
@pytest.mark.contract
def test_followup_decision_card_promotes_plan_comparison_guidance_into_next_steps(tmp_path, workflow_type):
    profile = _profile(account_profile_id=f"{workflow_type}_plan_guidance")
    db_path = tmp_path / f"{workflow_type}.sqlite"
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] == "blocked"
    assert onboarding_summary["formal_path_visibility"]["status"] == "blocked"
    assert onboarding_summary["user_state"]["pending_execution_plan"] is None

    updated_profile = profile.to_dict()
    updated_profile["current_weights"] = {
        "equity_cn": 0.15,
        "bond_cn": 0.55,
        "gold": 0.20,
        "satellite": 0.10,
    }

    with pytest.raises(ValueError, match="no saved onboarding baseline"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type=workflow_type,
            profile=updated_profile,
            db_path=db_path,
        )


@pytest.mark.contract
def test_frontdesk_monthly_rejects_goal_profile_updates(tmp_path):
    profile = _profile(account_profile_id="goal_change_user")
    db_path = tmp_path / "frontdesk.sqlite"
    run_frontdesk_onboarding(profile, db_path=db_path)

    updated_profile = profile.to_dict()
    updated_profile["goal_amount"] = 1_200_000.0

    with pytest.raises(ValueError, match="no saved onboarding baseline"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
            profile=updated_profile,
        )
