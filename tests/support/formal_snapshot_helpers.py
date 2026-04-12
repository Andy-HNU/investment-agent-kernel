from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from probability_engine.factor_library import load_factor_library_snapshot
from probability_engine.factor_mapping import (
    ProductHolding,
    ProductMappingProduct,
    ProductReturnObservation,
    build_factor_mapping,
)
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


DEFAULT_AS_OF = "2026-04-07T00:00:00Z"
DEFAULT_AUDIT_WINDOW = {
    "start_date": "2024-04-05",
    "end_date": "2026-04-03",
    "trading_days": 491,
    "observed_days": 491,
    "inferred_days": 0,
}
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v14"
FACTOR_LIBRARY_SNAPSHOT_PATH = FIXTURE_DIR / "factor_library_snapshot.json"


def _weighted_return(factor_returns: dict[str, float], weights: dict[str, float]) -> float:
    return sum(float(weights.get(factor_id, 0.0)) * float(factor_returns.get(factor_id, 0.0)) for factor_id in weights)


def _repeat_pattern(pattern: list[float], length: int) -> list[float]:
    if length <= 0:
        return []
    if not pattern:
        return [0.0] * length
    repeats = (length + len(pattern) - 1) // len(pattern)
    return (pattern * repeats)[:length]


def _series_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(float(value) for value in values) / float(len(values))


def _series_std(values: list[float], *, mean: float | None = None) -> float:
    if not values:
        return 0.0
    center = float(mean) if mean is not None else _series_mean(values)
    variance = sum((float(value) - center) ** 2 for value in values) / float(len(values))
    return variance**0.5


