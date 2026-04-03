from __future__ import annotations

import json


def test_route_intent_supports_explain_data_basis():
    from agent.nli_router import route_intent

    assert route_intent("请解释你用了哪些历史数据、哪些是推算历史") == "explain_data_basis"


def test_route_intent_supports_daily_monitor_and_sync_commands():
    from agent.nli_router import route_intent

    assert route_intent("今天帮我监控一下需要止盈止损的品种") == "daily_monitor"
    assert route_intent("请为用户 shell_user 手工同步持仓") == "sync_portfolio_manual"
    assert route_intent("请用OCR识别并同步这个账户持仓") == "sync_portfolio_ocr"
    assert route_intent("请解释当前季度执行策略") == "explain_execution_policy"


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

    monitor = handle_task("今天帮我监控一下用户 shell_user 需要止盈止损的品种", db_path=str(db))
    assert monitor["intent"]["name"] == "daily_monitor"
    assert monitor["result"]["workflow"] == "daily_monitor"
    assert isinstance(monitor["result"]["alerts"], list)


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
