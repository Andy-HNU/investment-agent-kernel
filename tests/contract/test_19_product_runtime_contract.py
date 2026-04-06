from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk.service import load_user_state, run_frontdesk_onboarding
from frontdesk.storage import FrontdeskStore
from product_mapping.engine import build_execution_plan
from product_mapping.types import ProductCandidate
from product_mapping.runtime_inputs import (
    build_runtime_product_universe_context,
    build_runtime_product_valuation_context,
    enrich_market_raw_with_runtime_product_inputs,
)
from shared.onboarding import UserOnboardingProfile


def _audit_window() -> dict[str, object]:
    return {
        "start_date": "2024-04-05",
        "end_date": "2026-04-03",
        "trading_days": 491,
        "observed_days": 491,
        "inferred_days": 0,
    }


def _historical_dataset() -> dict[str, object]:
    return {
        "dataset_id": "market_history",
        "version_id": "yfinance:2024-04-05:2026-04-03",
        "frequency": "daily",
        "as_of": "2026-04-03",
        "source_name": "yfinance",
        "source_ref": "yfinance://market_history?symbols=equity_cn:510300.SS",
        "lookback_months": 24,
        "return_series": {
            "equity_cn": [0.01, -0.02, 0.03],
            "bond_cn": [0.002, -0.001, 0.001],
            "gold": [0.005, 0.002, -0.001],
            "satellite": [0.03, -0.04, 0.02],
        },
        "coverage_status": "verified",
        "cached_at": "2026-04-05T08:00:00Z",
        "notes": [],
        "audit_window": _audit_window(),
    }


def _profile(*, account_profile_id: str = "layer2_runtime_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="cash 12000, gold 6000",
        restrictions=["forbidden_theme:technology", "no_stock_picking", "no_high_risk_products"],
    )


@pytest.mark.contract
def test_build_runtime_product_universe_context_probes_registry_candidates(monkeypatch):
    seen: list[str] = []

    def fake_probe(candidate, *, as_of, cache_dir, preferred_provider, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(candidate.product_id)
        if candidate.product_id in {"cn_equity_dividend_etf", "cn_bond_gov_etf", "cn_satellite_energy_etf"}:
            return {
                "status": "observed",
                "tradable": True,
                "source_name": "yfinance",
                "source_ref": f"yfinance://{candidate.provider_symbol}",
                "as_of": "2026-04-03",
                "data_status": "observed",
                "audit_window": _audit_window(),
            }
        return {
            "status": "missing",
            "tradable": False,
            "source_name": "yfinance",
            "source_ref": f"yfinance://{candidate.provider_symbol}",
            "as_of": "2026-04-03",
            "data_status": "computed_from_observed",
            "audit_window": _audit_window(),
            "reason": "probe_failed",
        }

    monkeypatch.setattr("product_mapping.runtime_inputs._probe_product_observability", fake_probe)

    inputs, result = build_runtime_product_universe_context(
        market_raw={"historical_dataset": _historical_dataset()},
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/layer2_runtime_contract"),
    )

    assert inputs["requested"] is True
    assert inputs["require_observed_source"] is True
    assert result["source_status"] == "observed"
    assert result["source_name"] == "runtime_product_universe"
    assert result["source_ref"] == "yfinance://market_history?symbols=equity_cn:510300.SS"
    assert result["products"]["cn_equity_dividend_etf"]["status"] == "observed"
    assert result["products"]["cn_equity_dividend_etf"]["tradable"] is True
    assert result["products"]["qdii_hk_tech_fund"]["status"] == "missing"
    assert "cn_satellite_energy_etf" in seen


@pytest.mark.contract
def test_build_runtime_product_universe_context_short_circuits_rate_limited_provider(monkeypatch):
    candidates = [
        ProductCandidate(
            product_id="cn_equity_csi300_etf",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="market_history_yfinance",
            provider_symbol="510300",
            tags=["core", "broad_market"],
        ),
        ProductCandidate(
            product_id="cn_satellite_energy_etf",
            product_name="能源ETF",
            asset_bucket="satellite",
            product_family="satellite",
            wrapper_type="etf",
            provider_source="market_history_yfinance",
            provider_symbol="159930",
            tags=["satellite", "cyclical"],
        ),
    ]
    calls: list[str] = []

    def fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin):  # type: ignore[no-untyped-def]
        calls.append(str(spec.symbol))
        raise RuntimeError("Too Many Requests. Rate limited. Try after a while.")

    monkeypatch.setattr("product_mapping.runtime_inputs.load_builtin_catalog", lambda: candidates)
    monkeypatch.setattr("product_mapping.runtime_inputs.fetch_timeseries", fake_fetch_timeseries)

    _, result = build_runtime_product_universe_context(
        market_raw={"historical_dataset": _historical_dataset()},
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/layer2_runtime_contract"),
    )

    assert calls == ["510300.SS", "510300"]
    assert result is not None
    assert result["source_status"] == "observed"
    equity_payload = result["products"]["cn_equity_csi300_etf"]
    satellite_payload = result["products"]["cn_satellite_energy_etf"]
    assert equity_payload["status"] == "observed"
    assert equity_payload["data_status"] == "computed_from_observed"
    assert any("Rate limited" in note for note in equity_payload["notes"])
    assert satellite_payload["status"] == "observed"
    assert satellite_payload["data_status"] == "computed_from_observed"
    assert any("rate_limited_short_circuit" in note for note in satellite_payload["notes"])


