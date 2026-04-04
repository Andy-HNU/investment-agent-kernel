from __future__ import annotations

import json


def test_route_intent_supports_explain_data_basis():
    from agent.nli_router import route_intent

    assert route_intent("请解释你用了哪些历史数据、哪些是推算历史") == "explain_data_basis"
    assert route_intent("explain data basis for user shell_user") == "explain_data_basis"
    assert route_intent("explain probability for user shell_user") == "explain_probability"
    assert route_intent("坚持8%年化回撤是多少，用户 shell_user") == "explain_probability"
    assert route_intent("坚持回撤不超过8%收益率能到多少，用户 shell_user") == "explain_probability"


def test_probability_explanation_surfaces_target_risk_tradeoffs():
    from agent.explainability import build_probability_explanation

    snapshot = {
        "latest_baseline": {
            "goal_solver_output": {
                "simulation_mode_requested": "garch_t",
                "simulation_mode_used": "garch_t",
                "recommended_result": {
                    "allocation_name": "balanced_core",
                    "success_probability": 0.55,
                    "product_adjusted_success_probability": 0.52,
                    "implied_required_annual_return": 0.06,
                    "risk_summary": {"max_drawdown_90pct": 0.08},
                },
                "all_results": [
                    {
                        "allocation_name": "balanced_core",
                        "display_name": "平衡核心方案",
                        "success_probability": 0.55,
                        "product_adjusted_success_probability": 0.52,
                        "expected_annual_return": 0.06,
                        "risk_summary": {"max_drawdown_90pct": 0.08},
                    },
                    {
                        "allocation_name": "target_return_priority",
                        "display_name": "收益优先方案",
                        "success_probability": 0.43,
                        "product_adjusted_success_probability": 0.41,
                        "expected_annual_return": 0.08,
                        "risk_summary": {"max_drawdown_90pct": 0.16},
                    },
                    {
                        "allocation_name": "capital_preservation",
                        "display_name": "防守优先方案",
                        "success_probability": 0.60,
                        "product_adjusted_success_probability": 0.58,
                        "expected_annual_return": 0.045,
                        "risk_summary": {"max_drawdown_90pct": 0.05},
                    },
                ],
                "frontier_analysis": {
                    "target_return_priority": {
                        "allocation_name": "target_return_priority",
                        "label": "收益优先方案",
                        "success_probability": 0.41,
                        "product_adjusted_success_probability": 0.41,
                        "expected_annual_return": 0.08,
                        "max_drawdown_90pct": 0.16,
                    },
                    "drawdown_priority": {
                        "allocation_name": "balanced_core",
                        "label": "平衡核心方案",
                        "success_probability": 0.52,
                        "product_adjusted_success_probability": 0.52,
                        "expected_annual_return": 0.06,
                        "max_drawdown_90pct": 0.08,
                    },
                    "scenario_status": {
                        "target_return_priority": {
                            "available": True,
                            "constraint_met": True,
                            "reason": "selected_by_required_annual_return",
                        },
                        "drawdown_priority": {
                            "available": True,
                            "constraint_met": True,
                            "reason": "selected_by_max_drawdown_tolerance",
                        },
                    },
                },
            }
        }
    }

    explanation = build_probability_explanation(
        snapshot,
        requested_annual_return=0.08,
        requested_max_drawdown=0.08,
    )

    assert explanation["implied_required_annual_return"] == 0.06
    assert explanation["target_return_tradeoff"]["requested_annual_return"] == 0.08
    assert explanation["target_return_tradeoff"]["selected_allocation_name"] == "target_return_priority"
    assert explanation["target_return_tradeoff"]["expected_max_drawdown_90pct"] == 0.16
    assert explanation["target_return_tradeoff"]["achievable_expected_annual_return"] == 0.08
    assert explanation["target_return_tradeoff"]["selection_basis"] == "frontier_analysis"
    assert "achievable_implied_annual_return" not in explanation["target_return_tradeoff"]
    assert explanation["drawdown_limit_tradeoff"]["requested_max_drawdown"] == 0.08
    assert explanation["drawdown_limit_tradeoff"]["selected_allocation_name"] == "balanced_core"
    assert explanation["drawdown_limit_tradeoff"]["achievable_expected_annual_return"] == 0.06
    assert explanation["drawdown_limit_tradeoff"]["selection_basis"] == "frontier_analysis"