def _build_probability_factor_mapping_payload(*, series_mode: str = "helper_pattern") -> dict[str, Any]:
    normalized_mode = str(series_mode).strip().lower()
    if normalized_mode not in {"helper_pattern", "factor_history"}:
        raise ValueError(f"unknown series_mode: {series_mode}")
    factor_library = load_factor_library_snapshot(FACTOR_LIBRARY_SNAPSHOT_PATH)
    factor_history = list(factor_library.factor_return_history)
    observation_dates = [row.date for row in factor_history]
    helper_series_templates: dict[str, list[float]] = {
        # Keep the helper snapshot realistic enough for acceptance runs:
        # balanced daily returns, modest drift, and visible drawdowns.
        "cn_equity_dividend_etf": [0.0035, -0.0040, 0.0022, -0.0025, 0.0014, -0.0016, 0.0028, 0.0004],
        "cn_bond_gov_etf": [0.0006, 0.0003, -0.0004, 0.0005, 0.0003, -0.0001, 0.0004, 0.0002],
        "cn_gold_etf": [0.0025, -0.0030, 0.0018, -0.0017, 0.0012, -0.0014, 0.0022, 0.0003],
        "cn_satellite_energy_etf": [0.0050, -0.0060, 0.0030, -0.0035, 0.0020, -0.0025, 0.0040, 0.0006],
    }

    product_specs: list[dict[str, Any]] = [
        {
            "product_id": "cn_equity_dividend_etf",
            "product_name": "红利ETF",
            "asset_bucket": "equity_cn",
            "asset_class": "equity",
            "region": "CN",
            "style": "dividend",
            "benchmark": "CSI300",
            "wrapper_type": "etf",
            "category": "cn_equity",
            "cluster_id": "cn_equity_cluster",
            "history_days": 252,
            "holdings_coverage": 0.90,
            "holdings_freshness": 0.92,
            "factor_weights": {
                "CN_EQ_BROAD": 0.78,
                "CN_EQ_GROWTH": 0.12,
                "CN_EQ_VALUE": 0.06,
                "GOLD_GLOBAL": 0.04,
            },
            "cluster_anchor_betas": {
                "CN_EQ_BROAD": 0.82,
                "CN_EQ_GROWTH": 0.08,
                "CN_EQ_VALUE": 0.04,
                "GOLD_GLOBAL": 0.02,
            },
            "holdings": [
                {
                    "security_id": "510880.SS",
                    "security_name": "红利ETF底仓",
                    "weight": 0.52,
                    "factor_exposures": {
                        "CN_EQ_BROAD": 0.95,
                        "CN_EQ_VALUE": 0.10,
                    },
                },
                {
                    "security_id": "000001.SZ",
                    "security_name": "平安银行",
                    "weight": 0.38,
                    "factor_exposures": {
                        "CN_EQ_BROAD": 0.90,
                        "CN_EQ_GROWTH": 0.08,
                    },
                },
            ],
        },
        {
            "product_id": "cn_bond_gov_etf",
            "product_name": "国债ETF",
            "asset_bucket": "bond_cn",
            "asset_class": "bond",
            "region": "CN",
            "style": "defense",
            "benchmark": "CDBond",
            "wrapper_type": "etf",
            "category": "cn_bond",
            "cluster_id": "cn_bond_cluster",
            "history_days": 252,
            "holdings_coverage": 0.88,
            "holdings_freshness": 0.93,
            "factor_weights": {
                "CN_RATE_DURATION": 0.72,
                "CN_CREDIT_SPREAD": 0.14,
                "GOLD_GLOBAL": 0.08,
                "USD_CNH": 0.06,
            },
            "cluster_anchor_betas": {
                "CN_RATE_DURATION": 0.75,
                "CN_CREDIT_SPREAD": 0.12,
                "GOLD_GLOBAL": 0.06,
                "USD_CNH": 0.03,
            },
            "holdings": [
                {
                    "security_id": "511010.SS",
                    "security_name": "国债ETF底仓",
                    "weight": 0.50,
                    "factor_exposures": {
                        "CN_RATE_DURATION": 0.96,
                        "CN_CREDIT_SPREAD": 0.08,
                    },
                },
                {
                    "security_id": "180019.OF",
                    "security_name": "债券增强",
                    "weight": 0.38,
                    "factor_exposures": {
                        "CN_RATE_DURATION": 0.82,
                        "CN_CREDIT_SPREAD": 0.18,
                    },
                },
            ],
        },
        {
            "product_id": "cn_gold_etf",
            "product_name": "黄金ETF",
            "asset_bucket": "gold",
            "asset_class": "commodity",
            "region": "GLOBAL",
            "style": "gold",
            "benchmark": "XAU",
            "wrapper_type": "etf",
            "category": "gold",
            "cluster_id": "gold_cluster",
            "history_days": 252,
            "holdings_coverage": 0.86,
            "holdings_freshness": 0.94,
            "factor_weights": {
                "GOLD_GLOBAL": 0.96,
                "USD_CNH": 0.04,
            },
            "cluster_anchor_betas": {
                "GOLD_GLOBAL": 0.95,
                "USD_CNH": 0.05,
            },
            "holdings": [
                {
                    "security_id": "518880.SS",
                    "security_name": "黄金ETF底仓",
                    "weight": 0.60,
                    "factor_exposures": {
                        "GOLD_GLOBAL": 0.98,
                    },
                },
                {
                    "security_id": "AU9999.SGE",
                    "security_name": "黄金现货",
                    "weight": 0.30,
                    "factor_exposures": {
                        "GOLD_GLOBAL": 0.92,
                        "USD_CNH": 0.04,
                    },
                },
            ],
        },
        {
            "product_id": "cn_satellite_energy_etf",
            "product_name": "能源ETF",
            "asset_bucket": "satellite",
            "asset_class": "equity",
            "region": "CN",
            "style": "satellite",
            "benchmark": "CSI500",
            "wrapper_type": "etf",
            "category": "satellite",
            "cluster_id": "satellite_cluster",
            "history_days": 252,
            "holdings_coverage": 0.89,
            "holdings_freshness": 0.91,
            "factor_weights": {
                "CN_EQ_BROAD": 0.84,
                "US_EQ_BROAD": 0.06,
                "GOLD_GLOBAL": 0.05,
                "USD_CNH": 0.05,
            },
            "cluster_anchor_betas": {
                "CN_EQ_BROAD": 0.86,
                "US_EQ_BROAD": 0.04,
                "GOLD_GLOBAL": 0.05,
                "USD_CNH": 0.05,
            },
            "holdings": [
                {
                    "security_id": "159930.SZ",
                    "security_name": "能源ETF底仓",
                    "weight": 0.55,
                    "factor_exposures": {
                        "CN_EQ_BROAD": 0.88,
                        "US_EQ_BROAD": 0.06,
                    },
                },
                {
                    "security_id": "600028.SH",
                    "security_name": "中国石化",
                    "weight": 0.34,
                    "factor_exposures": {
                        "CN_EQ_BROAD": 0.80,
                        "GOLD_GLOBAL": 0.06,
                    },
                },
            ],
        },
    ]

    products: list[ProductMappingProduct] = []
    series_tracks: dict[str, Any] = {
        "observation_dates": list(observation_dates),
        "by_product_id": {},
        "by_bucket": {},
    }
    for spec in product_specs:
        factor_history_series = [
            _weighted_return(row.factor_returns, dict(spec["factor_weights"]))
            for row in factor_history
        ]
        if normalized_mode == "factor_history":
            helper_pattern = helper_series_templates.get(str(spec["product_id"]), factor_history_series[:8])
            helper_mean = _series_mean(helper_pattern)
            helper_std = _series_std(helper_pattern, mean=helper_mean)
            raw_mean = _series_mean(factor_history_series)
            raw_std = _series_std(factor_history_series, mean=raw_mean)
            volatility_scale = helper_std / raw_std if raw_std > 0.0 else 1.0
            series = [
                helper_mean + ((float(value) - raw_mean) * volatility_scale)
                for value in factor_history_series
            ]
        else:
            series = _repeat_pattern(
                helper_series_templates.get(str(spec["product_id"]), factor_history_series[:8]),
                len(observation_dates),
            )
        series_tracks["by_product_id"][str(spec["product_id"])] = {
            "return_series": list(series),
            "observation_dates": list(observation_dates),
        }
        series_tracks["by_bucket"][str(spec["asset_bucket"])] = list(series)
        series_tracks["series_mode"] = normalized_mode
        products.append(
            ProductMappingProduct(
                product_id=str(spec["product_id"]),
                product_name=str(spec["product_name"]),
                asset_class=str(spec["asset_class"]),
                region=str(spec["region"]),
                style=str(spec["style"]),
                benchmark=str(spec["benchmark"]),
                wrapper_type=str(spec["wrapper_type"]),
                category=str(spec["category"]),
                cluster_id=str(spec["cluster_id"]),
                history_days=int(spec["history_days"]),
                holdings_coverage=float(spec["holdings_coverage"]),
                holdings_freshness=float(spec["holdings_freshness"]),
                holdings=tuple(
                    ProductHolding(
                        security_id=str(holding["security_id"]),
                        security_name=str(holding["security_name"]),
                        weight=float(holding["weight"]),
                        factor_exposures={
                            str(key): float(value)
                            for key, value in dict(holding["factor_exposures"]).items()
                        },
                    )
                    for holding in spec["holdings"]
                ),
                return_series=tuple(
                    ProductReturnObservation(
                        date=row.date,
                        product_return=series[index],
                    )
                    for index, row in enumerate(factor_history)
                ),
                cluster_anchor_betas={
                    str(key): float(value)
                    for key, value in dict(spec["cluster_anchor_betas"]).items()
                },
            )
        )

    mapping_results = build_factor_mapping(products, factor_library, as_of=factor_library.as_of)
    return {
        "probability_engine": {
            "factor_mapping": {
                "snapshot_id": factor_library.snapshot_id,
                "as_of": factor_library.as_of,
                "source_name": (
                    "observed_product_level_factor_mapping"
                    if normalized_mode == "factor_history"
                    else "helper_pattern_factor_mapping"
                ),
                "source_ref": (
                    f"observed://factor_mapping/{factor_library.snapshot_id}"
                    if normalized_mode == "factor_history"
                    else f"helper://factor_mapping/{factor_library.snapshot_id}"
                ),
                "products": [asdict(result) for result in mapping_results],
            }
        },
        "series_tracks": series_tracks,
    }


