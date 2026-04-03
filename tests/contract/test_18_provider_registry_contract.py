from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontdesk.service import run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile
from snapshot_ingestion.historical import (
    HistoricalDatasetCache,
    build_historical_dataset_snapshot,
    summarize_historical_dataset,
)
from snapshot_ingestion.provider_matrix import find_provider_coverage, provider_capability_matrix_dicts
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config, provider_debug_metadata


def _profile(*, account_profile_id: str = "provider_registry_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=900_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={"equity_cn": 0.50, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.10},
    )


@pytest.mark.contract
def test_provider_capability_matrix_covers_account_and_live_portfolio():
    matrix = provider_capability_matrix_dicts()
    coverage = {row["asset_class"] for row in matrix}

    assert "account_raw" in coverage
    assert "live_portfolio" in coverage
    assert find_provider_coverage("etf") is not None
    assert provider_debug_metadata()["live_portfolio_coverage"]["asset_class"] == "live_portfolio"


@pytest.mark.contract
def test_fetch_snapshot_from_provider_config_supports_local_json_fixture(tmp_path):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "provider_snapshot_local.json"
    fetched = fetch_snapshot_from_provider_config(
        {
            "adapter": "local_json",
            "snapshot_path": str(fixture_path),
            "provider_name": "fixture_local_json",
            "as_of": "2026-03-30T07:30:00Z",
            "fetched_at": "2026-03-30T08:00:00Z",
        },
        workflow_type="monthly",
        account_profile_id="provider_registry_user",
        as_of="2026-03-30T07:30:00Z",
    )

    assert fetched is not None
    assert fetched.provider_name == "fixture_local_json"
    assert fetched.raw_overrides["account_raw"]["total_value"] == 63_500.0
    assert fetched.freshness["domains"]["account_raw"]["status"] == "fresh"


@pytest.mark.contract
def test_historical_dataset_cache_roundtrip_preserves_version_pin(tmp_path):
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "fixture_history",
            "source_ref": "fixture://history",
            "as_of": "2026-03-29",
            "frequency": "daily",
            "lookback_months": 24,
            "version_id": "fixture_history:2026-03-29:v1",
            "series_dates": ["2026-01-31", "2026-02-28", "2026-03-29", "2026-04-30"],
            "observed_history_days": 2400,
            "inferred_history_days": 120,
            "inference_method": "index_proxy",
            "coverage_status": "cycle_insufficient",
            "cycle_reasons": ["missing_downcycle"],
            "return_series": {
                "equity_cn": [0.01, 0.02, -0.01, 0.03],
                "bond_cn": [0.002, 0.004, 0.001, 0.003],
            },
        }
    )

    assert dataset is not None
    cache = HistoricalDatasetCache(tmp_path / "history-cache")
    cache.save(dataset)
    reloaded = cache.load("fixture_history:2026-03-29:v1")

    assert reloaded is not None
    assert reloaded.version_id == dataset.version_id
    assert reloaded.return_series == dataset.return_series
    assert reloaded.coverage_status == "cycle_insufficient"
    assert reloaded.cycle_reasons == ["missing_downcycle"]
    assert reloaded.observed_history_days == 2400
    assert reloaded.inferred_history_days == 120
    assert reloaded.inference_method == "index_proxy"
    assert reloaded.frequency == "daily"

    expected_returns, volatility, correlation_matrix = summarize_historical_dataset(reloaded)
    assert set(expected_returns) == {"equity_cn", "bond_cn"}
    assert set(volatility) == {"equity_cn", "bond_cn"}
    assert correlation_matrix["equity_cn"]["equity_cn"] == 1.0


@pytest.mark.contract
def test_summarize_historical_dataset_annualizes_daily_series_with_daily_scaler():
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "fixture_history",
            "source_ref": "fixture://history",
            "as_of": "2026-03-29",
            "frequency": "daily",
            "return_series": {
                "equity_cn": [0.01, 0.01, 0.01, 0.01],
                "bond_cn": [0.002, 0.002, 0.002, 0.002],
            },
            "series_dates": ["2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29"],
            "observed_history_days": 2520,
            "cycle_reasons": ["missing_downcycle"],
        }
    )

    assert dataset is not None
    expected_returns, volatility, _correlation_matrix = summarize_historical_dataset(dataset)

    assert expected_returns["equity_cn"] == pytest.approx(2.52)
    assert expected_returns["bond_cn"] == pytest.approx(0.504)
    assert volatility["equity_cn"] == pytest.approx(0.03)


@pytest.mark.contract
def test_formal_frontdesk_onboarding_rejects_local_json_provider_fixture(tmp_path):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "provider_snapshot_local.json"
    with pytest.raises(ValueError, match="formal frontdesk flow forbids debug adapter: local_json"):
        run_frontdesk_onboarding(
            _profile(account_profile_id="local_json_provider_user"),
            db_path=tmp_path / "frontdesk.sqlite",
            external_data_config={
                "adapter": "local_json",
                "snapshot_path": str(fixture_path),
                "provider_name": "fixture_local_json",
            },
        )


@pytest.mark.contract
def test_formal_frontdesk_onboarding_rejects_file_json_provider_fixture(tmp_path):
    fixture_path = tmp_path / "provider_snapshot_file.json"
    fixture_path.write_text(
        json.dumps(
            {
                "market_raw": {"expected_returns": {"equity_cn": 0.08}},
                "provider_name": "fixture_file_json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="formal frontdesk flow forbids debug adapter: file_json"):
        run_frontdesk_onboarding(
            _profile(account_profile_id="file_json_provider_user"),
            db_path=tmp_path / "frontdesk.sqlite",
            external_data_config={
                "adapter": "file_json",
                "file_path": str(fixture_path),
            },
        )