@pytest.mark.contract
def test_build_runtime_product_universe_context_reuses_snapshot_payload():
    snapshot = {
        "source_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": "tinyshare://runtime_catalog?as_of=2026-04-05",
        "as_of": "2026-04-05",
        "runtime_candidates": [
            {
                "product_id": "ts_stock_000001_sz",
                "product_name": "平安银行",
                "asset_bucket": "equity_cn",
                "product_family": "a_share_stock",
                "wrapper_type": "stock",
                "provider_source": "tinyshare_stock_basic",
                "provider_symbol": "000001.SZ",
                "tags": ["equity", "stock_wrapper", "cn"],
            }
        ],
        "products": {
            "ts_stock_000001_sz": {
                "status": "observed",
                "tradable": True,
                "source_name": "tinyshare_runtime_catalog",
                "source_ref": "tinyshare://runtime_catalog?ts_code=000001.SZ",
                "as_of": "2026-04-05",
                "data_status": "observed",
            }
        },
    }

    inputs, result = build_runtime_product_universe_context(
        market_raw={"product_universe_snapshot": snapshot},
        as_of="2026-04-05T10:00:00Z",
    )

    assert inputs == {}
    assert result == snapshot


@pytest.mark.contract
def test_build_runtime_product_universe_context_derives_full_snapshot_contract_from_historical_dataset(monkeypatch):
    candidate = ProductCandidate(
        product_id="cn_equity_dividend_etf",
        product_name="红利ETF",
        asset_bucket="equity_cn",
        product_family="core",
        wrapper_type="etf",
        provider_source="market_history_yfinance",
        provider_symbol="510880",
        tags=["core", "dividend"],
    )

    monkeypatch.setattr("product_mapping.runtime_inputs.load_builtin_catalog", lambda: [candidate])
    monkeypatch.setattr(
        "product_mapping.runtime_inputs._probe_product_observability",
        lambda *args, **kwargs: {
            "status": "observed",
            "tradable": True,
            "source_name": "yfinance",
            "source_ref": "yfinance://510880.SS",
            "as_of": "2026-04-03",
            "data_status": "observed",
            "audit_window": _audit_window(),
            "coverage_status": "verified",
            "notes": [],
        },
    )

    inputs, result = build_runtime_product_universe_context(
        market_raw={"historical_dataset": _historical_dataset()},
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/layer2_runtime_contract"),
    )

    assert inputs["requested"] is True
    assert result is not None
    assert result["snapshot_id"] == "runtime_product_universe_2026-04-03"
    assert result["source_status"] == "observed"
    assert result["data_status"] == "computed_from_observed"
    assert result["item_count"] == 1
    assert result["items"][0]["product_id"] == "cn_equity_dividend_etf"
    assert result["items"][0]["wrapper"] == "etf"
    assert result["items"][0]["asset_bucket"] == "equity_cn"
    assert result["audit_window"]["trading_days"] == 491
    assert result["source_names"] == ["runtime_product_universe", "yfinance"]
    assert result["wrapper_counts"] == {"etf": 1}
    assert result["asset_bucket_counts"] == {"equity_cn": 1}
    assert len(result["runtime_candidates"]) == 1
    assert result["products"]["cn_equity_dividend_etf"]["coverage_status"] == "verified"