def _market_raw_overrides_for_series_mode(*, series_mode: str) -> dict[str, object]:
    audit_window = deepcopy(DEFAULT_AUDIT_WINDOW)
    probability_bundle = _build_probability_factor_mapping_payload(series_mode=series_mode)
    series_tracks = dict(probability_bundle.get("series_tracks") or {})
    observation_dates = list(series_tracks.get("observation_dates") or [])
    bucket_series = dict(series_tracks.get("by_bucket") or {})
    product_series = dict(series_tracks.get("by_product_id") or {})
    equity_series = list(bucket_series.get("equity_cn") or [])
    bond_series = list(bucket_series.get("bond_cn") or [])
    gold_series = list(bucket_series.get("gold") or [])
    satellite_series = list(bucket_series.get("satellite") or [])
    product_series_ref_prefix = "observed" if series_mode == "factor_history" else "helper"
    product_universe_source = "observed_runtime_catalog" if series_mode == "factor_history" else "helper_runtime_catalog"
    valuation_source = "observed_runtime_valuation" if series_mode == "factor_history" else "helper_runtime_valuation"
    history_source = "observed_market_history" if series_mode == "factor_history" else "helper_market_history"
    if observation_dates:
        audit_window["trading_days"] = len(observation_dates)
        audit_window["observed_days"] = len(observation_dates)
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
            "version_id": f"{product_universe_source}:2024-04-05:2026-04-03",
            "frequency": "daily",
            "as_of": "2026-04-03",
            "source_name": history_source,
            "source_ref": f"{product_series_ref_prefix}://market_history?profile=formal_test",
            "lookback_months": 24,
            "return_series": {
                "equity_cn": list(equity_series),
                "bond_cn": list(bond_series),
                "gold": list(gold_series),
                "satellite": list(satellite_series),
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
                        "return_series": list(product_series.get("cn_equity_dividend_etf", {}).get("return_series") or equity_series),
                        "observation_dates": list(
                            product_series.get("cn_equity_dividend_etf", {}).get("observation_dates") or observation_dates
                        ),
                        "source_ref": f"{product_series_ref_prefix}://product_returns/cn_equity_dividend_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": observation_dates[0] if observation_dates else "2026-03-27",
                        "observed_end_date": observation_dates[-1] if observation_dates else "2026-04-02",
                        "observed_points": len(
                            product_series.get("cn_equity_dividend_etf", {}).get("return_series") or equity_series
                        ),
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_bond_gov_etf",
                        "asset_bucket": "bond_cn",
                        "target_weight": 0.0,
                        "return_series": list(product_series.get("cn_bond_gov_etf", {}).get("return_series") or bond_series),
                        "observation_dates": list(
                            product_series.get("cn_bond_gov_etf", {}).get("observation_dates") or observation_dates
                        ),
                        "source_ref": f"{product_series_ref_prefix}://product_returns/cn_bond_gov_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": observation_dates[0] if observation_dates else "2026-03-27",
                        "observed_end_date": observation_dates[-1] if observation_dates else "2026-04-02",
                        "observed_points": len(
                            product_series.get("cn_bond_gov_etf", {}).get("return_series") or bond_series
                        ),
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_gold_etf",
                        "asset_bucket": "gold",
                        "target_weight": 0.0,
                        "return_series": list(product_series.get("cn_gold_etf", {}).get("return_series") or gold_series),
                        "observation_dates": list(
                            product_series.get("cn_gold_etf", {}).get("observation_dates") or observation_dates
                        ),
                        "source_ref": f"{product_series_ref_prefix}://product_returns/cn_gold_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": observation_dates[0] if observation_dates else "2026-03-27",
                        "observed_end_date": observation_dates[-1] if observation_dates else "2026-04-02",
                        "observed_points": len(
                            product_series.get("cn_gold_etf", {}).get("return_series") or gold_series
                        ),
                        "inferred_points": 0,
                    },
                    {
                        "product_id": "cn_satellite_energy_etf",
                        "asset_bucket": "satellite",
                        "target_weight": 0.0,
                        "return_series": list(
                            product_series.get("cn_satellite_energy_etf", {}).get("return_series") or satellite_series
                        ),
                        "observation_dates": list(
                            product_series.get("cn_satellite_energy_etf", {}).get("observation_dates") or observation_dates
                        ),
                        "source_ref": f"{product_series_ref_prefix}://product_returns/cn_satellite_energy_etf",
                        "data_status": "observed",
                        "frequency": "daily",
                        "observed_start_date": observation_dates[0] if observation_dates else "2026-03-27",
                        "observed_end_date": observation_dates[-1] if observation_dates else "2026-04-02",
                        "observed_points": len(
                            product_series.get("cn_satellite_energy_etf", {}).get("return_series") or satellite_series
                        ),
                        "inferred_points": 0,
                    },
                ],
            },
        },
        "product_universe_result": {
            "snapshot_id": f"{product_universe_source}_2026-04-03",
            "source_status": "observed",
            "source_name": product_universe_source,
            "source_ref": f"{product_series_ref_prefix}://runtime_catalog?profile=formal_test",
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
            "source_name": valuation_source,
            "source_ref": f"{product_series_ref_prefix}://valuation?profile=formal_test",
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
        "probability_engine": probability_bundle["probability_engine"],
    }


def formal_market_raw_overrides() -> dict[str, object]:
    return _market_raw_overrides_for_series_mode(series_mode="helper_pattern")


def observed_market_raw_overrides() -> dict[str, object]:
    return _market_raw_overrides_for_series_mode(series_mode="factor_history")


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
