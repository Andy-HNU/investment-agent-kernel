from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from product_mapping.types import ProductCandidate, ProductUniverseItem, ProductUniverseSnapshot
from shared.audit import AuditWindow, DataStatus

_TOKEN_ENV = "TINYSHARE_TOKEN"
_TOKEN_FILE_ENV = "TINYSHARE_TOKEN_FILE"
_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST_ENV = "TINYSHARE_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST"
_CACHE_NAMESPACE = "tinyshare"
_VALUATION_CACHE_FORMAT_VERSION = 3

_SATELLITE_KEYWORDS = {
    "芯片": "technology",
    "半导体": "technology",
    "机器人": "technology",
    "人工智能": "technology",
    "计算机": "technology",
    "软件": "technology",
    "科技": "technology",
    "新能源": "cyclical",
    "能源": "cyclical",
    "军工": "cyclical",
    "医药": "healthcare",
    "消费": "consumer",
    "恒生科技": "technology",
    "纳斯达克": "technology",
}

_INDUSTRY_THEME_MAP = {
    "银行": "defensive",
    "非银金融": "defensive",
    "证券": "defensive",
    "保险": "defensive",
    "石油": "cyclical",
    "煤炭": "cyclical",
    "电力设备": "cyclical",
    "有色金属": "cyclical",
    "基础化工": "cyclical",
    "机械设备": "cyclical",
    "汽车": "cyclical",
    "家用电器": "consumer",
    "食品饮料": "consumer",
    "商贸零售": "consumer",
    "医药生物": "healthcare",
    "电子": "technology",
    "计算机": "technology",
    "通信": "technology",
    "传媒": "technology",
}


def _market_label(candidate: ProductCandidate) -> str:
    region = str(candidate.region or "CN").upper()
    if region in {"CN", "HK", "US"}:
        return region
    return region or "CN"


def _universe_item(candidate: ProductCandidate, *, as_of: str, source_ref: str) -> ProductUniverseItem:
    return ProductUniverseItem(
        product_id=candidate.product_id,
        ts_code=str(candidate.provider_symbol or "").strip() or None,
        wrapper=candidate.wrapper_type,
        asset_bucket=candidate.asset_bucket,
        market=_market_label(candidate),
        region=str(candidate.region or "").strip().upper() or None,
        theme_tags=sorted({str(tag).strip().lower() for tag in candidate.tags if str(tag).strip()}),
        risk_labels=sorted({str(label).strip() for label in candidate.risk_labels if str(label).strip()}),
        source_ref=source_ref,
        data_status=DataStatus.OBSERVED.value,
        as_of=as_of,
    )