@pytest.mark.contract
def test_build_runtime_product_valuation_context_maps_bucket_observations_to_products():
    inputs, result = build_runtime_product_valuation_context(
        market_raw={
            "valuation_observations": {
                "equity_cn": {
                    "metric_name": "pe_ttm",
                    "current_value": 18.0,
                    "source_ref": "akshare:valuation:equity_cn",
                    "as_of": "2026-04-05",
                    "history_values": [21.0, 24.0, 27.0, 30.0],
                    "audit_window": _audit_window(),
                },
                "satellite": {
                    "metric_name": "pe_ttm",
                    "current_value": 16.0,
                    "source_ref": "akshare:valuation:satellite",
                    "as_of": "2026-04-05",
                    "history_values": [20.0, 22.0, 24.0, 28.0],
                    "audit_window": _audit_window(),
                },
            }
        },
        as_of="2026-04-05T10:00:00Z",
    )

    assert inputs["requested"] is True
    assert inputs["require_observed_source"] is True
    assert result["source_status"] == "observed"
    equity_payload = result["products"]["cn_equity_dividend_etf"]
    satellite_payload = result["products"]["cn_satellite_energy_etf"]
    assert equity_payload["status"] == "observed"
    assert equity_payload["pe_ratio"] == pytest.approx(18.0, abs=1e-6)
    assert equity_payload["percentile"] == pytest.approx(0.0, abs=1e-6)
    assert equity_payload["data_status"] == "computed_from_observed"
    assert equity_payload["audit_window"]["trading_days"] == 491
    assert satellite_payload["status"] == "observed"
    assert satellite_payload["percentile"] == pytest.approx(0.0, abs=1e-6)
    assert "cn_gold_etf" not in result["products"]


@pytest.mark.contract
def test_enrich_market_raw_with_runtime_product_inputs_preserves_policy_signals(monkeypatch):
    def fake_probe(candidate, *, as_of, cache_dir, preferred_provider, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "status": "observed",
            "tradable": True,
            "source_name": "yfinance",
            "source_ref": f"yfinance://{candidate.provider_symbol}",
            "as_of": "2026-04-03",
            "data_status": "observed",
            "audit_window": _audit_window(),
        }

    monkeypatch.setattr("product_mapping.runtime_inputs._probe_product_observability", fake_probe)

    market_raw = enrich_market_raw_with_runtime_product_inputs(
        {
            "historical_dataset": _historical_dataset(),
            "valuation_observations": {
                "equity_cn": {
                    "metric_name": "pe_ttm",
                    "current_value": 18.0,
                    "source_ref": "akshare:valuation:equity_cn",
                    "as_of": "2026-04-05",
                    "history_values": [21.0, 24.0, 27.0, 30.0],
                    "audit_window": _audit_window(),
                }
            },
            "policy_news_signals": [
                {
                    "signal_id": "energy-positive",
                    "as_of": "2026-04-05T10:00:00Z",
                    "published_at": "2026-04-04T09:00:00Z",
                    "source_type": "news",
                    "source_name": "newswire",
                    "source_refs": ["https://example.com/energy"],
                    "direction": "bullish",
                    "strength": 0.9,
                    "confidence": 0.8,
                    "target_buckets": ["satellite"],
                    "target_tags": ["cyclical"],
                }
            ],
        },
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/layer2_runtime_contract"),
    )

    assert market_raw["product_universe_inputs"]["requested"] is True
    assert market_raw["product_universe_result"]["source_status"] == "observed"
    assert market_raw["product_valuation_inputs"]["requested"] is True
    assert market_raw["product_valuation_result"]["source_status"] == "observed"
    assert market_raw["policy_news_signals"][0]["signal_id"] == "energy-positive"