def test_probability_explanation_surfaces_unavailable_frontier_constraints():
    from agent.explainability import build_probability_explanation

    snapshot = {
        "latest_baseline": {
            "goal_solver_output": {
                "simulation_mode_requested": "garch_t",
                "simulation_mode_used": "garch_t",
                "recommended_result": {
                    "allocation_name": "balanced_core",
                    "success_probability": 0.52,
                    "product_adjusted_success_probability": 0.50,
                    "implied_required_annual_return": 0.08,
                    "risk_summary": {"max_drawdown_90pct": 0.09},
                },
                "frontier_analysis": {
                    "scenario_status": {
                        "target_return_priority": {
                            "available": False,
                            "constraint_met": False,
                            "reason": "no_candidate_meets_required_annual_return",
                        },
                        "drawdown_priority": {
                            "available": False,
                            "constraint_met": False,
                            "reason": "no_candidate_meets_max_drawdown_tolerance",
                        },
                    },
                },
            }
        }
    }

    explanation = build_probability_explanation(
        snapshot,
        requested_annual_return=0.08,
        requested_max_drawdown=0.08,
    )

    assert explanation["target_return_tradeoff"]["selection_basis"] == "frontier_analysis"
    assert explanation["target_return_tradeoff"]["constraint_met"] is False
    assert explanation["target_return_tradeoff"]["availability_reason"] == "no_candidate_meets_required_annual_return"
    assert explanation["target_return_tradeoff"]["selected_allocation_name"] is None
    assert explanation["drawdown_limit_tradeoff"]["selection_basis"] == "frontier_analysis"
    assert explanation["drawdown_limit_tradeoff"]["constraint_met"] is False
    assert explanation["drawdown_limit_tradeoff"]["availability_reason"] == "no_candidate_meets_max_drawdown_tolerance"


def test_route_intent_supports_daily_monitor_and_sync_commands():
    from agent.nli_router import route_intent

    assert route_intent("今天帮我监控一下需要止盈止损的品种") == "daily_monitor"
    assert route_intent("请为用户 shell_user 手工同步持仓") == "sync_portfolio_manual"
    assert route_intent("请用OCR识别并同步这个账户持仓") == "sync_portfolio_ocr"
    assert route_intent("请解释当前季度执行策略") == "explain_execution_policy"
    assert route_intent("explain execution policy for user shell_user") == "explain_execution_policy"


