from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "observed_portfolio_cli_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
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


def _observed_portfolio(*, snapshot_id: str, source_kind: str = "manual_json") -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "source_kind": source_kind,
        "data_status": "observed",
        "completeness_status": "complete",
        "as_of": "2026-04-05T08:00:00Z",
        "total_value": 62_000.0,
        "available_cash": 1_200.0,
        "weights": {
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
        "holdings": [
            {"asset_bucket": "equity_cn", "product_id": "fund_equity_cn", "weight": 0.50},
            {"asset_bucket": "bond_cn", "product_id": "fund_bond_cn", "weight": 0.30},
            {"asset_bucket": "gold", "product_id": "etf_gold", "weight": 0.10},
            {"asset_bucket": "satellite", "product_id": "fund_satellite", "weight": 0.10},
        ],
        "missing_fields": [],
        "source_ref": "manual:inline",
    }


@pytest.mark.smoke
def test_frontdesk_cli_sync_portfolio_accepts_inline_observed_portfolio_json(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    onboarding_exit_code = main(
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
    assert onboarding_exit_code == 0

    sync_exit_code = main(
        [
            "sync-portfolio",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--observed-portfolio-json",
            json.dumps(_observed_portfolio(snapshot_id="cli_inline_20260405"), ensure_ascii=False),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert sync_exit_code == 0
    assert payload["workflow"] == "sync_portfolio"
    assert payload["status"] in {"synced", "completed"}
    assert payload["user_state"]["observed_portfolio"]["snapshot_id"] == "cli_inline_20260405"
    assert payload["user_state"]["reconciliation_state"]["status"] in {
        "aligned",
        "drifted",
        "pending_user_action",
        "no_observed_portfolio",
    }


@pytest.mark.smoke
def test_frontdesk_cli_sync_portfolio_accepts_ocr_merged_portfolio_file(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="observed_portfolio_cli_ocr")
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    onboarding_exit_code = main(
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
    assert onboarding_exit_code == 0

    payload_path = tmp_path / "ocr_merged_portfolio.json"
    payload_path.write_text(
        json.dumps(
            {
                "merged_portfolio": {
                    "snapshot_id": "ocr_file_20260405",
                    "source_kind": "ocr_snapshot",
                    "completeness_status": "partial",
                    "as_of": "2026-04-05T08:00:00Z",
                    "observed_portfolio": _observed_portfolio(
                        snapshot_id="ocr_file_20260405",
                        source_kind="ocr_snapshot",
                    ),
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    sync_exit_code = main(
        [
            "sync-portfolio",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--observed-portfolio-json",
            str(payload_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert sync_exit_code == 0
    assert payload["observed_portfolio"]["snapshot_id"] == "ocr_file_20260405"
    assert payload["observed_portfolio"]["source_kind"] == "ocr_snapshot"
    assert payload["reconciliation_state"]["observed_snapshot_id"] == "ocr_file_20260405"

