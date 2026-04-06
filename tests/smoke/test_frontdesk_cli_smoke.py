from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_andy",
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=[],
    )


@pytest.mark.smoke
def test_frontdesk_cli_non_interactive_onboarding_smoke(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["workflow"] == "onboard"
    assert payload["status"] == "completed"
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    assert payload["user_state"]["decision_card"]["card_type"] == "goal_baseline"
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1


@pytest.mark.smoke
def test_frontdesk_cli_accepts_inline_profile_json(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["plan_id"]
        == payload["user_state"]["pending_execution_plan"]["plan_id"]
    )


@pytest.mark.smoke
def test_frontdesk_cli_status_reads_existing_state(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    first_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()
    assert first_exit_code == 0

    status_exit_code = main(
        [
            "status",
            "--db",
            str(db_path),
            "--user-id",
            profile.account_profile_id,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert status_exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    serialized = json.dumps(payload["user_state"], ensure_ascii=False, sort_keys=True)
    for label in ("用户提供", "系统推断", "默认假设", "外部抓取"):
        assert label in serialized


@pytest.mark.smoke
def test_frontdesk_cli_text_summary_surfaces_readable_candidates_and_disclaimer(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "onboarding",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "candidate_1=" in output
    assert "bucket_success=" in output
    assert "product_success=" in output
    assert "required_return=" in output
    assert "expected_return=" in output
    assert "input_sources=" in output
    assert "model_disclaimer=" in output
    assert "probability_recommended=" in output
    assert "frontier_raw_candidate_count=" in output
    assert "goal_semantics:" in output
    assert "profile_model:" in output
    assert "refresh:" in output
    assert "pending_execution_plan:" in output
    assert "pending_execution_plan_proxy_mode=" in output
    assert "pending_execution_plan_proxy_covered_buckets=" in output
    assert "execution_feedback:" in output


@pytest.mark.smoke
def test_frontdesk_cli_approve_plan_promotes_pending_execution_plan(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert onboard_exit == 0
    assert approve_exit == 0
    assert payload["workflow"] == "approve_plan"
    assert payload["status"] == "approved"
    assert payload["approved_execution_plan"]["plan_id"] == pending_plan["plan_id"]
    assert payload["user_state"]["active_execution_plan"]["status"] == "approved"
    assert payload["user_state"]["pending_execution_plan"] is None


@pytest.mark.smoke
def test_frontdesk_cli_show_user_surfaces_execution_plan_comparison(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    capsys.readouterr()

    updated_profile = profile.to_dict()
    updated_profile["restrictions"] = ["不碰股票"]
    second_onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(updated_profile, ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()

    show_user_exit = main(
        [
            "show-user",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
        ]
    )
    output = capsys.readouterr().out

    assert onboard_exit == 0
    assert approve_exit == 0
    assert second_onboard_exit == 0
    assert show_user_exit == 0
    assert "execution_plan_comparison:" in output
    assert "recommendation=keep_active" in output
    assert "runtime_candidates=" in output
    assert "candidate_filter_drop_reasons=" in output
    assert "wrapper:stock" in output


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_degraded_scope_and_execution_eligibility():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "workflow": "onboard",
            "status": "completed",
            "refresh_summary": {
                "external_status": "fallback",
                "freshness_state": "fallback",
                "domain_details": [
                    {"domain": "market", "freshness_state": "fallback", "source_label": "外部抓取"},
                ],
            },
            "user_state": {
                "profile": {
                    "account_profile_id": "formal_path_user",
                    "display_name": "Andy",
                },
                "decision_card": {
                    "card_type": "goal_baseline",
                    "status_badge": "degraded",
                    "summary": "下面先展示临时参考，不应当作正式推荐。",
                    "primary_recommendation": "流动性缓冲方案",
                    "recommended_action": "adopt_recommended_plan",
                    "guardrails": ["calibration_quality=partial", "candidate_poverty=true"],
                    "recommendation_reason": [
                        "当前不存在满足你回撤约束的配置。",
                        "下面展示的是最接近可行的临时参考，不是正式推荐。",
                    ],
                    "execution_notes": ["manual_review_required"],
                    "input_provenance": {},
                },
            },
        }
    )

    assert "formal_path:" in output
    assert "degraded_scope=" in output
    assert "calibration" in output
    assert "market" in output
    assert "runtime_candidates" in output
    assert "fallback_used=true" in output
    assert "fallback_scope=" in output
    assert "external_snapshot" in output
    assert "goal_solver" in output
    assert "execution_eligible=false" in output


@pytest.mark.smoke
def test_frontdesk_cli_json_surfaces_formal_path_visibility(tmp_path, capsys, monkeypatch):
    from frontdesk import cli

    db_path = tmp_path / "frontdesk.sqlite"

    monkeypatch.setattr(
        cli,
        "run_frontdesk_onboarding",
        lambda *args, **kwargs: {
            "status": "completed",
            "run_id": "run_formal_path_cli",
            "user_state": {
                "profile": {"account_profile_id": "andy_cli", "display_name": "Andy"},
                "decision_card": {
                    "card_type": "goal_baseline",
                    "status_badge": "degraded",
                    "summary": "下面先展示临时参考，不应当作正式推荐。",
                    "primary_recommendation": "流动性缓冲方案",
                    "recommended_action": "adopt_recommended_plan",
                    "guardrails": ["bundle_quality=partial"],
                    "recommendation_reason": ["下面展示的是最接近可行的临时参考，不是正式推荐。"],
                    "input_provenance": {},
                },
            },
            "refresh_summary": {
                "external_status": "fallback",
                "freshness_state": "fallback",
                "domain_details": [{"domain": "market", "freshness_state": "fallback"}],
            },
            "external_snapshot_status": "fallback",
        },
    )

    exit_code = cli.main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(_profile().to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["formal_path_visibility"]["fallback_used"] is True
    assert payload["formal_path_visibility"]["execution_eligible"] is False
    assert payload["user_state"]["formal_path_visibility"]["degraded_scope"] == ["bundle", "market"]


@pytest.mark.smoke
def test_frontdesk_cli_json_preserves_policy_news_audit_summary(tmp_path, capsys, monkeypatch):
    from frontdesk import cli

    db_path = tmp_path / "frontdesk.sqlite"

    monkeypatch.setattr(
        cli,
        "run_frontdesk_onboarding",
        lambda *args, **kwargs: {
            "status": "completed",
            "run_id": "run_policy_news_cli",
            "decision_card": {
                "card_type": "goal_baseline",
                "execution_plan_summary": {
                    "plan_id": "plan_policy_news",
                    "policy_news_audit_summary": {
                        "source_status": "observed",
                        "realtime_eligible": True,
                        "matched_signal_count": 2,
                        "latest_published_at": "2026-04-04T12:00:00Z",
                    },
                },
            },
            "user_state": {
                "profile": {"account_profile_id": "andy_cli", "display_name": "Andy"},
                "decision_card": {
                    "card_type": "goal_baseline",
                    "execution_plan_summary": {
                        "plan_id": "plan_policy_news",
                        "policy_news_audit_summary": {
                            "source_status": "observed",
                            "realtime_eligible": True,
                            "matched_signal_count": 2,
                        },
                    },
                },
            },
        },
    )

    exit_code = cli.main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(_profile().to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["policy_news_audit_summary"]["source_status"]
        == "observed"
    )
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["policy_news_audit_summary"][
            "realtime_eligible"
        ]
        is True
    )


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_execution_plan_valuation_audit():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "workflow": "status",
            "status": "loaded",
            "user_state": {
                "profile": {
                    "account_profile_id": "valuation_audit_user",
                    "display_name": "Andy",
                },
                "decision_card": {
                    "card_type": "goal_baseline",
                    "summary": "估值筛选已进入产品层。",
                    "primary_recommendation": "防守优先方案",
                    "recommended_action": "review",
                    "input_provenance": {},
                },
                "pending_execution_plan": {
                    "plan_id": "run_val:allocation_val",
                    "plan_version": 1,
                    "status": "draft",
                    "item_count": 2,
                    "confirmation_required": True,
                    "runtime_candidate_count": 4,
                    "registry_candidate_count": 8,
                    "candidate_filter_dropped_reasons": {
                        "valuation:pe_above_40": 1,
                        "valuation:percentile_above_0.30": 1,
                    },
                    "valuation_audit_summary": {
                        "source_status": "observed",
                        "source_name": "akshare_dynamic_valuation",
                        "rule_max_pe": 40.0,
                        "rule_max_percentile": 0.30,
                        "applicable_candidate_count": 3,
                        "passed_candidate_count": 1,
                    },
                },
            },
        }
    )

    assert "pending_execution_plan_candidate_filter_drop_reasons=" in output
    assert "valuation:pe_above_40" in output
    assert "pending_execution_plan_valuation_audit=" in output
    assert "akshare_dynamic_valuation" in output


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_layer1_probability_and_frontier_fields():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "account_profile_id": "layer1_frontdesk_user",
            "display_name": "Andy",
            "workflow_type": "onboarding",
            "status": "completed",
            "decision_card": {
                "card_type": "goal_baseline",
                "summary": "Layer 1 probability summary",
                "primary_recommendation": "平衡推进方案",
                "recommended_action": "adopt_recommended_plan",
                "probability_explanation": {
                    "recommended_allocation_label": "平衡推进方案",
                    "recommended_success_probability": "65.00%",
                    "recommended_expected_annual_return": "6.10%",
                    "highest_probability_allocation_label": "冲目标方案",
                    "highest_probability_success_probability": "70.00%",
                    "highest_probability_expected_annual_return": "7.90%",
                    "target_return_priority_allocation_label": "",
                    "target_return_priority_success_probability": "",
                    "target_return_priority_expected_annual_return": "",
                    "drawdown_priority_allocation_label": "平衡推进方案",
                    "drawdown_priority_success_probability": "65.00%",
                    "drawdown_priority_expected_annual_return": "6.10%",
                    "implied_required_annual_return": "8.00%",
                    "product_probability_method": "product_proxy_adjustment_estimate",
                    "product_probability_disclosure": "当前产品层概率使用代理修正口径，仍不是逐产品独立模拟。",
                    "why_not_target_return_priority": "no_candidate_meets_required_annual_return",
                    "difficulty_source": "constraint_binding",
                    "evidence_layer": {
                        "formal_path_status": "formal",
                        "observed_ratio": 0.82,
                        "observed_product_count": 6,
                        "product_universe_source_status": "observed",
                        "valuation_source_status": "observed",
                        "policy_news_source_status": "observed",
                    },
                    "constraint_contributions": [
                        {"constraint_name": "required_annual_return", "is_binding": True, "impact_direction": "down"}
                    ],
                    "counterfactuals": {
                        "required_return_gap": 0.019,
                        "fallback_scenarios": [
                            {"scenario": "reduce_target", "expected_delta_success_probability": 0.08}
                        ],
                    },
                    "product_contributions": [
                        {"product_id": "cn_equity_dividend_etf", "contribution_direction": "positive"},
                        {"product_id": "cn_satellite_energy_etf", "contribution_direction": "negative"},
                    ],
                },
                "frontier_analysis": {
                    "frontier_diagnostics": {
                        "raw_candidate_count": 4,
                        "feasible_candidate_count": 3,
                        "frontier_max_expected_annual_return": 0.079,
                        "candidate_families": ["balanced_core", "growth_tilt", "max_return_unconstrained"],
                        "binding_constraints": [
                            {"constraint_name": "required_annual_return", "reason": "no_candidate_meets_required_annual_return"}
                        ],
                        "structural_limitations": ["expected_return_shrinkage_applied"],
                    }
                },
                "input_provenance": {},
            },
            "key_metrics": {
                "success_probability": "65.00%",
                "product_proxy_adjusted_success_probability": "65.00%",
                "product_probability_method": "product_proxy_adjustment_estimate",
                "implied_required_annual_return": "8.00%",
                "expected_annual_return": "6.10%",
            },
            "input_provenance": {},
            "refresh_summary": {},
            "candidate_options": [],
            "goal_alternatives": [],
            "formal_path_visibility": {},
        }
    )

    assert "expected_annual_return=6.10%" in output
    assert "probability_recommended=平衡推进方案 | success=65.00% | expected_return=6.10%" in output
    assert "probability_highest=冲目标方案 | success=70.00% | expected_return=7.90%" in output
    assert "probability_target_return=unavailable | reason=no_candidate_meets_required_annual_return | required_return=8.00%" in output
    assert "probability_drawdown=平衡推进方案 | success=65.00% | expected_return=6.10%" in output
    assert "probability_difficulty_source=constraint_binding" in output
    assert "probability_method_disclosure=当前产品层概率使用代理修正口径，仍不是逐产品独立模拟。" in output
    assert "probability_evidence_formal_path_status=formal" in output
    assert "probability_evidence_observed_ratio=0.82" in output
    assert "probability_constraint_contributions=[{'constraint_name': 'required_annual_return', 'is_binding': True, 'impact_direction': 'down'}]" in output
    assert "probability_counterfactuals=[{'scenario': 'reduce_target', 'expected_delta_success_probability': 0.08}]" in output
    assert "probability_product_contributions=['cn_equity_dividend_etf:positive', 'cn_satellite_energy_etf:negative']" in output
    assert "frontier_raw_candidate_count=4" in output
    assert "frontier_candidate_families=['balanced_core', 'growth_tilt', 'max_return_unconstrained']" in output
    assert "frontier_binding_constraints=[{'constraint_name': 'required_annual_return', 'reason': 'no_candidate_meets_required_annual_return'}]" in output


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_execution_realism_fields():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "workflow": "status",
            "status": "loaded",
            "user_state": {
                "profile": {
                    "account_profile_id": "execution_realism_user",
                    "display_name": "Andy",
                },
                "decision_card": {
                    "card_type": "goal_baseline",
                    "summary": "执行计划已生成。",
                    "primary_recommendation": "防守优先方案",
                    "recommended_action": "review",
                    "input_provenance": {},
                },
                "pending_execution_plan": {
                    "plan_id": "run_exec:allocation_exec",
                    "plan_version": 1,
                    "status": "draft",
                    "item_count": 4,
                    "confirmation_required": True,
                    "runtime_candidate_count": 8,
                    "product_proxy_specs": [
                        {
                            "product_id": "cn_dividend_etf",
                            "proxy_kind": "listed_fund_price_proxy",
                            "proxy_ref": "akshare:sh510880",
                            "confidence": 0.93,
                            "confidence_data_status": "manual_annotation",
                            "confidence_disclosure": "proxy confidence is a heuristic wrapper-level mapping, not observed market coverage or empirical fit quality.",
                            "source_ref": "akshare:sh510880",
                            "data_status": "manual_annotation",
                        }
                    ],
                    "proxy_universe_summary": {
                        "solving_mode": "proxy_universe",
                        "proxy_scope": "selected_plan_items",
                        "covered_asset_buckets": ["equity_cn"],
                        "uncovered_asset_buckets": [],
                        "product_proxy_count": 1,
                        "runtime_candidate_proxy_count": 8,
                        "data_status": "manual_annotation",
                        "disclosure": "当前仍是代理宇宙求解",
                    },
                    "execution_realism_summary": {
                        "executable": False,
                        "cash_reserve_target_amount": 3500.0,
                        "initial_buy_amount": 11900.0,
                        "initial_sell_amount": 1900.0,
                        "fundable_initial_cash": 10846.0,
                        "minimum_trade_amount": 500.0,
                        "estimated_total_fee": 42.8,
                        "estimated_total_slippage": 11.2,
                        "execution_cost_data_status": "prior_default",
                        "tax_estimate_status": "not_modeled",
                        "tiny_trade_buckets": ["satellite"],
                        "reasons": ["cash_reserve_conflict", "tiny_trade:satellite"],
                    },
                    "maintenance_policy_summary": {
                        "initial_deploy_fraction": 0.40,
                        "drawdown_add_buy_threshold": 0.10,
                        "core_take_profit_threshold": 0.12,
                        "satellite_take_profit_threshold": 0.15,
                        "rebalance_band": 0.10,
                    },
                    "items": [
                        {
                            "asset_bucket": "satellite",
                            "target_weight": 0.10,
                            "target_amount": 2000.0,
                            "primary_product_id": "cn_satellite_energy_etf",
                            "trade_direction": "buy",
                            "initial_trade_amount": 800.0,
                            "deferred_trade_amount": 1200.0,
                            "trigger_conditions": ["若回撤达到10%，按预设分批补仓。"],
                            "valuation_audit": {"status": "observed", "percentile": 0.2},
                            "policy_news_audit": {"status": "observed", "score": 0.45},
                        }
                    ],
                },
            },
        }
    )

    assert "pending_execution_plan_executable=False" in output
    assert "pending_execution_plan_proxy_mode=proxy_universe" in output
    assert "pending_execution_plan_proxy_scope=selected_plan_items" in output
    assert "pending_execution_plan_proxy_selected_product_count=1" in output
    assert "pending_execution_plan_proxy_runtime_candidate_count=8" in output
    assert "pending_execution_plan_proxy_data_status=manual_annotation" in output
    assert "pending_execution_plan_proxy_spec_data_statuses=['manual_annotation']" in output
    assert "pending_execution_plan_proxy_confidence_data_statuses=['manual_annotation']" in output
    assert "pending_execution_plan_cash_reserve_target=3500.0" in output
    assert "pending_execution_plan_initial_buy_amount=11900.0" in output
    assert "pending_execution_plan_initial_sell_amount=1900.0" in output
    assert "pending_execution_plan_fundable_initial_cash=10846.0" in output
    assert "pending_execution_plan_minimum_trade_amount=500.0" in output
    assert "pending_execution_plan_estimated_total_fee=42.8" in output
    assert "pending_execution_plan_estimated_total_slippage=11.2" in output
    assert "pending_execution_plan_execution_cost_data_status=prior_default" in output
    assert "pending_execution_plan_tax_estimate_status=not_modeled" in output
    assert "pending_execution_plan_tiny_trade_buckets=['satellite']" in output
    assert "pending_execution_plan_execution_realism_reasons=['cash_reserve_conflict', 'tiny_trade:satellite']" in output
    assert "pending_execution_plan_maintenance_policy=" in output
    assert "pending_execution_plan_initial_deploy_fraction=0.4" in output
    assert "pending_execution_plan_drawdown_add_buy_threshold=0.1" in output
    assert "pending_execution_plan_core_take_profit_threshold=0.12" in output
    assert "pending_execution_plan_satellite_take_profit_threshold=0.15" in output
    assert "pending_execution_plan_rebalance_band=0.1" in output
    assert "pending_execution_plan_item_1=bucket:satellite, product:cn_satellite_energy_etf" in output
    assert "pending_execution_plan_item_1_trigger_conditions=['若回撤达到10%，按预设分批补仓。']" in output
    assert "pending_execution_plan_item_1_valuation_audit={'status': 'observed', 'percentile': 0.2}" in output
    assert "pending_execution_plan_item_1_policy_news_audit={'status': 'observed', 'score': 0.45}" in output