def test_bridge_handles_explainability_and_daily_monitor(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    handle_task(
        "onboard user shell_user assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )

    explanation = handle_task("请解释你用了哪些历史数据、哪些是推算历史，用户 shell_user", db_path=str(db))
    assert explanation["intent"]["name"] == "explain_data_basis"
    assert explanation["result"]["workflow"] == "explain_data_basis"
    assert "simulation_mode_used" in explanation["result"]["explanation"]
    assert "observed_history_days" in explanation["result"]["explanation"]

    tradeoff = handle_task("坚持8%年化回撤是多少，用户 shell_user", db_path=str(db))
    assert tradeoff["intent"]["name"] == "explain_probability"
    assert tradeoff["result"]["workflow"] == "explain_probability"
    assert "target_return_tradeoff" in tradeoff["result"]["explanation"]
    assert tradeoff["result"]["explanation"]["target_return_tradeoff"]["requested_annual_return"] == 0.08

    drawdown_tradeoff = handle_task("坚持回撤不超过8%收益率能到多少，用户 shell_user", db_path=str(db))
    assert drawdown_tradeoff["intent"]["name"] == "explain_probability"
    assert drawdown_tradeoff["result"]["workflow"] == "explain_probability"
    assert "drawdown_limit_tradeoff" in drawdown_tradeoff["result"]["explanation"]
    assert drawdown_tradeoff["result"]["explanation"]["drawdown_limit_tradeoff"]["requested_max_drawdown"] == 0.08

    monitor = handle_task("今天帮我监控一下用户 shell_user 需要止盈止损的品种", db_path=str(db))
    assert monitor["intent"]["name"] == "daily_monitor"
    assert monitor["result"]["workflow"] == "daily_monitor"
    assert isinstance(monitor["result"]["alerts"], list)


def test_bridge_explain_probability_preserves_unavailable_frontier_reason(monkeypatch, tmp_path):
    from integration.openclaw.bridge import handle_task

    snapshot = {
        "latest_baseline": {
            "goal_solver_output": {
                "simulation_mode_requested": "garch_t",
                "simulation_mode_used": "garch_t",
                "recommended_result": {
                    "allocation_name": "balanced_core",
                    "success_probability": 0.52,
                    "product_adjusted_success_probability": 0.50,
                    "implied_required_annual_return": 0.08,
                    "risk_summary": {"max_drawdown_90pct": 0.09},
                },
                "frontier_analysis": {
                    "scenario_status": {
                        "target_return_priority": {
                            "available": False,
                            "constraint_met": False,
                            "reason": "no_candidate_meets_required_annual_return",
                        },
                    }
                },
            }
        }
    }

    monkeypatch.setattr(
        "integration.openclaw.bridge.load_frontdesk_snapshot",
        lambda account_profile_id, db_path=None: snapshot,
    )

    result = handle_task(
        "坚持8%年化回撤是多少，用户 shell_user",
        db_path=str(tmp_path / "frontdesk.sqlite"),
    )

    assert result["intent"]["name"] == "explain_probability"
    explanation = result["result"]["explanation"]
    assert explanation["target_return_tradeoff"]["selection_basis"] == "frontier_analysis"
    assert explanation["target_return_tradeoff"]["constraint_met"] is False
    assert explanation["target_return_tradeoff"]["availability_reason"] == "no_candidate_meets_required_annual_return"
    assert "achievable_implied_annual_return" not in explanation["target_return_tradeoff"]


def test_bridge_handles_manual_sync_and_execution_policy_explanation(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    handle_task(
        "onboard user shell_user assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )

    holdings_json = json.dumps(
        [
            {
                "product_id": "cn_bond_gov_etf",
                "product_name": "国债ETF",
                "market_value": 56000,
                "cost_basis": 55000,
            }
        ],
        ensure_ascii=False,
    )
    sync_result = handle_task(
        f"请为用户 shell_user 手工同步持仓 json:{holdings_json}",
        db_path=str(db),
    )
    assert sync_result["intent"]["name"] == "sync_portfolio_manual"
    assert sync_result["result"]["workflow"] == "sync_observed_portfolio"
    assert sync_result["result"]["observed_portfolio"]["source_kind"] == "manual"

    policy_result = handle_task("请解释当前季度执行策略，用户 shell_user", db_path=str(db))
    assert policy_result["intent"]["name"] == "explain_execution_policy"
    assert policy_result["result"]["workflow"] == "explain_execution_policy"
    assert "trigger_rules" in policy_result["result"]["execution_policy"]


def test_bridge_approve_plan_ignores_version_like_user_id_tokens(tmp_path):
    from integration.openclaw.bridge import handle_task
    from frontdesk.service import load_user_state

    db = tmp_path / "frontdesk.sqlite"
    handle_task(
        "onboard user v12_bridge_user assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )
    state = load_user_state("v12_bridge_user", db_path=str(db))
    pending = state["pending_execution_plan"]

    result = handle_task(
        f"approve plan {pending['plan_id']} v{pending['plan_version']} for user v12_bridge_user",
        db_path=str(db),
    )

    assert result["intent"]["name"] == "approve_plan"
    assert result["result"]["workflow"] == "approve_plan"
    assert result["invocation"]["plan_version"] == pending["plan_version"]
