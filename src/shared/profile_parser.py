from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


_PERCENT_PATTERN = re.compile(r"(?P<value>\d{1,3}(?:\.\d+)?)\s*%")
_DIGIT_RATIO_PATTERN = re.compile(r"(?P<left>\d(?:\.\d+)?)\s*[:：/]\s*(?P<right>\d(?:\.\d+)?)")
_CN_RATIO_MAP = {
    "一九": (0.1, 0.9),
    "二八": (0.2, 0.8),
    "三七": (0.3, 0.7),
    "四六": (0.4, 0.6),
    "五五": (0.5, 0.5),
    "六四": (0.6, 0.4),
    "七三": (0.7, 0.3),
    "八二": (0.8, 0.2),
    "九一": (0.9, 0.1),
}
_CASH_WORDS = ("现金", "cash", "货基", "货币基金", "货币", "存款", "活期")
_EQUITY_WORDS = ("股票", "权益", "etf", "指数基金", "沪深300", "标普", "纳指", "nasdaq", "sp500")
_BOND_WORDS = ("债", "债券", "固收", "中短债", "国债", "信用债")
_GOLD_WORDS = ("黄金", "金", "gold")


@dataclass
class ParsedProfilePreferences:
    current_weights: dict[str, float] | None = None
    available_cash_fraction: float = 0.0
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)
    allowed_wrappers: list[str] = field(default_factory=list)
    forbidden_wrappers: list[str] = field(default_factory=list)
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)
    qdii_allowed: bool | None = None
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    holdings_parse_status: str = "not_attempted"
    restrictions_parse_status: str = "not_attempted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_weight_map(weights: dict[str, float], *, normalize_to: float = 1.0) -> dict[str, float]:
    cleaned = {key: max(float(value), 0.0) for key, value in weights.items() if float(value) > 0.0}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    target_total = max(float(normalize_to), 0.0)
    return {key: round((value / total) * target_total, 4) for key, value in cleaned.items()}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _parse_explicit_weight_tokens(text: str) -> tuple[dict[str, float] | None, float, list[str]]:
    normalized = text.lower().strip()
    notes: list[str] = []
    if not normalized:
        return None, 0.0, notes
    if any(phrase in normalized for phrase in ("纯黄金", "全仓黄金", "只有黄金")):
        return {"gold": 1.0}, 0.0, ["根据“纯黄金/全仓黄金”解析为黄金单一持仓。"]
    if any(phrase in normalized for phrase in ("全现金", "纯现金", "all cash", "cash only")):
        return {}, 1.0, ["根据“全现金/纯现金”解析为现金持仓。"]
    if "股债" in normalized:
        for token, (equity, bond) in _CN_RATIO_MAP.items():
            if token in normalized:
                return {"equity_cn": equity, "bond_cn": bond}, 0.0, [f"根据“股债{token}”解析仓位。"]
        ratio_match = _DIGIT_RATIO_PATTERN.search(normalized)
        if ratio_match:
            left = float(ratio_match.group("left"))
            right = float(ratio_match.group("right"))
            total = left + right
            if total > 0:
                return {"equity_cn": left / total, "bond_cn": right / total}, 0.0, ["根据“股债 x:y”解析仓位。"]

    percent_matches = list(_PERCENT_PATTERN.finditer(normalized))
    percents = [float(match.group("value")) / 100.0 for match in percent_matches]
    if len(percents) >= 2:
        allocations: list[tuple[str, float]] = []
        for index, match in enumerate(percent_matches):
            value = float(match.group("value")) / 100.0
            prev_end = percent_matches[index - 1].end() if index > 0 else 0
            next_start = percent_matches[index + 1].start() if index + 1 < len(percent_matches) else len(normalized)
            before = normalized[max(prev_end, match.start() - 8):match.start()]
            after = normalized[match.end():min(next_start, match.end() + 8)]
            context = f"{after} {before}".strip()
            if _contains_any(context, _GOLD_WORDS):
                allocations.append(("gold", value))
            elif _contains_any(context, _BOND_WORDS):
                allocations.append(("bond_cn", value))
            elif _contains_any(context, _CASH_WORDS):
                allocations.append(("cash", value))
            elif _contains_any(context, _EQUITY_WORDS):
                allocations.append(("equity_cn", value))
        if allocations:
            bucket_weights: dict[str, float] = {}
            cash_fraction = 0.0
            for bucket, value in allocations:
                if bucket == "cash":
                    cash_fraction += value
                else:
                    bucket_weights[bucket] = bucket_weights.get(bucket, 0.0) + value
            if bucket_weights or cash_fraction > 0:
                cash_fraction = min(max(cash_fraction, 0.0), 1.0)
                notes.append("根据显式百分比描述解析当前持仓。")
                return _normalize_weight_map(bucket_weights, normalize_to=max(1.0 - cash_fraction, 0.0)), cash_fraction, notes
    return None, 0.0, notes


