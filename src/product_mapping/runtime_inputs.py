from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from product_mapping.catalog import load_builtin_catalog
from product_mapping.types import ProductCandidate
from shared.audit import AuditWindow, DataStatus
from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.tinyshare import (
    build_runtime_valuation_result as _build_tinyshare_runtime_valuation_result,
    has_token as _tinyshare_has_token,
    load_runtime_catalog as _load_tinyshare_runtime_catalog,
)
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.provider_matrix import find_provider_coverage
from snapshot_ingestion.valuation import build_valuation_percentile_results

_SUPPORTED_PROBE_PROVIDERS = {"yfinance", "akshare", "baostock", "tinyshare"}
_PROBE_LOOKBACK_DAYS = 21
_VALUATION_BUCKETS = ("equity_cn", "bond_cn", "gold", "satellite")


def load_tinyshare_runtime_catalog(
    *,
    as_of: str,
    cache_dir: Path | None = None,
) -> tuple[list[ProductCandidate], dict[str, Any]]:
    return _load_tinyshare_runtime_catalog(as_of=as_of, cache_dir=cache_dir)


def build_tinyshare_runtime_valuation_result(
    candidates: list[ProductCandidate],
    *,
    as_of: str,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    return _build_tinyshare_runtime_valuation_result(candidates, as_of=as_of, cache_dir=cache_dir)


def _as_of_date(as_of: str) -> str:
    return str(as_of).split("T", 1)[0]


def _probe_start_date(end_date: str) -> str:
    return (date.fromisoformat(end_date) - timedelta(days=_PROBE_LOOKBACK_DAYS)).isoformat()


def _symbol_for_yfinance(candidate: ProductCandidate) -> str | None:
    symbol = str(candidate.provider_symbol or "").strip()
    if not symbol:
        return None
    region = str(candidate.region or "CN").strip().upper()
    if region == "CN" and symbol.isdigit():
        exchange = "SS" if symbol.startswith(("5", "6")) else "SZ"
        return f"{symbol}.{exchange}"
    if region == "HK" and symbol.isdigit():
        return f"{symbol}.HK"
    return symbol


def _symbol_for_provider(candidate: ProductCandidate, provider: str) -> str | None:
    symbol = str(candidate.provider_symbol or "").strip()
    if not symbol:
        return None
    if provider == "yfinance":
        return _symbol_for_yfinance(candidate)
    return symbol


def _candidate_asset_class(candidate: ProductCandidate) -> str:
    if candidate.asset_bucket == "cash_liquidity":
        return "cash_liquidity"
    if candidate.asset_bucket == "gold":
        return "gold"
    if "qdii" in candidate.tags:
        return "qdii"
    if candidate.wrapper_type == "stock":
        region = str(candidate.region or "CN").upper()
        if region == "US":
            return "us_equity"
        if region == "HK":
            return "hong_kong_equity"
        return "a_share_equity"
    if candidate.asset_bucket == "bond_cn":
        return "bond"
    if candidate.wrapper_type == "fund":
        return "public_fund"
    return "etf"


def _provider_sequence(candidate: ProductCandidate, *, preferred_provider: str | None) -> list[str]:
    coverage = find_provider_coverage(_candidate_asset_class(candidate))
    sequence: list[str] = []
    for item in (
        str(preferred_provider or "").strip().lower(),
        str((coverage.primary_source if coverage is not None else "") or "").strip().lower(),
        str((coverage.fallback_source if coverage is not None else "") or "").strip().lower(),
    ):
        if item and item in _SUPPORTED_PROBE_PROVIDERS and item not in sequence:
            sequence.append(item)
    if not sequence:
        sequence.append("yfinance")
    return sequence


def _probe_pin(provider: str, symbol: str, *, end_date: str) -> VersionPin:
    start_date = _probe_start_date(end_date)
    return VersionPin(
        version_id=f"{provider}:{symbol}:{start_date}:{end_date}:probe",
        source_ref=f"{provider}://{symbol}?start={start_date}&end={end_date}",
    )


def _probe_window(rows: list[dict[str, Any]]) -> AuditWindow | None:
    if not rows:
        return None
    return AuditWindow(
        start_date=str(rows[0].get("date") or ""),
        end_date=str(rows[-1].get("date") or ""),
        trading_days=len(rows),
        observed_days=len(rows),
        inferred_days=0,
    )


def _supports_live_probe(candidate: ProductCandidate, provider: str) -> bool:
    if provider != "yfinance":
        return True
    if candidate.wrapper_type in {"fund", "cash_mgmt"}:
        return False
    return True


def _derive_product_observability(
    candidate: ProductCandidate,
    *,
    historical_dataset: dict[str, Any],
    notes: list[str],
) -> dict[str, Any] | None:
    if not historical_dataset:
        return None
    source_name = str(historical_dataset.get("source_name") or "").strip() or "historical_dataset"
    source_ref = str(historical_dataset.get("source_ref") or "").strip()
    as_of = str(historical_dataset.get("as_of") or "")
    audit_window = AuditWindow.from_any(historical_dataset.get("audit_window"))
    coverage_status = str(historical_dataset.get("coverage_status") or "").strip().lower()
    if coverage_status not in {"verified", "observed", "fallback", "degraded"}:
        coverage_status = ""
    derived_notes = list(notes)
    derived_notes.append(
        "direct product probe unavailable; derived from observed market_history dataset and registry metadata"
    )
    return {
        "status": "observed",
        "tradable": True,
        "source_name": source_name,
        "source_ref": source_ref,
        "as_of": as_of,
        "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
        "audit_window": None if audit_window is None else audit_window.to_dict(),
        "notes": derived_notes,
        "coverage_status": coverage_status or None,
    }


def _probe_product_observability(
    candidate: ProductCandidate,
    *,
    as_of: str,
    cache_dir: Path,
    preferred_provider: str | None,
    historical_dataset: dict[str, Any] | None = None,
    provider_limits: dict[str, str] | None = None,
) -> dict[str, Any]:
    if candidate.asset_bucket == "cash_liquidity":
        return {
            "status": "observed",
            "tradable": True,
            "source_name": "account_liquidity_runtime",
            "source_ref": "account_raw:cash_liquidity",
            "as_of": _as_of_date(as_of),
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": None,
            "notes": ["cash/liquidity tradability derived from account-domain runtime context"],
        }

    cache = DatasetCache(base_dir=cache_dir)
    end_date = _as_of_date(as_of)
    failures: list[str] = []
    provider_failures = provider_limits if provider_limits is not None else {}
    for provider in _provider_sequence(candidate, preferred_provider=preferred_provider):
        if provider_failures.get(provider) == "rate_limited":
            failures.append(f"{provider}:rate_limited_short_circuit")
            continue
        if not _supports_live_probe(candidate, provider):
            failures.append(f"{provider}:unsupported_wrapper_for_live_probe")
            continue
        symbol = _symbol_for_provider(candidate, provider)
        if not symbol:
            failures.append(f"{provider}:missing_symbol")
            continue
        spec = DatasetSpec(kind="timeseries", dataset_id="runtime_product_universe", provider=provider, symbol=symbol)
        pin = _probe_pin(provider, symbol, end_date=end_date)
        try:
            rows, used_pin = fetch_timeseries(spec, pin=pin, cache=cache, allow_fallback=True, return_used_pin=True)
        except Exception as exc:
            rendered = str(exc)
            failures.append(f"{provider}:{rendered}")
            if "Too Many Requests" in rendered or "RateLimit" in rendered:
                provider_failures[provider] = "rate_limited"
            continue
        if not rows:
            failures.append(f"{provider}:empty_dataset")
            continue
        used_cached_pin = used_pin.version_id != pin.version_id
        notes = list(failures)
        if used_cached_pin:
            notes.append(f"{provider}:cache_fallback")
        return {
            "status": "observed",
            "tradable": True,
            "source_name": provider,
            "source_ref": str(used_pin.source_ref or pin.source_ref),
            "as_of": end_date,
            "data_status": (
                DataStatus.COMPUTED_FROM_OBSERVED.value if used_cached_pin else DataStatus.OBSERVED.value
            ),
            "audit_window": None if _probe_window(rows) is None else _probe_window(rows).to_dict(),
            "notes": notes,
        }
    derived = _derive_product_observability(
        candidate,
        historical_dataset=dict(historical_dataset or {}),
        notes=failures,
    )
    if derived is not None:
        return derived
    return {
        "status": "missing",
        "tradable": False,
        "source_name": preferred_provider or "runtime_probe",
        "source_ref": "",
        "as_of": end_date,
        "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
        "notes": failures,
        "reason": "probe_failed",
    }


def build_runtime_product_universe_context(
    *,
    market_raw: dict[str, Any] | None,
    as_of: str,
    cache_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    market = dict(market_raw or {})
    if market.get("product_universe_result") or market.get("runtime_product_universe_result"):
        inputs = dict(market.get("product_universe_inputs") or market.get("runtime_product_universe_inputs") or {})
        result = dict(market.get("product_universe_result") or market.get("runtime_product_universe_result") or {})
        return inputs, result

    effective_cache_dir = cache_dir or Path.home() / ".cache" / "investment_system" / "timeseries"
    if _tinyshare_has_token():
        candidates, result = load_tinyshare_runtime_catalog(
            as_of=_as_of_date(as_of),
            cache_dir=effective_cache_dir,
        )
        return {
            "requested": True,
            "require_observed_source": True,
            "source_kind": "tinyshare_runtime_catalog",
        }, result

    historical_dataset = dict(market.get("historical_dataset") or {})
    if not historical_dataset:
        return {"requested": False, "require_observed_source": True}, None

    preferred_provider = str(historical_dataset.get("source_name") or "").strip().lower() or None
    source_ref = str(historical_dataset.get("source_ref") or "")
    provider_limits: dict[str, str] = {}

    products: dict[str, Any] = {}
    observed_count = 0
    for candidate in load_builtin_catalog():
        payload = _probe_product_observability(
            candidate,
            as_of=as_of,
            cache_dir=effective_cache_dir,
            preferred_provider=preferred_provider,
            historical_dataset=historical_dataset,
            provider_limits=provider_limits,
        )
        products[candidate.product_id] = payload
        if str(payload.get("status") or "").strip().lower() == "observed":
            observed_count += 1

    inputs = {
        "requested": True,
        "require_observed_source": True,
        "source_kind": "runtime_product_universe_probe",
        "preferred_provider": preferred_provider,
    }
    result = {
        "source_status": "observed" if observed_count > 0 else "missing",
        "source_name": "runtime_product_universe",
        "source_ref": source_ref,
        "as_of": str(historical_dataset.get("as_of") or _as_of_date(as_of)),
        "products": products,
    }
    return inputs, result


def _observed_valuation_inputs(market_raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(market_raw.get("valuation_observations") or {})
    if payload:
        return payload
    payload = dict(market_raw.get("observed_valuation_inputs") or {})
    return payload


def build_runtime_product_valuation_context(
    *,
    market_raw: dict[str, Any] | None,
    as_of: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    market = dict(market_raw or {})
    existing_result = dict(market.get("product_valuation_result") or market.get("valuation_result") or {})
    if existing_result:
        inputs = dict(market.get("product_valuation_inputs") or market.get("valuation_inputs") or {})
        return inputs, existing_result

    if _tinyshare_has_token():
        runtime_candidates: list[ProductCandidate] = []
        universe_result = dict(market.get("product_universe_result") or market.get("runtime_product_universe_result") or {})
        for payload in list(universe_result.get("runtime_candidates") or []):
            if isinstance(payload, dict):
                runtime_candidates.append(ProductCandidate(**dict(payload)))
        if not runtime_candidates:
            runtime_candidates, _ = load_tinyshare_runtime_catalog(as_of=_as_of_date(as_of))
        result = build_tinyshare_runtime_valuation_result(runtime_candidates, as_of=_as_of_date(as_of))
        return {
            "requested": True,
            "require_observed_source": True,
            "source_kind": "tinyshare_runtime_valuation",
        }, result

    observed_inputs = _observed_valuation_inputs(market)
    if not observed_inputs:
        return {"requested": False, "require_observed_source": True}, None

    bucket_results = build_valuation_percentile_results(
        buckets=list(_VALUATION_BUCKETS),
        observed_inputs=observed_inputs,
        valuation_z_scores={},
        as_of=_as_of_date(as_of),
    )
    products: dict[str, Any] = {}
    source_name = "runtime_bucket_valuation_mapping"
    source_refs: set[str] = set()
    for candidate in load_builtin_catalog():
        if candidate.asset_bucket not in {"equity_cn", "satellite"} and candidate.wrapper_type != "stock":
            continue
        bucket_result = bucket_results.get(candidate.asset_bucket)
        if bucket_result is None:
            continue
        current_value = bucket_result.current_value
        metric_name = str(bucket_result.metric_name or "")
        pe_ratio = current_value if metric_name.startswith("pe") and current_value is not None else None
        source_refs.add(bucket_result.source_ref)
        products[candidate.product_id] = {
            "status": "observed" if pe_ratio is not None else "missing_metrics",
            "pe_ratio": pe_ratio,
            "pb_ratio": None,
            "percentile": float(bucket_result.percentile),
            "data_status": (
                DataStatus.COMPUTED_FROM_OBSERVED.value
                if bucket_result.data_status in {DataStatus.OBSERVED, DataStatus.COMPUTED_FROM_OBSERVED}
                else bucket_result.data_status.value
            ),
            "audit_window": None if bucket_result.audit_window is None else bucket_result.audit_window.to_dict(),
            "source_ref": bucket_result.source_ref,
            "as_of": bucket_result.as_of,
        }
    if not products:
        return {"requested": False, "require_observed_source": True}, None
    inputs = {
        "requested": True,
        "require_observed_source": True,
        "source_kind": "runtime_bucket_valuation_mapping",
    }
    result = {
        "source_status": "observed",
        "source_name": source_name,
        "source_ref": ",".join(sorted(source_refs)),
        "as_of": _as_of_date(as_of),
        "products": products,
    }
    return inputs, result


def enrich_market_raw_with_runtime_product_inputs(
    market_raw: dict[str, Any] | None,
    *,
    as_of: str,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(market_raw or {})
    universe_inputs, universe_result = build_runtime_product_universe_context(
        market_raw=enriched,
        as_of=as_of,
        cache_dir=cache_dir,
    )
    if universe_inputs.get("requested") or universe_result:
        enriched.setdefault("product_universe_inputs", universe_inputs)
        if universe_result is not None:
            enriched.setdefault("product_universe_result", universe_result)

    valuation_inputs, valuation_result = build_runtime_product_valuation_context(
        market_raw=enriched,
        as_of=as_of,
    )
    if valuation_inputs.get("requested") or valuation_result:
        enriched.setdefault("product_valuation_inputs", valuation_inputs)
        if valuation_result is not None:
            enriched.setdefault("product_valuation_result", valuation_result)
            enriched.setdefault("valuation_result", valuation_result)
    return enriched


__all__ = [
    "build_tinyshare_runtime_valuation_result",
    "build_runtime_product_universe_context",
    "build_runtime_product_valuation_context",
    "enrich_market_raw_with_runtime_product_inputs",
    "load_tinyshare_runtime_catalog",
]
