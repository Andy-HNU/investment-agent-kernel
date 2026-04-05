from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from product_mapping.types import ProductCandidate
from shared.audit import AuditWindow, DataStatus

_TOKEN_ENV = "TINYSHARE_TOKEN"
_TOKEN_FILE_ENV = "TINYSHARE_TOKEN_FILE"
_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST_ENV = "TINYSHARE_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST"
_CACHE_NAMESPACE = "tinyshare"

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
    for candidate in candidates:
        products[candidate.product_id] = {
            "status": "observed",
            "tradable": True,
            "source_name": "tinyshare_runtime_catalog",
            "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
            "as_of": as_of_date,
            "data_status": DataStatus.OBSERVED.value,
            "audit_window": None,
        }

    result = {
        "source_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
        "as_of": as_of_date,
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
            "stock_candidate_count": stock_candidate_count,
            "stock_candidate_signature": stock_candidate_signature,
        }
        _write_json_cache(cache_path, result)
        return result

    trade_date = _latest_trade_date(as_of_date, cache_dir=cache_dir, token=token)
    pro = _pro_api(token)
    products: dict[str, Any] = {}
    audit_window = AuditWindow(
        start_date=_normalize_iso_date(trade_date),
        end_date=_normalize_iso_date(trade_date),
        trading_days=1,
        observed_days=1,
        inferred_days=0,
    )
    df = pro.daily_basic(trade_date=trade_date, fields="ts_code,trade_date,pe,pe_ttm,pb")
    by_code: dict[str, dict[str, Any]] = {}
    if df is not None and not getattr(df, "empty", True):
        for _, row in df.iterrows():
            payload = row.to_dict()
            ts_code = str(payload.get("ts_code") or "").strip().upper()
            if ts_code:
                by_code[ts_code] = payload

    for candidate in stock_candidates:
        row = by_code.get(str(candidate.provider_symbol or "").strip().upper())
        if not row:
            continue
        pe_ratio = row.get("pe") or row.get("pe_ttm")
        pb_ratio = row.get("pb")
        if pe_ratio is None:
            continue
        percentile = min(max(float(pe_ratio) / 80.0, 0.0), 1.0)
        products[candidate.product_id] = {
            "status": "observed",
            "pe_ratio": float(pe_ratio),
            "pb_ratio": None if pb_ratio is None else float(pb_ratio),
            "percentile": percentile,
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": asdict(audit_window),
            "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}&ts_code={candidate.provider_symbol}",
            "as_of": as_of_date,
        }

    result = {
        "source_status": "observed" if products else "missing",
        "source_name": "tinyshare_runtime_valuation",
        "source_ref": f"tinyshare://daily_basic?trade_date={trade_date}",
        "as_of": as_of_date,
        "products": products,
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
