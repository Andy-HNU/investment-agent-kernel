from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.historical import build_historical_dataset_snapshot, summarize_historical_dataset


DEFAULT_MARKET_HISTORY_CACHE_DIR = Path(
    "/root/AndyFtp/investment_system_codex_ready_repo/data/market_history_cache"
)

_DEFAULT_BUCKET_PROXY_MAP: dict[str, dict[str, str]] = {
    "equity_cn": {
        "provider": "akshare",
        "dataset_id": "cn_equity_core_daily",
        "symbol": "sh510300",
        "source_ref": "akshare://fund_etf_hist_sina",
    },
    "bond_cn": {
        "provider": "akshare",
        "dataset_id": "cn_bond_core_daily",
        "symbol": "sh511010",
        "source_ref": "akshare://fund_etf_hist_sina",
    },
    "gold": {
        "provider": "akshare",
        "dataset_id": "cn_gold_daily",
        "symbol": "sh518880",
        "source_ref": "akshare://fund_etf_hist_sina",
    },
    "satellite": {
        "provider": "akshare",
        "dataset_id": "cn_satellite_daily",
        "symbol": "sz159915",
        "source_ref": "akshare://fund_etf_hist_sina",
    },
}


@dataclass(frozen=True)
class RealSourceMarketSnapshot:
    provider_name: str
    fetched_at: str
    market_raw: dict[str, Any]
    historical_dataset_metadata: dict[str, Any]
    source_versions: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_as_of(as_of: str | None) -> datetime:
    rendered = str(as_of or "").strip()
    if not rendered:
        return datetime.now(timezone.utc)
    if rendered.endswith("Z"):
        rendered = rendered[:-1] + "+00:00"
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _version_token(as_of: datetime) -> str:
    return as_of.strftime("%Y%m%d")


def _close_series_to_returns(rows: list[dict[str, Any]], *, as_of_date: str) -> tuple[list[str], list[float], float]:
    filtered = [dict(row) for row in rows if str(row.get("date") or "") <= as_of_date]
    filtered.sort(key=lambda item: str(item.get("date") or ""))
    if len(filtered) < 2:
        raise RuntimeError("real-source history requires at least two rows")
    dates: list[str] = []
    returns: list[float] = []
    recent_volumes = [float(item.get("volume") or 0.0) for item in filtered[-20:]]
    recent_volume_mean = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0.0
    previous_close = float(filtered[0]["close"])
    for row in filtered[1:]:
        current_close = float(row["close"])
        if previous_close <= 0:
            previous_close = current_close
            continue
        returns.append((current_close / previous_close) - 1.0)
        dates.append(str(row["date"]))
        previous_close = current_close
    if not returns:
        raise RuntimeError("real-source history requires at least one return observation")
    return dates, returns, recent_volume_mean


def _normalize_liquidity_scores(volume_means: dict[str, float]) -> dict[str, float]:
    positive = [value for value in volume_means.values() if value > 0]
    if not positive:
        return {bucket: 0.5 for bucket in volume_means}
    low = min(positive)
    high = max(positive)
    if high <= low:
        return {bucket: 0.8 for bucket in volume_means}
    scores: dict[str, float] = {}
    for bucket, value in volume_means.items():
        if value <= 0:
            scores[bucket] = 0.5
            continue
        normalized = (value - low) / (high - low)
        scores[bucket] = round(0.5 + 0.45 * normalized, 4)
    return scores


def build_real_source_market_snapshot(
    *,
    as_of: str,
    cache_dir: str | Path = DEFAULT_MARKET_HISTORY_CACHE_DIR,
) -> RealSourceMarketSnapshot:
    resolved_cache_dir = Path(os.environ.get("INVESTMENT_MARKET_HISTORY_CACHE_DIR") or cache_dir)
    parsed_as_of = _parse_as_of(as_of)
    as_of_date = parsed_as_of.strftime("%Y-%m-%d")
    cache = DatasetCache(base_dir=resolved_cache_dir)
    bucket_series: dict[str, dict[str, float]] = {}
    bucket_dates: dict[str, list[str]] = {}
    volume_means: dict[str, float] = {}
    source_versions: dict[str, dict[str, str]] = {}

    for bucket, config in _DEFAULT_BUCKET_PROXY_MAP.items():
        spec = DatasetSpec(
            kind="timeseries",
            dataset_id=config["dataset_id"],
            provider=config["provider"],
            symbol=config["symbol"],
        )
        requested_pin = VersionPin(
            version_id=f"{config['provider']}:{config['symbol']}:{_version_token(parsed_as_of)}",
            source_ref=config["source_ref"],
        )
        rows, used_pin = fetch_timeseries(
            spec,
            pin=requested_pin,
            cache=cache,
            allow_fallback=True,
            return_used_pin=True,
        )
        dates, returns, recent_volume_mean = _close_series_to_returns(rows, as_of_date=as_of_date)
        bucket_dates[bucket] = dates
        bucket_series[bucket] = {date: value for date, value in zip(dates, returns, strict=True)}
        volume_means[bucket] = recent_volume_mean
        source_versions[bucket] = {
            "provider": config["provider"],
            "symbol": config["symbol"],
            "source_ref": used_pin.source_ref or config["source_ref"],
            "version_id": used_pin.version_id,
        }

    common_dates = sorted(set.intersection(*(set(dates) for dates in bucket_dates.values())))
    if len(common_dates) < 2:
        raise RuntimeError("real-source market history intersection is too short")

    return_series = {
        bucket: [bucket_series[bucket][date] for date in common_dates]
        for bucket in bucket_series
    }
    dataset = build_historical_dataset_snapshot(
        {
            "dataset_id": "real_source_market_history",
            "version_id": f"real_source_market_history:{_version_token(parsed_as_of)}",
            "as_of": parsed_as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source_name": "real_source_market_history",
            "source_ref": "|".join(
                f"{bucket}:{meta['provider']}:{meta['symbol']}:{meta['version_id']}"
                for bucket, meta in sorted(source_versions.items())
            ),
            "frequency": "daily",
            "lookback_months": max(1, round(len(common_dates) / 21)),
            "lookback_days": len(common_dates),
            "series_dates": common_dates,
            "return_series": return_series,
        }
    )
    if dataset is None:
        raise RuntimeError("failed to build real-source historical dataset")
    expected_returns, raw_volatility, _corr = summarize_historical_dataset(dataset)
    market_raw = {
        "provider_name": "real_source_market_history",
        "fetched_at": _iso_now(),
        "raw_volatility": raw_volatility,
        "liquidity_scores": _normalize_liquidity_scores(volume_means),
        "expected_returns": expected_returns,
        "historical_dataset": dataset.to_dict(),
    }
    return RealSourceMarketSnapshot(
        provider_name="real_source_market_history",
        fetched_at=market_raw["fetched_at"],
        market_raw=market_raw,
        historical_dataset_metadata=dataset.to_dict(),
        source_versions=source_versions,
    )


__all__ = ["DEFAULT_MARKET_HISTORY_CACHE_DIR", "RealSourceMarketSnapshot", "build_real_source_market_snapshot"]
