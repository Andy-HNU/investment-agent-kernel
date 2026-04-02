from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from snapshot_ingestion.adapters import market_history_adapter
from snapshot_ingestion.engine import build_snapshot_bundle
from snapshot_ingestion.historical import HistoricalDatasetCache, HistoricalDatasetSnapshot
from snapshot_ingestion.provider_matrix import find_provider_coverage, load_provider_capability_matrix
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config, provider_debug_metadata
from shared.datasets.types import VersionPin


def _market_raw_with_history() -> dict[str, object]:
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.11,
            "satellite": 0.20,
        },
        "liquidity_scores": {
            "equity_cn": 0.82,
            "bond_cn": 0.95,
            "gold": 0.78,
            "satellite": 0.55,
        },
        "valuation_z_scores": {
            "equity_cn": -0.2,
            "bond_cn": 0.1,
            "gold": -0.1,
            "satellite": 0.8,
        },
        "historical_dataset": {
            "source_name": "akshare",
            "source_ref": "akshare://etf-cn-daily",
            "as_of": "2026-03-30",
            "lookback_months": 24,
            "return_series": {
                "equity_cn": [0.01, 0.03, -0.02, 0.015, 0.01, -0.005],
                "bond_cn": [0.004, 0.003, 0.002, 0.004, 0.003, 0.002],
                "gold": [0.008, -0.004, 0.006, 0.005, 0.002, -0.003],
                "satellite": [0.018, 0.02, -0.03, 0.022, 0.01, -0.012],
            },
        },
        "policy_news_signals": [
            {
                "signal_id": "policy-001",
                "as_of": "2026-03-30T09:00:00Z",
                "source_type": "policy_analysis",
                "source_refs": ["https://policy.example/pbo c"],
                "policy_regime": "tightening",
                "macro_uncertainty": "high",
                "sentiment_stress": "elevated",
                "liquidity_stress": "elevated",
                "manual_review_required": True,
                "confidence": 0.82,
                "notes": ["policy stance changed"],
            }
        ],
    }


def _account_raw() -> dict[str, object]:
    return {
        "weights": {
            "equity_cn": 0.45,
            "bond_cn": 0.35,
            "gold": 0.10,
            "satellite": 0.10,
        },
        "total_value": 120_000.0,
        "available_cash": 8_000.0,
        "remaining_horizon_months": 48,
    }


def _goal_raw() -> dict[str, object]:
    return {
        "goal_amount": 350_000.0,
        "horizon_months": 48,
        "goal_description": "Four-year target",
        "success_prob_threshold": 0.65,
        "priority": "important",
        "risk_preference": "balanced",
    }


def _constraint_raw() -> dict[str, object]:
    return {
        "ips_bucket_boundaries": {
            "equity_cn": [0.20, 0.65],
            "bond_cn": [0.20, 0.60],
            "gold": [0.00, 0.20],
            "satellite": [0.00, 0.12],
        },
        "satellite_cap": 0.12,
        "theme_caps": {"technology": 0.10},
        "qdii_cap": 0.20,
        "liquidity_reserve_min": 0.05,
        "max_drawdown_tolerance": 0.12,
        "cooling_period_days": 3,
    }


