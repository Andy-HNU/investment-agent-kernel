from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_openclaw_bridge_layer3_intents(tmp_path):
    from integration.openclaw.bridge import handle_task

    db_path = tmp_path / "frontdesk.sqlite"
    handle_task(
        "please onboard user bridge_layer3_user with current assets 50000, monthly 12000, goal 1000000 in 60 months, risk moderate",
        db_path=str(db_path),
    )
    sync = handle_task(
        'sync portfolio for user bridge_layer3_user with {"snapshot_id":"bridge_layer3_sync","source_kind":"manual_json","as_of":"2026-04-05T08:00:00Z","total_value":62000,"available_cash":1200,"weights":{"equity_cn":0.5,"bond_cn":0.3,"gold":0.1,"satellite":0.1},"holdings":[{"asset_bucket":"equity_cn","product_id":"fund_equity_cn","weight":0.5}]}',
        db_path=str(db_path),
    )
    assert sync["intent"]["name"] == "sync_portfolio"
    assert sync["result"]["workflow"] == "sync_portfolio"

    daily = handle_task("daily monitor for user bridge_layer3_user", db_path=str(db_path))
    assert daily["intent"]["name"] == "daily_monitor"
    assert daily["result"]["workflow"] == "daily_monitor"

    probability = handle_task("explain probability for user bridge_layer3_user", db_path=str(db_path))
    assert probability["intent"]["name"] == "explain_probability"
    assert probability["result"]["workflow"] == "explain_probability"

    plan_change = handle_task("explain plan change for user bridge_layer3_user", db_path=str(db_path))
    assert plan_change["intent"]["name"] == "explain_plan_change"
    assert plan_change["result"]["workflow"] == "explain_plan_change"

