from __future__ import annotations

from datetime import datetime, timezone

import pytest

from snapshot_ingestion.cycle_policy import evaluate_cycle_coverage
from snapshot_ingestion.engine import build_snapshot_bundle
from snapshot_ingestion.historical import build_historical_dataset_snapshot


@pytest.mark.contract
def test_evaluate_cycle_coverage_flags_missing_bear_phase():
    summary = evaluate_cycle_coverage(
        dates=["2020-01-01", "2020-01-02", "2020-01-03"],
        returns=[0.01, 0.02, 0.01],
    )

    assert summary.coverage_ok is False
    assert "missing_downcycle" in summary.reasons


@pytest.mark.contract
def test_evaluate_cycle_coverage_rejects_short_series_even_if_returns_span_multiple_shapes():
    summary = evaluate_cycle_coverage(
        dates=["2020-01-01", "2020-01-02", "2020-01-03"],
        returns=[0.25, -0.20, 0.25],
    )

    assert summary.coverage_ok is False
    assert "insufficient_observed_span" in summary.reasons


@pytest.mark.contract
def test_build_historical_dataset_snapshot_preserves_observed_and_inferred_history_fields():
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "akshare",
            "source_ref": "akshare://equity-cn",
            "as_of": "2026-04-01",
            "lookback_months": 120,
            "return_series": {"equity_cn": [0.01, -0.02, 0.015, 0.01]},
            "observed_history_days": 1200,
            "inferred_history_days": 400,
            "inference_method": "index_proxy",
            "cycle_reasons": ["missing_high_volatility"],
        }
    )

    assert dataset is not None
    assert dataset.observed_history_days == 1200
    assert dataset.inferred_history_days == 400
    assert dataset.inference_method == "index_proxy"
    assert dataset.cycle_reasons == ["missing_high_volatility"]


@pytest.mark.contract
def test_build_historical_dataset_snapshot_overrides_stale_verified_status_when_derived_cycle_is_insufficient():
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "baostock",
            "source_ref": "baostock://equity-cn",
            "as_of": "2026-04-01",
            "coverage_status": "verified",
            "return_series": {
                "equity_cn": [0.01, 0.01, 0.01, 0.01],
                "bond_cn": [0.002, 0.002, 0.002, 0.002],
            },
            "series_dates": ["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"],
        }
    )

    assert dataset is not None
    assert dataset.coverage_status == "cycle_insufficient"
    assert "insufficient_observed_span" in dataset.cycle_reasons


@pytest.mark.contract
def test_build_historical_dataset_snapshot_derives_cycle_reasons_and_observed_days_from_series():
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "baostock",
            "source_ref": "baostock://equity-cn",
            "as_of": "2026-04-01",
            "return_series": {
                "equity_cn": [0.01, 0.01, 0.01, 0.01],
                "bond_cn": [0.002, 0.002, 0.002, 0.002],
            },
            "series_dates": ["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"],
        }
    )

    assert dataset is not None
    assert dataset.observed_history_days == 4
    assert dataset.inferred_history_days == 0
    assert dataset.inference_method is None
    assert "insufficient_observed_span" in dataset.cycle_reasons
    assert "missing_downcycle" in dataset.cycle_reasons
    assert dataset.coverage_status == "cycle_insufficient"


@pytest.mark.contract
def test_build_snapshot_bundle_preserves_historical_cycle_metadata():
    bundle = build_snapshot_bundle(
        account_profile_id="cycle_user",
        as_of=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        market_raw={
            "raw_volatility": {"equity_cn": 0.18, "bond_cn": 0.04},
            "liquidity_scores": {"equity_cn": 0.8, "bond_cn": 0.9},
            "valuation_z_scores": {"equity_cn": -0.2, "bond_cn": 0.1},
            "historical_dataset": {
                "source_name": "akshare",
                "source_ref": "akshare://cn-core",
                "as_of": "2026-04-01",
                "lookback_months": 120,
                "return_series": {
                    "equity_cn": [0.01, -0.02, 0.015, 0.01],
                    "bond_cn": [0.002, 0.001, 0.003, 0.002],
                },
                "observed_history_days": 1000,
                "inferred_history_days": 250,
                "inference_method": "index_proxy",
                "cycle_reasons": ["missing_high_volatility"],
            },
        },
        account_raw={
            "weights": {"equity_cn": 0.6, "bond_cn": 0.4},
            "total_value": 100_000.0,
            "available_cash": 5_000.0,
        },
        goal_raw={"goal_amount": 150_000.0, "horizon_months": 36},
        constraint_raw={"ips_bucket_boundaries": {"equity_cn": [0.2, 0.8], "bond_cn": [0.2, 0.8]}},
        behavior_raw={
            "override_count_90d": 0,
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
        },
        remaining_horizon_months=36,
    )

    assert bundle.historical_dataset_metadata["observed_history_days"] == 1000
    assert bundle.historical_dataset_metadata["inferred_history_days"] == 250
    assert bundle.historical_dataset_metadata["inference_method"] == "index_proxy"
    assert bundle.historical_dataset_metadata["cycle_reasons"] == ["missing_high_volatility"]