def _daily_rows(*monthly_closes: tuple[str, float]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for date_text, close_value in monthly_closes:
        rows.append(
            {
                "date": date_text,
                "open": close_value,
                "high": close_value,
                "low": close_value,
                "close": close_value,
                "volume": 1000.0,
            }
        )
    return rows


@pytest.mark.contract
def test_provider_capability_matrix_covers_kernel_critical_asset_classes():
    matrix = load_provider_capability_matrix()
    asset_classes = {record.asset_class for record in matrix}

    assert "account_raw" in asset_classes
    assert "live_portfolio" in asset_classes
    assert "etf" in asset_classes
    assert "bond" in asset_classes
    assert "gold" in asset_classes
    assert find_provider_coverage("live_portfolio").primary_source == "manual_snapshot"
    assert find_provider_coverage("gold").verified_status == "in_progress"
    assert find_provider_coverage("a_share_equity").fallback_source == "baostock"
    assert find_provider_coverage("etf").historical_support == "partial"


@pytest.mark.contract
def test_inline_snapshot_provider_supports_debug_metadata():
    payload = fetch_snapshot_from_provider_config(
        {
            "adapter": "inline_snapshot",
            "provider_name": "fixture_provider",
            "fetched_at": "2026-03-30T08:00:00Z",
            "payload": {
                "market_raw": _market_raw_with_history(),
                "account_raw": _account_raw(),
            },
        },
        workflow_type="monthly",
        account_profile_id="provider_contract",
        as_of="2026-03-30T00:00:00Z",
    )
    debug = provider_debug_metadata()

    assert payload is not None
    assert payload.provider_name == "fixture_provider"
    assert "market_raw" in payload.raw_overrides
    assert debug["live_portfolio_coverage"]["asset_class"] == "live_portfolio"
    assert any(record["asset_class"] == "a_share_equity" for record in debug["capability_matrix"])


@pytest.mark.contract
def test_local_json_snapshot_provider_loads_payload(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "market_raw": _market_raw_with_history(),
                "account_raw": _account_raw(),
                "behavior_raw": {
                    "recent_chase_risk": "low",
                    "recent_panic_risk": "none",
                    "trade_frequency_30d": 0.0,
                    "override_count_90d": 0,
                    "cooldown_active": False,
                    "cooldown_until": None,
                    "behavior_penalty_coeff": 0.1,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = fetch_snapshot_from_provider_config(
        {
            "adapter": "local_json",
            "snapshot_path": str(snapshot_path),
            "provider_name": "fixture_local_json",
            "fetched_at": "2026-03-30T08:10:00Z",
        },
        workflow_type="onboarding",
        account_profile_id="provider_contract",
        as_of="2026-03-30T00:00:00Z",
    )

    assert payload.provider_name == "fixture_local_json"
    assert payload.raw_overrides["account_raw"]["total_value"] == 120_000.0
    assert payload.source_ref.startswith("file://")


@pytest.mark.contract
def test_historical_dataset_cache_roundtrip(tmp_path):
    cache = HistoricalDatasetCache(tmp_path / "historical_cache")
    dataset = HistoricalDatasetSnapshot(
        dataset_id="cn_core_returns",
        version_id="cn_core_returns:2026-04-01:v1",
        as_of="2026-04-01T00:00:00Z",
        source_name="akshare",
        source_ref="akshare://cn_core_returns",
        lookback_months=6,
        return_series={
            "equity_cn": [0.02, -0.01, 0.03, 0.01, 0.02, -0.015],
            "bond_cn": [0.003, 0.002, 0.004, 0.001, 0.002, 0.003],
        },
    )

    saved_path = cache.save(dataset)
    loaded = cache.load(dataset.version_id)

    assert saved_path.exists()
    assert loaded is not None
    assert loaded.version_id == dataset.version_id
    assert loaded.return_series["equity_cn"][0] == 0.02


@pytest.mark.contract
def test_historical_dataset_snapshot_defaults_to_in_progress():
    dataset = HistoricalDatasetSnapshot(
        dataset_id="cn_core_returns",
        version_id="cn_core_returns:v1",
        as_of="2026-04-01T00:00:00Z",
        source_name="fixture_history",
        source_ref="fixture://history",
        lookback_months=6,
        return_series={"equity_cn": [0.02, -0.01]},
    )

    assert dataset.coverage_status == "in_progress"


@pytest.mark.contract
def test_market_history_adapter_resamples_daily_bars_and_marks_default_status_in_progress(tmp_path, monkeypatch):
    rows_by_symbol = {
        "000300": _daily_rows(("2025-01-31", 100.0), ("2025-02-28", 110.0), ("2025-03-31", 121.0)),
        "511010": _daily_rows(("2025-01-31", 100.0), ("2025-02-28", 101.0), ("2025-03-31", 102.0)),
        "Au99.99": _daily_rows(("2025-01-31", 100.0), ("2025-02-28", 98.0), ("2025-03-31", 99.0)),
        "399006": _daily_rows(("2025-01-31", 100.0), ("2025-02-28", 115.0), ("2025-03-31", 120.0)),
    }

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin=False):
        del cache, allow_fallback
        rows = rows_by_symbol[str(spec.symbol)]
        return (rows, pin) if return_used_pin else rows

    monkeypatch.setattr(market_history_adapter, "fetch_timeseries", _fake_fetch_timeseries)

    payload = fetch_snapshot_from_provider_config(
        {
            "adapter": "market_history",
            "provider_name": "market_history_akshare_tx",
            "dataset_id": "cn_core_history",
            "dataset_cache_dir": str(tmp_path / "dataset-cache"),
            "historical_cache_dir": str(tmp_path / "historical-cache"),
            "lookback_months": 24,
            "bucket_series": {
                "equity_cn": {
                    "provider": "akshare",
                    "kind": "cn_index_daily",
                    "dataset_id": "cn_index_000300",
                    "symbol": "000300",
                    "version_id": "tx-csi300:v1",
                    "source_ref": "akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
                    "proxy_label": "沪深300指数",
                },
                "bond_cn": {
                    "provider": "akshare",
                    "kind": "cn_bond_daily",
                    "dataset_id": "cn_bond_511010",
                    "symbol": "511010",
                    "version_id": "bond-511010:v1",
                    "source_ref": "akshare://bond_zh_hs_daily?series_type=cn_bond_daily",
                    "proxy_label": "国债ETF",
                },
                "gold": {
                    "provider": "akshare",
                    "kind": "cn_gold_spot",
                    "dataset_id": "cn_gold_au9999",
                    "symbol": "Au99.99",
                    "version_id": "gold-au9999:v1",
                    "source_ref": "akshare://spot_hist_sge?series_type=cn_gold_spot",
                    "proxy_label": "黄金现货",
                },
                "satellite": {
                    "provider": "akshare",
                    "kind": "cn_index_daily",
                    "dataset_id": "cn_index_399006",
                    "symbol": "399006",
                    "version_id": "tx-cyb:v1",
                    "source_ref": "akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
                    "proxy_label": "创业板指数",
                },
            },
            "coverage_expectation": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
        workflow_type="monthly",
        account_profile_id="provider_contract",
        as_of="2026-04-01T00:00:00Z",
    )

    assert payload is not None
    assert payload.provider_name == "market_history_akshare_tx"
    market_raw = payload.raw_overrides["market_raw"]
    dataset = market_raw["historical_dataset"]
    assert dataset["coverage_status"] == "in_progress"
    assert dataset["return_series"]["equity_cn"] == pytest.approx([0.10, 0.10])
    assert market_raw["raw_volatility"]["equity_cn"] > 0.0
    assert market_raw["bucket_proxy_mapping"]["bucket_to_proxy"]["equity_cn"] == "沪深300指数"
    assert any("dataset_version=" in item["note"] for item in payload.provenance_items)


@pytest.mark.contract
def test_snapshot_bundle_and_calibration_absorb_history_and_policy_signals():
    bundle = build_snapshot_bundle(
        account_profile_id="provider_contract",
        as_of=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw_with_history(),
        account_raw=_account_raw(),
        goal_raw=_goal_raw(),
        constraint_raw=_constraint_raw(),
        behavior_raw={
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 0.0,
            "override_count_90d": 0,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.1,
        },
        remaining_horizon_months=48,
    )
    result = run_calibration(bundle, prior_calibration=None)

    assert bundle.historical_dataset_metadata["source_name"] == "akshare"
    assert bundle.policy_news_signals[0].policy_regime == "tightening"
    assert result.market_assumptions.historical_backtest_used is True
    assert result.market_assumptions.source_name == "akshare"
    assert result.market_state.policy_regime == "tightening"
    assert result.market_state.manual_review_required is True
    assert any("policy_signal policy_regime=tightening" in note for note in result.notes)
    assert any("historical_dataset source=akshare" in note for note in result.notes)
