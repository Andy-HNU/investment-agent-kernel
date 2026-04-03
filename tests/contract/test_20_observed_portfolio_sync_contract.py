from __future__ import annotations

import csv

import pytest

from frontdesk.service import (
    load_user_state,
    run_frontdesk_onboarding,
)
from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "observed_sync_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="ObservedSync",
        current_total_assets=120_000.0,
        monthly_contribution=8_000.0,
        goal_amount=450_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="60%沪深300 25%债券 15%黄金",
        restrictions=["不买股票"],
    )


def _manual_holdings() -> list[dict[str, object]]:
    return [
        {
            "product_id": "cn_equity_csi300_etf",
            "product_name": "沪深300ETF",
            "market_value": 48_000.0,
            "cost_basis": 45_000.0,
        },
        {
            "product_id": "cn_bond_gov_etf",
            "product_name": "国债ETF",
            "market_value": 32_000.0,
            "cost_basis": 31_000.0,
        },
        {
            "product_id": "cn_gold_etf",
            "product_name": "黄金ETF",
            "market_value": 18_000.0,
            "cost_basis": 17_500.0,
        },
        {
            "product_id": "cn_cash_money_fund",
            "product_name": "货币基金",
            "market_value": 12_000.0,
            "cost_basis": 12_000.0,
        },
    ]


@pytest.mark.contract
def test_sync_observed_portfolio_manual_persists_snapshot_and_reconciliation(tmp_path):
    from frontdesk.service import sync_observed_portfolio_manual

    db_path = tmp_path / "observed_manual.sqlite"
    profile = _profile(account_profile_id="observed_manual")
    run_frontdesk_onboarding(profile, db_path=db_path)

    summary = sync_observed_portfolio_manual(
        account_profile_id=profile.account_profile_id,
        holdings=_manual_holdings(),
        observed_at="2026-04-04T10:00:00Z",
        account_source="alipay",
        db_path=db_path,
    )

    assert summary["observed_portfolio"]["source_kind"] == "manual"
    assert len(summary["observed_portfolio"]["holdings"]) == 4
    assert summary["reconciliation_state"]["target_plan_id"]
    assert "equity_cn" in summary["reconciliation_state"]["drift_by_bucket"]


@pytest.mark.contract
def test_sync_observed_portfolio_import_reads_csv_statement(tmp_path):
    from frontdesk.service import sync_observed_portfolio_import

    db_path = tmp_path / "observed_import.sqlite"
    profile = _profile(account_profile_id="observed_import")
    run_frontdesk_onboarding(profile, db_path=db_path)

    csv_path = tmp_path / "statement.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["product_id", "product_name", "market_value", "cost_basis"])
        writer.writeheader()
        writer.writerow(
            {
                "product_id": "cn_bond_gov_etf",
                "product_name": "国债ETF",
                "market_value": "56000",
                "cost_basis": "55000",
            }
        )

    summary = sync_observed_portfolio_import(
        account_profile_id=profile.account_profile_id,
        import_path=csv_path,
        observed_at="2026-04-04T11:00:00Z",
        account_source="jd_finance",
        db_path=db_path,
    )

    assert summary["observed_portfolio"]["source_kind"] == "statement_import"
    assert summary["observed_portfolio"]["holdings"][0]["product_id"] == "cn_bond_gov_etf"


@pytest.mark.contract
def test_sync_observed_portfolio_ocr_preserves_confidence_and_flags_unexpected_products(tmp_path):
    from frontdesk.service import sync_observed_portfolio_ocr

    db_path = tmp_path / "observed_ocr.sqlite"
    profile = _profile(account_profile_id="observed_ocr")
    run_frontdesk_onboarding(profile, db_path=db_path)

    summary = sync_observed_portfolio_ocr(
        account_profile_id=profile.account_profile_id,
        holdings=[
            {
                "product_id": "cn_equity_csi300_etf",
                "product_name": "沪深300ETF",
                "market_value": 52_000.0,
                "confidence": 0.93,
            },
            {
                "product_id": "user_custom_unplanned_fund",
                "product_name": "自选混合基金",
                "market_value": 8_000.0,
                "confidence": 0.74,
            },
        ],
        observed_at="2026-04-04T12:00:00Z",
        account_source="ocr_upload",
        db_path=db_path,
    )

    assert summary["observed_portfolio"]["source_kind"] == "ocr"
    assert summary["observed_portfolio"]["holdings"][0]["confidence"] == pytest.approx(0.93)
    assert "user_custom_unplanned_fund" in summary["reconciliation_state"]["unexpected_products"]


@pytest.mark.contract
def test_load_user_state_surfaces_latest_observed_portfolio_and_reconciliation(tmp_path):
    from frontdesk.service import sync_observed_portfolio_manual

    db_path = tmp_path / "observed_state.sqlite"
    profile = _profile(account_profile_id="observed_state")
    run_frontdesk_onboarding(profile, db_path=db_path)
    sync_observed_portfolio_manual(
        account_profile_id=profile.account_profile_id,
        holdings=_manual_holdings(),
        observed_at="2026-04-04T13:00:00Z",
        account_source="alipay",
        db_path=db_path,
    )

    user_state = load_user_state(profile.account_profile_id, db_path=db_path)

    assert user_state["observed_portfolio"]["observed_at"] == "2026-04-04T13:00:00Z"
    assert user_state["reconciliation_state"]["planned_action_status"] in {"partial", "completed", "stale"}