def _percentile_from_values(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    ordered = sorted(float(item) for item in population)
    less_or_equal = sum(1 for item in ordered if item <= value)
    return round(max(min(less_or_equal / len(ordered), 1.0), 0.0), 6)


def has_token() -> bool:
    if os.getenv(_TOKEN_ENV, "").strip():
        return True
    return _read_token_file() is not None


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def _token_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = str(os.getenv(_TOKEN_FILE_ENV, "")).strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    under_pytest = bool(str(os.getenv("PYTEST_CURRENT_TEST", "")).strip())
    allow_repo_token_under_pytest = str(os.getenv(_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST_ENV, "")).strip() == "1"
    if not under_pytest or allow_repo_token_under_pytest:
        candidates.append(_repo_root() / ".secrets" / "tinyshare.token")
    return candidates


def _read_token_file() -> str | None:
    for path in _token_file_candidates():
        try:
            if path.exists():
                token = path.read_text(encoding="utf-8").strip()
                if token:
                    return token
        except Exception:
            continue
    return None


def _require_token(token: str | None = None) -> str:
    resolved = str(token or os.getenv(_TOKEN_ENV, "")).strip() or str(_read_token_file() or "").strip()
    if not resolved:
        raise RuntimeError(
            "tinyshare provider unavailable - set TINYSHARE_TOKEN or provide .secrets/tinyshare.token"
        )
    return resolved


def _pro_api(token: str | None = None):
    try:
        import tinyshare as ts  # type: ignore
    except Exception as exc:  # pragma: no cover - install error
        raise RuntimeError("tinyshare provider unavailable - install tinyshare") from exc
    return ts.pro_api(_require_token(token))


def _cache_path(cache_dir: Path | None, name: str, *, as_of: str) -> Path:
    base = cache_dir or (Path.home() / ".cache" / "investment_system" / _CACHE_NAMESPACE)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{name}_{as_of}.json"


def _read_json_cache(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _normalize_iso_date(value: str) -> str:
    if not value:
        return value
    if len(value) == 8 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _trade_date(text: str) -> str:
    return _normalize_iso_date(text).replace("-", "")


def _latest_trade_date(as_of: str, *, cache_dir: Path | None = None, token: str | None = None) -> str:
    as_of_date = _normalize_iso_date(str(as_of).split("T", 1)[0])
    cache_path = _cache_path(cache_dir, "trade_cal", as_of=as_of_date)
    cached = _read_json_cache(cache_path)
    if isinstance(cached, dict) and cached.get("latest_trade_date"):
        return str(cached["latest_trade_date"])
    pro = _pro_api(token)
    start = (date.fromisoformat(as_of_date) - timedelta(days=14)).strftime("%Y%m%d")
    end = date.fromisoformat(as_of_date).strftime("%Y%m%d")
    df = pro.trade_cal(exchange="", start_date=start, end_date=end)
    if df is None or getattr(df, "empty", True):
        raise RuntimeError("tinyshare_trade_cal_empty")
    latest = None
    for _, row in df.iterrows():
        if str(row.get("is_open") or row.get("is_trading") or "0") == "1":
            latest = str(row.get("cal_date") or row.get("trade_date") or "")
    if not latest:
        raise RuntimeError("tinyshare_trade_cal_no_open_day")
    payload = {"latest_trade_date": latest}
    _write_json_cache(cache_path, payload)
    return latest


def _normalize_history_rows(df: Any, *, ts_code: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if df is None or getattr(df, "empty", True):
        return rows
    for _, row in df.iterrows():
        date_value = _normalize_iso_date(str(row.get("trade_date") or row.get("date") or ""))
        rows.append(
            {
                "date": date_value,
                "open": float(row.get("open")),
                "high": float(row.get("high")),
                "low": float(row.get("low")),
                "close": float(row.get("close")),
                "volume": float(row.get("vol") or row.get("volume") or 0.0),
                "ts_code": ts_code,
            }
        )
    rows.sort(key=lambda item: item["date"])
    return rows


def _stock_candidate_signature(candidates: list[ProductCandidate]) -> tuple[int, str]:
    stock_entries = sorted(
        {
            f"{candidate.product_id}:{str(candidate.provider_symbol or '').strip().upper()}"
            for candidate in candidates
            if candidate.wrapper_type == "stock" and str(candidate.provider_symbol or "").strip()
        }
    )
    digest = hashlib.sha1(",".join(stock_entries).encode("utf-8")).hexdigest()
    return len(stock_entries), digest


def fetch_history_rows(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    ts_code = str(symbol or "").strip().upper()
    if not ts_code:
        raise ValueError("tinyshare provider requires spec.symbol")
    pro = _pro_api(token)
    is_fund = ts_code.startswith(("5", "1", "15", "16")) or ts_code.endswith((".OF",))
    start_compact = _trade_date(start_date)
    end_compact = _trade_date(end_date)
    if is_fund:
        df = pro.fund_daily(ts_code=ts_code, start_date=start_compact, end_date=end_compact)
    else:
        df = pro.daily(ts_code=ts_code, start_date=start_compact, end_date=end_compact)
    rows = _normalize_history_rows(df, ts_code=ts_code)
    if not rows:
        raise RuntimeError("tinyshare_empty_dataset")
    return rows


def _stock_runtime_candidate(row: dict[str, Any]) -> ProductCandidate:
    ts_code = str(row.get("ts_code") or "").strip().upper()
    name = str(row.get("name") or ts_code)
    industry = str(row.get("industry") or "").strip()
    tags = ["equity", "stock_wrapper", "cn"]
    if industry:
        tags.append(industry.lower())
        for keyword, theme in _INDUSTRY_THEME_MAP.items():
            if keyword in industry and theme not in tags:
                tags.append(theme)
    return ProductCandidate(
        product_id=f"ts_stock_{ts_code.lower().replace('.', '_')}",
        product_name=name,
        asset_bucket="equity_cn",
        product_family="a_share_stock",
        wrapper_type="stock",
        provider_source="tinyshare_stock_basic",
        provider_symbol=ts_code,
        tags=tags,
        risk_labels=["个股波动", "集中度"],
        notes=["runtime candidate sourced from tinyshare stock_basic"],
    )


def _infer_fund_bucket(name: str, fund_type: str, invest_type: str) -> str:
    rendered = f"{name} {fund_type} {invest_type}"
    if "黄金" in rendered:
        return "gold"
    if any(token in rendered for token in ("债", "固收", "政金", "国债", "短融", "中票")):
        return "bond_cn"
    if any(token in rendered for token in ("货币", "现金管理", "现金")):
        return "cash_liquidity"
    if any(token in rendered for token in _SATELLITE_KEYWORDS):
        return "satellite"
    if any(token in rendered for token in ("QDII", "海外", "港股", "美股", "标普", "纳指", "恒生")):
        return "satellite"
    return "equity_cn"


def _infer_fund_tags(name: str, fund_type: str, invest_type: str, bucket: str) -> list[str]:
    rendered = f"{name} {fund_type} {invest_type}"
    tags: list[str] = [bucket]
    if "ETF" in rendered:
        tags.append("etf")
    if "QDII" in rendered or any(token in rendered for token in ("海外", "港股", "美股", "标普", "纳指", "恒生")):
        tags.extend(["qdii", "overseas"])
    if bucket == "equity_cn":
        tags.append("core")
    if bucket == "bond_cn":
        tags.extend(["defense", "bond"])
    if bucket == "gold":
        tags.append("gold")
    if bucket == "cash_liquidity":
        tags.extend(["cash", "liquidity"])
    for token, tag in _SATELLITE_KEYWORDS.items():
        if token in rendered and tag not in tags:
            tags.append(tag)
    return tags


def _infer_fund_risk_labels(bucket: str, tags: list[str]) -> list[str]:
    if bucket == "bond_cn":
        return ["利率波动"]
    if bucket == "gold":
        return ["商品波动"]
    if bucket == "cash_liquidity":
        return ["低收益"]
    labels = ["权益波动"]
    if "technology" in tags or bucket == "satellite":
        labels.append("主题波动")
    if "qdii" in tags or "overseas" in tags:
        labels.extend(["汇率波动", "海外市场"])
    return labels


def _fund_runtime_candidate(row: dict[str, Any]) -> ProductCandidate | None:
    ts_code = str(row.get("ts_code") or "").strip().upper()
    name = str(row.get("name") or "").strip()
    if not ts_code or not name:
        return None
    status = str(row.get("status") or "").strip().upper()
    if status and status not in {"L", "I", "D"}:
        return None
    fund_type = str(row.get("fund_type") or row.get("type") or "").strip()
    invest_type = str(row.get("invest_type") or "").strip()
    bucket = _infer_fund_bucket(name, fund_type, invest_type)
    tags = _infer_fund_tags(name, fund_type, invest_type, bucket)
    wrapper = "etf" if "ETF" in name.upper() or str(row.get("market") or "").upper() == "E" else "fund"
    region = "CN"
    currency = "CNY"
    if "海外" in tags or "qdii" in tags:
        region = "US" if any(token in name for token in ("标普", "纳指", "美股")) else "HK" if "恒生" in name else "US"
        currency = "USD" if region == "US" else "HKD"
    return ProductCandidate(
        product_id=f"ts_fund_{ts_code.lower().replace('.', '_')}",
        product_name=name,
        asset_bucket=bucket,
        product_family=f"{bucket}_runtime_fund",
        wrapper_type=wrapper,
        provider_source="tinyshare_fund_basic",
        provider_symbol=ts_code,
        region=region,
        currency=currency,
        tags=tags,
        risk_labels=_infer_fund_risk_labels(bucket, tags),
        notes=["runtime candidate sourced from tinyshare fund_basic"],
    )


def _market_label(candidate: ProductCandidate) -> str:
    if str(candidate.region or "").upper() == "HK":
        return "HK"
    if str(candidate.region or "").upper() == "US":
        return "US"
    return "CN"


def _runtime_universe_item(
    candidate: ProductCandidate,
    *,
    as_of_date: str,
    source_ref: str,
) -> dict[str, Any]:
    return ProductUniverseItem(
        product_id=candidate.product_id,
        ts_code=str(candidate.provider_symbol or "").strip() or None,
        wrapper=candidate.wrapper_type,
        asset_bucket=candidate.asset_bucket,
        market=_market_label(candidate),
        region=str(candidate.region or "").strip() or None,
        theme_tags=list(candidate.tags),
        risk_labels=list(candidate.risk_labels),
        source_ref=source_ref,
        data_status=DataStatus.OBSERVED.value,
        as_of=as_of_date,
    ).to_dict()


def load_runtime_catalog(*, as_of: str, cache_dir: Path | None = None, token: str | None = None) -> tuple[list[ProductCandidate], dict[str, Any]]:
    as_of_date = _normalize_iso_date(str(as_of).split("T", 1)[0])
    cache_path = _cache_path(cache_dir, "runtime_catalog", as_of=as_of_date)
    cached = _read_json_cache(cache_path)
    if isinstance(cached, dict) and isinstance(cached.get("runtime_candidates"), list):
        candidates = [ProductCandidate(**dict(item)) for item in list(cached["runtime_candidates"])]
        return candidates, dict(cached)

    pro = _pro_api(token)
    stock_df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry,market,list_date")
    fund_df = pro.fund_basic(market="", status="")
    candidates: list[ProductCandidate] = []
    products: dict[str, Any] = {}
    for _, row in stock_df.iterrows():
        candidate = _stock_runtime_candidate(dict(row))
        candidates.append(candidate)
    for _, row in fund_df.iterrows():
        candidate = _fund_runtime_candidate(dict(row))
        if candidate is None:
            continue
        candidates.append(candidate)

    candidates = [candidate for candidate in candidates if candidate.enabled]
    source_ref = "tinyshare://runtime_catalog?markets=stocks,funds"
    wrapper_counts: dict[str, int] = {}
    asset_bucket_counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        wrapper_counts[candidate.wrapper_type] = wrapper_counts.get(candidate.wrapper_type, 0) + 1
        asset_bucket_counts[candidate.asset_bucket] = asset_bucket_counts.get(candidate.asset_bucket, 0) + 1
        items.append(_runtime_universe_item(candidate, as_of_date=as_of_date, source_ref=source_ref))
        products[candidate.product_id] = {
            "status": "observed",
            "tradable": True,
            "source_name": "tinyshare_runtime_catalog",
            "source_ref": source_ref,
            "as_of": as_of_date,
            "data_status": DataStatus.OBSERVED.value,
            "audit_window": None,
        }

    result = {
        "snapshot_id": f"tinyshare_runtime_catalog_{as_of_date}",
        "source_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": source_ref,
        "as_of": as_of_date,
        "data_status": DataStatus.OBSERVED.value,
        "item_count": len(items),
        "items": items,
        "audit_window": {
            "start_date": as_of_date,
            "end_date": as_of_date,
            "trading_days": 1,
            "observed_days": 1,
            "inferred_days": 0,
        },
        "source_names": ["tinyshare_fund_basic", "tinyshare_stock_basic"],
        "wrapper_counts": wrapper_counts,
        "asset_bucket_counts": asset_bucket_counts,
        "products": products,
        "runtime_candidates": [candidate.to_dict() for candidate in candidates],
    }
    _write_json_cache(cache_path, result)
    return candidates, result


def build_runtime_valuation_result(
    candidates: list[ProductCandidate],
    *,
    as_of: str,
    cache_dir: Path | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    as_of_date = _normalize_iso_date(str(as_of).split("T", 1)[0])
    cache_path = _cache_path(cache_dir, "runtime_valuation", as_of=as_of_date)
    stock_candidates = [candidate for candidate in candidates if candidate.wrapper_type == "stock"]
    stock_candidate_count, stock_candidate_signature = _stock_candidate_signature(stock_candidates)
    cached = _read_json_cache(cache_path)
    if (
        isinstance(cached, dict)
        and isinstance(cached.get("products"), dict)
        and int(cached.get("cache_format_version") or 0) >= _VALUATION_CACHE_FORMAT_VERSION
        and int(cached.get("stock_candidate_count") or 0) == stock_candidate_count
        and str(cached.get("stock_candidate_signature") or "") == stock_candidate_signature
    ):
        return dict(cached)

    if not stock_candidates:
        result = {
            "source_status": "missing",
            "source_name": "tinyshare_runtime_valuation",
            "source_ref": "tinyshare://daily_basic?trade_date=not_applicable",
            "as_of": as_of_date,
            "products": {},
            "bucket_proxies": {},
            "cache_format_version": _VALUATION_CACHE_FORMAT_VERSION,
            "stock_candidate_count": stock_candidate_count,
            "stock_candidate_signature": stock_candidate_signature,
        }
        _write_json_cache(cache_path, result)
        return result

    trade_date = _latest_trade_date(as_of_date, cache_dir=cache_dir, token=token)
    pro = _pro_api(token)
    products: dict[str, Any] = {}
    bucket_proxies: dict[str, Any] = {}
    theme_proxies: dict[str, Any] = {}
    window_start = (date.fromisoformat(_normalize_iso_date(trade_date)) - timedelta(days=365)).strftime("%Y%m%d")
    history_df = pro.daily_basic(
        start_date=window_start,
        end_date=trade_date,
        fields="ts_code,trade_date,pe,pe_ttm,pb",
    )
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if history_df is not None and not getattr(history_df, "empty", True):
        for _, row in history_df.iterrows():
            payload = row.to_dict()
            ts_code = str(payload.get("ts_code") or "").strip().upper()
            trade_day = _normalize_iso_date(str(payload.get("trade_date") or ""))
            if not ts_code or not trade_day:
                continue
            by_code[ts_code].append(payload)
            by_date[trade_day].append(payload)

    for candidate in stock_candidates:
        rows = sorted(
            by_code.get(str(candidate.provider_symbol or "").strip().upper(), []),
            key=lambda item: str(item.get("trade_date") or ""),
        )
        if not rows:
            continue
        latest_row = rows[-1]
        pe_ratio = latest_row.get("pe") or latest_row.get("pe_ttm")
        pb_ratio = latest_row.get("pb")
        if pe_ratio is None:
            continue
        history_values = [
            float(row.get("pe") or row.get("pe_ttm"))
            for row in rows
            if row.get("pe") is not None or row.get("pe_ttm") is not None
        ]
        percentile = _percentile_from_values(float(pe_ratio), history_values)
        candidate_audit_window = AuditWindow(
            start_date=_normalize_iso_date(str(rows[0].get("trade_date") or "")),
            end_date=_normalize_iso_date(str(rows[-1].get("trade_date") or "")),
            trading_days=len(rows),
            observed_days=len(rows),
            inferred_days=0,
        )
        products[candidate.product_id] = {
            "status": "observed",
            "pe_ratio": float(pe_ratio),
            "pb_ratio": None if pb_ratio is None else float(pb_ratio),
            "percentile": percentile,
            "valuation_mode": "direct_observed",
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": asdict(candidate_audit_window),
            "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}&ts_code={candidate.provider_symbol}",
            "as_of": as_of_date,
        }

    equity_pe_values = [float(payload["pe_ratio"]) for payload in products.values() if payload.get("pe_ratio") is not None]
    if equity_pe_values:
        equity_proxy_pe = float(median(equity_pe_values))
        equity_history_values: list[float] = []
        for trade_day in sorted(by_date):
            values = [
                float(row.get("pe") or row.get("pe_ttm"))
                for row in by_date[trade_day]
                if row.get("pe") is not None or row.get("pe_ttm") is not None
            ]
            if values:
                equity_history_values.append(float(median(values)))
        equity_audit_window = AuditWindow(
            start_date=_normalize_iso_date(str(min(by_date) if by_date else trade_date)),
            end_date=_normalize_iso_date(str(max(by_date) if by_date else trade_date)),
            trading_days=len(equity_history_values) or 1,
            observed_days=len(equity_history_values) or 1,
            inferred_days=0,
        )
        bucket_proxies["equity_cn"] = {
            "status": "observed",
            "pe_ratio": equity_proxy_pe,
            "pb_ratio": None,
            "percentile": _percentile_from_values(equity_proxy_pe, equity_history_values or [equity_proxy_pe]),
            "valuation_mode": "index_proxy",
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": asdict(equity_audit_window),
            "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}&subject=equity_cn_proxy",
            "as_of": as_of_date,
        }

    themed_values: dict[str, list[float]] = {}
    for candidate in stock_candidates:
        product_payload = products.get(candidate.product_id)
        if not product_payload:
            continue
        pe_value = product_payload.get("pe_ratio")
        if pe_value is None:
            continue
        normalized_tags = {str(tag).strip().lower() for tag in candidate.tags}
        for theme in {"technology", "cyclical", "consumer", "healthcare", "defensive"}:
            if theme in normalized_tags:
                themed_values.setdefault(theme, []).append(float(pe_value))
    for theme, values in themed_values.items():
        if not values:
            continue
        proxy_pe = float(median(values))
        themed_codes = {
            str(candidate.provider_symbol or "").strip().upper()
            for candidate in stock_candidates
            if theme in {str(tag).strip().lower() for tag in candidate.tags}
        }
        theme_history_values: list[float] = []
        for trade_day in sorted(by_date):
            values_for_day = [
                float(row.get("pe") or row.get("pe_ttm"))
                for row in by_date[trade_day]
                if str(row.get("ts_code") or "").strip().upper() in themed_codes
                and (row.get("pe") is not None or row.get("pe_ttm") is not None)
            ]
            if values_for_day:
                theme_history_values.append(float(median(values_for_day)))
        theme_audit_window = AuditWindow(
            start_date=_normalize_iso_date(str(min(by_date) if by_date else trade_date)),
            end_date=_normalize_iso_date(str(max(by_date) if by_date else trade_date)),
            trading_days=len(theme_history_values) or 1,
            observed_days=len(theme_history_values) or 1,
            inferred_days=0,
        )
        theme_proxies[theme] = {
            "status": "observed",
            "pe_ratio": proxy_pe,
            "pb_ratio": None,
            "percentile": _percentile_from_values(proxy_pe, theme_history_values or [proxy_pe]),
            "valuation_mode": "holdings_proxy",
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": asdict(theme_audit_window),
            "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}&theme={theme}",
            "as_of": as_of_date,
        }

    result = {
        "source_status": "observed" if products else "missing",
        "source_name": "tinyshare_runtime_valuation",
        "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}",
        "as_of": as_of_date,
        "products": products,
        "bucket_proxies": bucket_proxies,
        "theme_proxies": theme_proxies,
        "cache_format_version": _VALUATION_CACHE_FORMAT_VERSION,
        "stock_candidate_count": stock_candidate_count,
        "stock_candidate_signature": stock_candidate_signature,
    }
    _write_json_cache(cache_path, result)
    return result


__all__ = [
    "_pro_api",
    "build_runtime_valuation_result",
    "fetch_history_rows",
    "has_token",
    "load_runtime_catalog",
]
