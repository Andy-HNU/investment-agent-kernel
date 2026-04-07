from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


DEFAULT_AS_OF = "2026-04-07T00:00:00Z"
DEFAULT_AUDIT_WINDOW = {
    "start_date": "2024-04-05",
    "end_date": "2026-04-03",
    "trading_days": 491,
    "observed_days": 491,
    "inferred_days": 0,
}


def formal_market_raw_overrides() -> dict[str, object]:
    audit_window = deepcopy(DEFAULT_AUDIT_WINDOW)
    observation_dates = [
        "2026-03-27",
        "2026-03-30",
        "2026-03-31",
        "2026-04-01",
        "2026-04-02",
    ]
    runtime_candidates = [
        {
            "product_id": "cn_equity_dividend_etf",
            "product_name": "红利ETF",
            "asset_bucket": "equity_cn",
            "product_family": "core",
            "wrapper_type": "etf",
            "provider_source": "market_history_yfinance",
            "provider_symbol": "510880.SS",
            "tags": ["core", "dividend"],
        },
        {
            "product_id": "cn_bond_gov_etf",
            "product_name": "国债ETF",
            "asset_bucket": "bond_cn",
            "product_family": "defense",
            "wrapper_type": "etf",
            "provider_source": "market_history_yfinance",
            "provider_symbol": "511010.SS",
            "tags": ["defense", "bond"],
        },
        {
            "product_id": "cn_gold_etf",
            "product_name": "黄金ETF",
            "asset_bucket": "gold",
            "product_family": "defense",
            "wrapper_type": "etf",
            "provider_source": "market_history_yfinance",
            "provider_symbol": "518880.SS",
            "tags": ["gold"],
        },
        {
            "product_id": "cn_cash_money_fund",
            "product_name": "货币基金",
            "asset_bucket": "cash_liquidity",
            "product_family": "cash_management",
            "wrapper_type": "cash_mgmt",
            "provider_source": "account_liquidity_runtime",
            "provider_symbol": None,
            "tags": ["cash_management"],
        },
        {
            "product_id": "cn_satellite_energy_etf",
            "product_name": "能源ETF",
            "asset_bucket": "satellite",
            "product_family": "satellite",
            "wrapper_type": "etf",
            "provider_source": "market_history_yfinance",
            "provider_symbol": "159930.SZ",
            "tags": ["satellite", "cyclical"],
        },
    ]
    products = {
        candidate["product_id"]: {
            "status": "observed",
            "tradable": True,
            "source_name": "observed_runtime_catalog",
            "source_ref": f"observed://runtime_catalog/{candidate['product_id']}",
            "as_of": "2026-04-03",
            "data_status": "observed",
            "audit_window": deepcopy(audit_window),
            "coverage_status": "verified",
        }
        for candidate in runtime_candidates
    }
    return {
        "historical_dataset": {
            "dataset_id": "market_history",
            "version_id": "observed:2024-04-05:2026-04-03",
            "frequency": "daily",
            "as_of": "2026-04-03",
            "source_name": "observed_market_history",
            "source_ref": "observed://market_history?profile=formal_test",
            "lookback_months": 24,
            "return_series": {
                "equity_cn": [0.01, -0.02, 0.03, 0.015, -0.01],
                "bond_cn": [0.002, -0.001, 0.001, 0.002, 0.001],
                "gold": [0.005, 0.002, -0.001, 0.004, -0.002],
                "satellite": [0.03, -0.04, 0.02, 0.01, -0.015],
            },
            "coverage_status": "verified",
            "cached_at": "2026-04-05T08:00:00Z",
            "notes": [],
            "audit_window": deepcopy(audit_window),
            "product_simulation_input": {
                "frequency": "daily",
                "simulation_method": "product_independent_path",
                "audit_window": deepcopy(audit_window),
                "coverage_summary": {
                    "selected_product_count": 4,
                    "observed_product_count": 4,
                    "inferred_product_count": 0,
                    "missing_product_count": 0,
                },
                "products": [
                    {
                        "product_id": "cn_equity_dividend_etf",
                        "asset_bucket": "equity_cn",
                        "target_weight": 0.0,
                        "return_series": [0.012, -0.006, 0.009, 0.004, 0.007],
                        "observation_dates": list(observation_dates),
                        "source_ref": "observed://product_returns/cn_equity_dividend_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2026-03-27",
                        "observed_end_date": "2026-04-02",
                        "observed_points": 5,
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_bond_gov_etf",
                        "asset_bucket": "bond_cn",
                        "target_weight": 0.0,
                        "return_series": [0.001, 0.0005, 0.0012, 0.0008, 0.0011],
                        "observation_dates": list(observation_dates),
                        "source_ref": "observed://product_returns/cn_bond_gov_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2026-03-27",
                        "observed_end_date": "2026-04-02",
                        "observed_points": 5,
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_gold_etf",
                        "asset_bucket": "gold",
                        "target_weight": 0.0,
                        "return_series": [0.004, -0.003, 0.002, 0.001, -0.001],
                        "observation_dates": list(observation_dates),
                        "source_ref": "observed://product_returns/cn_gold_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2026-03-27",
                        "observed_end_date": "2026-04-02",
                        "observed_points": 5,
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_satellite_energy_etf",
                        "asset_bucket": "satellite",
                        "target_weight": 0.0,
                        "return_series": [0.016, -0.011, 0.013, 0.006, 0.009],
                        "observation_dates": list(observation_dates),
                        "source_ref": "observed://product_returns/cn_satellite_energy_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": "2026-03-27",
                        "observed_end_date": "2026-04-02",
                        "observed_points": 5,
                        "inferred_points": 0,
                    },
                ],
            },
        },
        "product_universe_result": {
            "snapshot_id": "observed_runtime_catalog_2026-04-03",
            "source_status": "observed",
            "source_name": "observed_runtime_catalog",
            "source_ref": "observed://runtime_catalog?profile=formal_test",
            "as_of": "2026-04-03",
            "data_status": "observed",
            "item_count": len(runtime_candidates),
            "runtime_candidates": runtime_candidates,
            "products": products,
            "audit_window": deepcopy(audit_window),
            "source_names": ["observed_runtime_catalog"],
            "wrapper_counts": {"etf": 4, "cash_mgmt": 1},
            "asset_bucket_counts": {
                "equity_cn": 1,
                "bond_cn": 1,
                "gold": 1,
                "cash_liquidity": 1,
                "satellite": 1,
            },
        },
        "product_valuation_result": {
            "source_status": "observed",
            "source_name": "observed_runtime_valuation",
            "source_ref": "observed://valuation?profile=formal_test",
            "as_of": "2026-04-03",
            "products": {
                "cn_equity_dividend_etf": {
                    "status": "observed",
                    "pe_ratio": 18.0,
                    "percentile": 0.18,
                    "data_status": "observed",
                    "audit_window": deepcopy(audit_window),
                    "passed_filters": True,
                    "reason": "valuation:passed",
                },
                "cn_satellite_energy_etf": {
                    "status": "observed",
                    "pe_ratio": 16.0,
                    "percentile": 0.22,
                    "data_status": "observed",
                    "audit_window": deepcopy(audit_window),
                    "passed_filters": True,
                    "reason": "valuation:passed",
                },
                "cn_bond_gov_etf": {"status": "not_applicable"},
                "cn_gold_etf": {"status": "not_applicable"},
                "cn_cash_money_fund": {"status": "not_applicable"},
            },
        },
    }


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def build_formal_snapshot_payload(
    profile: UserOnboardingProfile,
    *,
    as_of: str = DEFAULT_AS_OF,
    market_raw_overrides: dict[str, Any] | None = None,
    account_raw_overrides: dict[str, Any] | None = None,
    behavior_raw_overrides: dict[str, Any] | None = None,
    live_portfolio_overrides: dict[str, Any] | None = None,
    provider_name: str = "observed_formal_snapshot",
    source_ref: str | None = None,
) -> dict[str, Any]:
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    source_ref = source_ref or f"observed://snapshot/{profile.account_profile_id}"
    fetched_at = as_of

    market_raw = _deep_merge(bundle.raw_inputs["market_raw"], formal_market_raw_overrides())
    if market_raw_overrides:
        market_raw = _deep_merge(market_raw, market_raw_overrides)
    account_raw = deepcopy(bundle.raw_inputs["account_raw"])
    if account_raw_overrides:
        account_raw = _deep_merge(account_raw, account_raw_overrides)
    behavior_raw = deepcopy(bundle.raw_inputs["behavior_raw"])
    if behavior_raw_overrides:
        behavior_raw = _deep_merge(behavior_raw, behavior_raw_overrides)
    live_portfolio = deepcopy(bundle.live_portfolio)
    if live_portfolio_overrides:
        live_portfolio = _deep_merge(live_portfolio, live_portfolio_overrides)

    def _external_item(field: str, label: str, value: object) -> dict[str, object]:
        return {
            "field": field,
            "label": label,
            "value": deepcopy(value),
            "source_ref": source_ref,
            "as_of": as_of,
            "fetched_at": fetched_at,
            "data_status": "observed",
            "audit_window": deepcopy(DEFAULT_AUDIT_WINDOW),
            "note": "formal observed snapshot",
        }

    return {
        "market_raw": market_raw,
        "account_raw": account_raw,
        "behavior_raw": behavior_raw,
        "live_portfolio": live_portfolio,
        "input_provenance": {
            "externally_fetched": [
                _external_item("market_raw", "市场输入", market_raw),
                _external_item("account_raw", "账户输入", account_raw),
                _external_item("behavior_raw", "行为输入", behavior_raw),
                _external_item("live_portfolio", "持仓输入", live_portfolio),
            ]
        },
        "external_snapshot_meta": {
            "source": source_ref,
            "provider_name": provider_name,
            "source_kind": "snapshot_source",
            "as_of": as_of,
            "fetched_at": fetched_at,
            "domains": {
                field: {
                    "source_ref": source_ref,
                    "as_of": as_of,
                    "fetched_at": fetched_at,
                    "status": "fresh",
                    "data_status": "observed",
                    "audit_window": deepcopy(DEFAULT_AUDIT_WINDOW),
                }
                for field in ("market_raw", "account_raw", "behavior_raw", "live_portfolio")
            },
        },
    }


def write_formal_snapshot_source(
    tmp_path: Path,
    profile: UserOnboardingProfile,
    *,
    as_of: str = DEFAULT_AS_OF,
    market_raw_overrides: dict[str, Any] | None = None,
    account_raw_overrides: dict[str, Any] | None = None,
    behavior_raw_overrides: dict[str, Any] | None = None,
    live_portfolio_overrides: dict[str, Any] | None = None,
    provider_name: str = "observed_formal_snapshot",
) -> Path:
    snapshot_path = tmp_path / f"{profile.account_profile_id}_observed_snapshot.json"
    payload = build_formal_snapshot_payload(
        profile,
        as_of=as_of,
        market_raw_overrides=market_raw_overrides,
        account_raw_overrides=account_raw_overrides,
        behavior_raw_overrides=behavior_raw_overrides,
        live_portfolio_overrides=live_portfolio_overrides,
        provider_name=provider_name,
        source_ref=snapshot_path.resolve().as_uri(),
    )
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot_path
