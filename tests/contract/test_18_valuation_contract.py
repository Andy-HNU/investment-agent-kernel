from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from shared.audit import DataStatus
from snapshot_ingestion.engine import build_snapshot_bundle
from snapshot_ingestion.valuation import (
    build_valuation_percentile_results,
    coerce_valuation_observations,
)


def _observed_inputs() -> dict[str, dict[str, object]]:
    return {
        "equity_cn": {
            "metric_name": "pe_ttm",
            "current_value": 12.0,
            "history_values": [8.0, 9.5, 10.0, 11.0, 12.0, 13.0],
            "source_ref": "akshare:000300:pe_ttm",
            "as_of": "2026-03-29",
            "data_status": "observed",
            "audit_window": {
                "start_date": "2018-01-01",
                "end_date": "2026-03-29",
                "trading_days": 2000,
                "observed_days": 2000,
                "inferred_days": 0,
            },
        }
    }


@pytest.mark.contract
def test_observed_valuation_snapshot_coerces_and_computes_percentile_result():
    observations = coerce_valuation_observations(_observed_inputs())
    results = build_valuation_percentile_results(
        buckets=["equity_cn"],
        observed_inputs=_observed_inputs(),
        valuation_z_scores={},
        as_of="2026-03-29",
    )

    assert observations["equity_cn"].data_status == DataStatus.OBSERVED
    assert observations["equity_cn"].audit_window is not None
    assert observations["equity_cn"].audit_window.trading_days == 2000
    assert results["equity_cn"].data_status == DataStatus.OBSERVED
    assert results["equity_cn"].source_ref == "akshare:000300:pe_ttm"
    assert results["equity_cn"].audit_window is not None
    assert results["equity_cn"].percentile == pytest.approx(5 / 6, abs=1e-6)
    assert results["equity_cn"].valuation_position == "rich"


@pytest.mark.contract
def test_lack_of_observed_valuation_source_does_not_masquerade_as_observed_percentile():
    results = build_valuation_percentile_results(
        buckets=["equity_cn", "bond_cn"],
        observed_inputs=None,
        valuation_z_scores={"equity_cn": 1.5},
        as_of="2026-03-29",
    )

    assert results["equity_cn"].data_status == DataStatus.INFERRED
    assert results["equity_cn"].source_ref == "market_raw.valuation_z_scores"
    assert results["equity_cn"].audit_window is None
    assert results["equity_cn"].percentile > 0.9

    assert results["bond_cn"].data_status == DataStatus.PRIOR_DEFAULT
    assert results["bond_cn"].source_ref == "calibration:valuation_prior_default"
    assert results["bond_cn"].percentile == pytest.approx(0.5)
    assert results["bond_cn"].audit_window is None


@pytest.mark.contract
def test_calibration_output_carries_honest_valuation_metadata():
    bundle = build_snapshot_bundle(
        account_profile_id="valuation_contract_profile",
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw={
            "raw_volatility": {
                "equity_cn": 0.18,
                "bond_cn": 0.04,
                "gold": 0.12,
                "satellite": 0.22,
            },
            "liquidity_scores": {
                "equity_cn": 0.9,
                "bond_cn": 0.95,
                "gold": 0.85,
                "satellite": 0.6,
            },
            "valuation_z_scores": {
                "gold": -0.4,
                "satellite": 1.8,
            },
            "observed_valuation_inputs": _observed_inputs(),
            "expected_returns": {
                "equity_cn": 0.08,
                "bond_cn": 0.03,
                "gold": 0.04,
                "satellite": 0.1,
            },
        },
        account_raw={
            "weights": {
                "equity_cn": 0.5,
                "bond_cn": 0.25,
                "gold": 0.15,
                "satellite": 0.1,
            },
            "total_value": 100000.0,
            "available_cash": 5000.0,
            "remaining_horizon_months": 36,
        },
        goal_raw={
            "goal_amount": 300000.0,
            "horizon_months": 36,
            "goal_description": "valuation contract target",
            "success_prob_threshold": 0.7,
            "priority": "important",
            "risk_preference": "moderate",
        },
        constraint_raw={
            "ips_bucket_boundaries": {
                "equity_cn": (0.2, 0.7),
                "bond_cn": (0.1, 0.5),
                "gold": (0.0, 0.25),
                "satellite": (0.0, 0.2),
            },
            "satellite_cap": 0.2,
            "theme_caps": {"technology": 0.1},
            "qdii_cap": 0.15,
            "liquidity_reserve_min": 0.03,
            "max_drawdown_tolerance": 0.15,
        },
        behavior_raw={
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 1.0,
            "override_count_90d": 0,
            "cooldown_active": False,
        },
        remaining_horizon_months=36,
    )

    result = run_calibration(bundle, prior_calibration=None)
    metadata = result.market_state.valuation_percentile_results

    assert metadata["equity_cn"].data_status == DataStatus.OBSERVED
    assert metadata["equity_cn"].source_ref == "akshare:000300:pe_ttm"
    assert metadata["equity_cn"].audit_window is not None
    assert metadata["gold"].data_status == DataStatus.INFERRED
    assert metadata["gold"].source_ref == "market_raw.valuation_z_scores"
    assert metadata["bond_cn"].data_status == DataStatus.PRIOR_DEFAULT
    assert result.market_state.valuation_percentile["bond_cn"] == pytest.approx(0.5)