def _parse_restrictions(restrictions: list[str]) -> ParsedProfilePreferences:
    parsed = ParsedProfilePreferences(restrictions_parse_status="parsed")
    normalized_items = [str(item).strip().lower() for item in restrictions if str(item).strip()]
    if not normalized_items:
        parsed.restrictions_parse_status = "not_provided"
        return parsed
    unmatched_items: list[str] = []
    for item in normalized_items:
        matched = False
        if "不碰股票" in item or "不买股票" in item or "不能买股票" in item:
            parsed.forbidden_wrappers.append("single_stock")
            parsed.notes.append("限制条件包含“不碰股票”，已编译为禁止个股，但允许 ETF/基金形式的权益暴露。")
            matched = True
        if "不碰科技" in item or "不买科技" in item or "不能买科技" in item:
            parsed.forbidden_themes.extend(["technology", "chip", "innovation"])
            parsed.notes.append("限制条件包含“不碰科技”，已编译为禁止科技/芯片/创新风格。")
            matched = True
        if "不买qdii" in item or "不碰qdii" in item or "不能买qdii" in item:
            parsed.qdii_allowed = False
            parsed.notes.append("限制条件包含“不买QDII”，已关闭 QDII。")
            matched = True
        if "只能黄金和现金" in item or "只要黄金和现金" in item:
            parsed.allowed_buckets = ["gold", "cash_liquidity"]
            parsed.forbidden_buckets.extend(["equity_cn", "bond_cn", "satellite"])
            parsed.notes.append("限制条件包含“只能黄金和现金”，当前产品 universe 会限制为黄金与现金/流动性。")
            parsed.requires_confirmation = True
            matched = True
        if not matched:
            unmatched_items.append(item)

    parsed.forbidden_buckets = sorted(set(parsed.forbidden_buckets))
    parsed.allowed_wrappers = sorted(set(parsed.allowed_wrappers))
    parsed.forbidden_wrappers = sorted(set(parsed.forbidden_wrappers))
    parsed.forbidden_themes = sorted(set(parsed.forbidden_themes))
    if unmatched_items and parsed.notes:
        parsed.restrictions_parse_status = "partial"
        parsed.requires_confirmation = True
        parsed.warnings.append(
            "以下限制条件未解析，尚未完全进入约束层: " + ", ".join(unmatched_items[:3])
        )
    elif not parsed.notes:
        parsed.restrictions_parse_status = "unparsed"
        parsed.requires_confirmation = True
        parsed.notes.append("限制条件未能稳定编译为标准约束，需人工确认。")
        parsed.warnings.append("限制条件存在未解析项，尚未完全进入约束层。")
    return parsed


def compile_profile_preferences(
    *,
    current_holdings: str,
    restrictions: list[str],
    explicit_current_weights: dict[str, float] | None = None,
) -> ParsedProfilePreferences:
    parsed = _parse_restrictions(restrictions)
    if explicit_current_weights is not None:
        weights = _normalize_weight_map(explicit_current_weights)
        parsed.current_weights = weights
        parsed.available_cash_fraction = max(0.0, 1.0 - sum(weights.values()))
        parsed.holdings_parse_status = "explicit_weights"
        parsed.notes.append("用户已显式提供 current_weights，优先使用。")
        return parsed

    weights, cash_fraction, notes = _parse_explicit_weight_tokens(current_holdings)
    if weights is None:
        lowered = str(current_holdings or "").strip().lower()
        if lowered:
            parsed.holdings_parse_status = "unparsed"
            parsed.requires_confirmation = True
            parsed.notes.append("当前持仓描述未能稳定解析，系统不会再静默套用通用默认仓位。")
            parsed.warnings.append("当前持仓描述未解析，需要确认或显式权重。")
        else:
            parsed.holdings_parse_status = "not_provided"
        return parsed

    parsed.current_weights = weights
    parsed.available_cash_fraction = cash_fraction
    parsed.holdings_parse_status = "parsed"
    parsed.notes.extend(notes)
    return parsed


def parse_profile_semantics(
    *,
    current_holdings: str,
    restrictions: list[str],
    explicit_current_weights: dict[str, float] | None = None,
) -> ParsedProfilePreferences:
    return compile_profile_preferences(
        current_holdings=current_holdings,
        restrictions=restrictions,
        explicit_current_weights=explicit_current_weights,
    )
