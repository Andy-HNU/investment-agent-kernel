from __future__ import annotations

import json

import pytest


@pytest.mark.smoke
def test_openclaw_bridge_routes_sync_portfolio_task(tmp_path):
    from integration.openclaw.bridge import handle_task
    from frontdesk.service import run_frontdesk_onboarding
    from shared.onboarding import UserOnboardingProfile

    db_path = tmp_path / "frontdesk.sqlite"
    profile = UserOnboardingProfile(
        account_profile_id="bridge_sync_portfolio_user",
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
    run_frontdesk_onboarding(profile, db_path=db_path)

    task = (
        'sync portfolio for user bridge_sync_portfolio_user with '
        '{"snapshot_id":"bridge_sync_20260405","source_kind":"manual_json","as_of":"2026-04-05T08:00:00Z",'
        '"total_value":62000,"available_cash":1200,"weights":{"equity_cn":0.5,"bond_cn":0.3,"gold":0.1,"satellite":0.1},'
        '"holdings":[{"asset_bucket":"equity_cn","product_id":"fund_equity_cn","weight":0.5}]}'
    )
    result = handle_task(task, db_path=str(db_path))

    assert result["intent"]["name"] == "sync_portfolio"
    assert result["invocation"]["tool"] == "frontdesk.sync_portfolio"
    assert result["result"]["workflow"] == "sync_portfolio"
    assert result["result"]["user_state"]["observed_portfolio"]["snapshot_id"] == "bridge_sync_20260405"
    assert result["result"]["reconciliation_state"]["snapshot_id"] == "bridge_sync_20260405"
