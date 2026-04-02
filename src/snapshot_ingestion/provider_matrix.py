from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


VerificationStatus = Literal["planned", "in_progress", "verified", "degraded", "blocked"]
CoverageLevel = Literal["none", "partial", "full"]


@dataclass(frozen=True)
class ProviderCoverageRecord:
    asset_class: str
    region: str
    primary_source: str | None
    fallback_source: str | None
    degraded_source: str | None
    realtime_support: CoverageLevel
    historical_support: CoverageLevel
    verified_status: VerificationStatus
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_BUILTIN_PROVIDER_CAPABILITY_MATRIX: tuple[ProviderCoverageRecord, ...] = (
    ProviderCoverageRecord(
        asset_class="a_share_equity",
        region="CN",
        primary_source="akshare",
        fallback_source="baostock",
        degraded_source="efinance",
        realtime_support="partial",
        historical_support="partial",
        verified_status="in_progress",
        notes=["A 股主源", "低频抓取优先", "verified slice 先锁定 TX 指数历史路径", "历史序列走缓存落账"],
    ),
    ProviderCoverageRecord(
        asset_class="hong_kong_equity",
        region="HK",
        primary_source="akshare",
        fallback_source="yfinance",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="planned",
        notes=["港股覆盖保留为第一版扩展"],
    ),
    ProviderCoverageRecord(
        asset_class="us_equity",
        region="US",
        primary_source="yfinance",
        fallback_source="yahooquery",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="full",
        verified_status="planned",
        notes=["美股/海外交叉验证"],
    ),
    ProviderCoverageRecord(
        asset_class="etf",
        region="GLOBAL",
        primary_source="akshare",
        fallback_source="yfinance",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="in_progress",
        notes=["支持宽基/红利/行业/风格 ETF 产品层映射", "AKShare ETF 历史路径未完成独立 live/replay 验证"],
    ),
    ProviderCoverageRecord(
        asset_class="public_fund",
        region="CN",
        primary_source="akshare",
        fallback_source="efinance",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="planned",
        notes=["公募基金估值/净值"],
    ),
    ProviderCoverageRecord(
        asset_class="bond",
        region="CN",
        primary_source="akshare",
        fallback_source="manual_snapshot",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="in_progress",
        notes=["债券/国债/政金债"],
    ),
    ProviderCoverageRecord(
        asset_class="gold",
        region="CN",
        primary_source="akshare",
        fallback_source="manual_snapshot",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="in_progress",
        notes=["黄金 ETF / 联接基金"],
    ),
    ProviderCoverageRecord(
        asset_class="cash_liquidity",
        region="CN",
        primary_source="manual_snapshot",
        fallback_source="manual_snapshot",
        degraded_source="manual_snapshot",
        realtime_support="full",
        historical_support="none",
        verified_status="verified",
        notes=["现金类/货基/短债替代由账户快照主导"],
    ),
    ProviderCoverageRecord(
        asset_class="qdii",
        region="GLOBAL",
        primary_source="akshare",
        fallback_source="yfinance",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="partial",
        verified_status="planned",
        notes=["QDII 保持可选，不默认强依赖"],
    ),
    ProviderCoverageRecord(
        asset_class="broad_style_industry_index",
        region="CN",
        primary_source="akshare",
        fallback_source="baostock",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="full",
        verified_status="in_progress",
        notes=["行业指数/宽基指数/风格指数"],
    ),
    ProviderCoverageRecord(
        asset_class="news_feed",
        region="CN",
        primary_source="http_json_public_news",
        fallback_source="manual_snapshot",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="none",
        verified_status="planned",
        notes=["新闻只进入结构化 sidecar，不直接进入 solver 数学"],
    ),
    ProviderCoverageRecord(
        asset_class="policy_source",
        region="CN",
        primary_source="official_policy_site",
        fallback_source="manual_snapshot",
        degraded_source="manual_snapshot",
        realtime_support="partial",
        historical_support="none",
        verified_status="planned",
        notes=["政策原文优先官网"],
    ),
    ProviderCoverageRecord(
        asset_class="account_raw",
        region="ACCOUNT",
        primary_source="manual_snapshot",
        fallback_source="http_json",
        degraded_source="manual_snapshot",
        realtime_support="full",
        historical_support="none",
        verified_status="verified",
        notes=["第一版以手工快照和 http_json broker proxy 为主"],
    ),
    ProviderCoverageRecord(
        asset_class="live_portfolio",
        region="ACCOUNT",
        primary_source="manual_snapshot",
        fallback_source="http_json",
        degraded_source="manual_snapshot",
        realtime_support="full",
        historical_support="none",
        verified_status="verified",
        notes=["组合快照会进入 freshness / provenance / fallback 链"],
    ),
)


def load_provider_capability_matrix() -> list[ProviderCoverageRecord]:
    return list(_BUILTIN_PROVIDER_CAPABILITY_MATRIX)


def provider_capability_matrix_dicts() -> list[dict[str, Any]]:
    return [record.to_dict() for record in load_provider_capability_matrix()]


def find_provider_coverage(asset_class: str) -> ProviderCoverageRecord | None:
    target = str(asset_class).strip().lower()
    for record in _BUILTIN_PROVIDER_CAPABILITY_MATRIX:
        if record.asset_class.lower() == target:
            return record
    return None


__all__ = [
    "ProviderCoverageRecord",
    "find_provider_coverage",
    "load_provider_capability_matrix",
    "provider_capability_matrix_dicts",
]