@pytest.mark.contract
def test_frontdesk_onboarding_auto_generates_runtime_audits_and_maintenance_policy(monkeypatch, tmp_path):
    def fake_probe(candidate, *, as_of, cache_dir, preferred_provider, **kwargs):  # type: ignore[no-untyped-def]
        observed = {
            "cn_equity_dividend_etf",
            "cn_equity_low_vol_fund",
            "cn_bond_gov_etf",
            "cn_bond_pure_bond_fund",
            "cn_gold_etf",
            "cn_cash_money_fund",
            "cn_satellite_energy_etf",
            "qdii_us_broad_fund",
        }
        return {
            "status": "observed" if candidate.product_id in observed else "missing",
            "tradable": candidate.product_id in observed,
            "source_name": "yfinance",
            "source_ref": f"yfinance://{candidate.provider_symbol}",
            "as_of": "2026-04-03",
            "data_status": "observed" if candidate.product_id in observed else "computed_from_observed",
            "audit_window": _audit_window(),
        }

    monkeypatch.setattr("product_mapping.runtime_inputs._probe_product_observability", fake_probe)

    summary = run_frontdesk_onboarding(
        UserOnboardingProfile(
            **{
                **_profile().to_dict(),
                "account_profile_id": "layer2_runtime_policy_user",
                "restrictions": ["forbidden_theme:technology", "no_stock_picking"],
            }
        ),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "inline_snapshot",
            "provider_name": "fixture_inline_provider",
            "as_of": "2026-04-05T10:00:00Z",
            "fetched_at": "2026-04-05T10:05:00Z",
            "payload": {
                "market_raw": {
                    "historical_dataset": _historical_dataset(),
                    "valuation_observations": {
                        "equity_cn": {
                            "metric_name": "pe_ttm",
                            "current_value": 18.0,
                            "source_ref": "akshare:valuation:equity_cn",
                            "as_of": "2026-04-05",
                            "history_values": [21.0, 24.0, 27.0, 30.0],
                            "audit_window": _audit_window(),
                        },
                        "satellite": {
                            "metric_name": "pe_ttm",
                            "current_value": 16.0,
                            "source_ref": "akshare:valuation:satellite",
                            "as_of": "2026-04-05",
                            "history_values": [20.0, 22.0, 24.0, 28.0],
                            "audit_window": _audit_window(),
                        },
                    },
                    "policy_news_signals": [
                        {
                            "signal_id": "energy-positive",
                            "as_of": "2026-04-05T10:00:00Z",
                            "published_at": "2026-04-04T09:00:00Z",
                            "source_type": "news",
                            "source_name": "newswire",
                            "source_refs": ["https://example.com/energy"],
                            "direction": "bullish",
                            "strength": 0.9,
                            "confidence": 0.8,
                            "decay_half_life_days": 7.0,
                            "target_buckets": ["satellite"],
                            "target_tags": ["cyclical"],
                        }
                    ],
                }
            },
        },
    )

    pending = summary["pending_execution_plan"]
    db_path = tmp_path / "frontdesk.sqlite"
    user_state = load_user_state("layer2_runtime_policy_user", db_path=db_path)
    assert pending is not None
    assert user_state is not None
    assert pending["product_universe_audit_summary"]["source_status"] == "observed"
    assert pending["valuation_audit_summary"]["source_status"] == "observed"
    assert pending["policy_news_audit_summary"]["source_status"] == "observed"
    assert pending["items"]
    summary_satellite_item = next(item for item in pending["items"] if item["asset_bucket"] == "satellite")
    assert summary_satellite_item["primary_product_id"] == "cn_satellite_energy_etf"
    assert summary_satellite_item["target_amount"] is not None
    assert summary_satellite_item["trigger_conditions"]
    assert summary_satellite_item["policy_news_audit"]["status"] == "observed"
    detailed_pending = FrontdeskStore(db_path).get_latest_pending_execution_plan("layer2_runtime_policy_user")
    assert detailed_pending is not None
    detailed_pending_payload = detailed_pending.payload
    satellite_item = next(item for item in detailed_pending_payload["items"] if item["asset_bucket"] == "satellite")
    assert satellite_item["primary_product_id"] == "cn_satellite_energy_etf"
    assert all("technology" not in str(tag).lower() for tag in satellite_item["primary_product"]["tags"])
    assert pending["maintenance_policy_summary"]["initial_deploy_fraction"] == pytest.approx(0.40, abs=1e-6)
    assert pending["maintenance_policy_summary"]["drawdown_add_buy_threshold"] == pytest.approx(0.10, abs=1e-6)
    assert satellite_item["trigger_conditions"]


@pytest.mark.contract
def test_build_execution_plan_exposes_maintenance_policy_summary_and_trigger_conditions():
    plan = build_execution_plan(
        source_run_id="run_layer2_maintenance",
        source_allocation_id="allocation_layer2_maintenance",
        bucket_targets={"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
        restrictions=[],
        account_total_value=20_000.0,
        current_weights={"equity_cn": 0.20, "bond_cn": 0.20, "gold": 0.10, "cash_liquidity": 0.50},
        available_cash=8_000.0,
        liquidity_reserve_min=0.10,
    )

    assert plan.maintenance_policy_summary is not None
    assert plan.maintenance_policy_summary["initial_deploy_fraction"] == pytest.approx(0.40, abs=1e-6)
    assert plan.maintenance_policy_summary["core_take_profit_threshold"] == pytest.approx(0.12, abs=1e-6)
    assert plan.maintenance_policy_summary["satellite_take_profit_threshold"] == pytest.approx(0.15, abs=1e-6)
    equity_item = next(item for item in plan.items if item.asset_bucket == "equity_cn")
    assert equity_item.initial_trade_amount is not None
    assert equity_item.deferred_trade_amount is not None
    assert any("回撤达到10%" in condition for condition in equity_item.trigger_conditions)
