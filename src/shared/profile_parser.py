from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


_PERCENT_PATTERN = re.compile(r"(?P<value>\d{1,3}(?:\.\d+)?)\s*%")
_DIGIT_RATIO_PATTERN = re.compile(r"(?P<left>\d(?:\.\d+)?)\s*[:：/]\s*(?P<right>\d(?:\.\d+)?)")
_NUMBER_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>万|w|k|千)?", re.IGNORECASE)
_RESTRICTION_CLAUSE_SPLIT_PATTERN = re.compile(r"[，,、；;]+|(?:而且)|(?:并且)|(?:以及)")
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
_CANONICAL_FORBIDDEN_THEME_PREFIX = "forbidden_theme:"
_CANONICAL_FORBIDDEN_WRAPPER_PREFIX = "forbidden_wrapper:"
_CANONICAL_FORBIDDEN_REGION_PREFIX = "forbidden_region:"


@dataclass
class ParsedProfilePreferences:
    current_weights: dict[str, float] | None = None
    available_cash_fraction: float = 0.0
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)
    allowed_wrappers: list[str] = field(default_factory=list)
    forbidden_wrappers: list[str] = field(default_factory=list)
    allowed_regions: list[str] = field(default_factory=list)
    forbidden_regions: list[str] = field(default_factory=list)
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)
    forbidden_risk_labels: list[str] = field(default_factory=list)
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


def _classify_bucket_from_context(before: str, after: str, *, prefer_after: bool) -> str | None:
    ordered_contexts = (str(after or "").strip(), str(before or "").strip()) if prefer_after else (
        str(before or "").strip(),
        str(after or "").strip(),
    )
    for context in ordered_contexts:
        lowered = context.lower()
        if not lowered:
            continue
        if _contains_any(lowered, _CASH_WORDS):
            return "cash"
        if _contains_any(lowered, _GOLD_WORDS):
            return "gold"
        if _contains_any(lowered, _BOND_WORDS):
            return "bond_cn"
        if _contains_any(lowered, _EQUITY_WORDS):
            return "equity_cn"
    return None


def _split_restriction_clauses(restrictions: list[str]) -> list[str]:
    clauses: list[str] = []
    for item in restrictions:
        rendered = str(item).strip()
        if not rendered:
            continue
        parts = [part.strip() for part in _RESTRICTION_CLAUSE_SPLIT_PATTERN.split(rendered) if part.strip()]
        if parts:
            clauses.extend(parts)
        else:
            clauses.append(rendered)
    return clauses


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
            bucket = _classify_bucket_from_context(before, after, prefer_after=True)
            if bucket is not None:
                allocations.append((bucket, value))
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
    amount_matches = list(_NUMBER_PATTERN.finditer(normalized))
    if amount_matches:
        allocations: list[tuple[str, float]] = []
        for index, match in enumerate(amount_matches):
            value = float(match.group("value"))
            unit = str(match.group("unit") or "").lower()
            if unit in {"万", "w"}:
                value *= 10_000.0
            elif unit in {"k", "千"}:
                value *= 1_000.0
            prev_end = amount_matches[index - 1].end() if index > 0 else 0
            next_start = amount_matches[index + 1].start() if index + 1 < len(amount_matches) else len(normalized)
            before = normalized[max(prev_end, match.start() - 8):match.start()]
            after = normalized[match.end():min(next_start, match.end() + 8)]
            bucket = _classify_bucket_from_context(before, after, prefer_after=False)
            if bucket is not None:
                allocations.append((bucket, value))
        if allocations:
            bucket_amounts: dict[str, float] = {}
            cash_amount = 0.0
            for bucket, value in allocations:
                if bucket == "cash":
                    cash_amount += value
                else:
                    bucket_amounts[bucket] = bucket_amounts.get(bucket, 0.0) + value
            total_amount = cash_amount + sum(bucket_amounts.values())
            if total_amount > 0:
                cash_fraction = min(max(cash_amount / total_amount, 0.0), 1.0)
                notes.append("根据显式金额描述解析当前持仓。")
                return _normalize_weight_map(bucket_amounts, normalize_to=max(1.0 - cash_fraction, 0.0)), cash_fraction, notes
    return None, 0.0, notes


def _parse_restrictions(restrictions: list[str]) -> ParsedProfilePreferences:
    parsed = ParsedProfilePreferences(restrictions_parse_status="parsed")
    normalized_items = [item.lower() for item in _split_restriction_clauses(restrictions)]
    if not normalized_items:
        parsed.restrictions_parse_status = "not_provided"
        return parsed
    unmatched_items: list[str] = []
    for item in normalized_items:
        matched = False
        if item in {"no_stock_picking", "no_stock_wrapper"} or item == "forbidden_wrapper:stock":
            parsed.forbidden_wrappers.append("stock")
            parsed.notes.append("限制条件包含 canonical token no_stock_picking，已编译为禁止股票包装，不影响 ETF/基金权益敞口。")
            matched = True
        elif item.startswith(_CANONICAL_FORBIDDEN_WRAPPER_PREFIX):
            wrapper = item.split(":", 1)[1].strip().lower()
            if wrapper:
                parsed.forbidden_wrappers.append(wrapper)
                parsed.notes.append(f"限制条件包含 canonical token forbidden_wrapper:{wrapper}，已编译为包装过滤。")
                matched = True
        if item.startswith(_CANONICAL_FORBIDDEN_THEME_PREFIX):
            theme = item.split(":", 1)[1].strip().lower()
            if theme:
                parsed.forbidden_themes.append(theme)
                parsed.notes.append(f"限制条件包含 canonical token forbidden_theme:{theme}，已编译为主题过滤。")
                matched = True
        if item in {"no_qdii", "forbidden_region:non_cn"}:
            parsed.qdii_allowed = False
            parsed.forbidden_regions.append("non_cn")
            parsed.notes.append("限制条件包含 canonical token no_qdii，已关闭非 CN / QDII 产品。")
            matched = True
        elif item.startswith(_CANONICAL_FORBIDDEN_REGION_PREFIX):
            region = item.split(":", 1)[1].strip().upper()
            if region:
                parsed.forbidden_regions.append(region)
                parsed.notes.append(f"限制条件包含 canonical token forbidden_region:{region.lower()}，已编译为区域过滤。")
                matched = True
        if item in {"only_gold_and_cash", "gold_and_cash_only"}:
            parsed.allowed_buckets = ["gold", "cash_liquidity"]
            parsed.forbidden_buckets.extend(["equity_cn", "bond_cn", "satellite"])
            parsed.notes.append("限制条件包含 canonical token only_gold_and_cash，当前产品 universe 会近似为黄金单桶并保留现金为未投资部分。")
            parsed.requires_confirmation = True
            matched = True
        if item in {"no_high_risk_products", "forbidden_risk:high"}:
            parsed.forbidden_risk_labels.append("high_risk_product")
            parsed.notes.append("限制条件包含 canonical token no_high_risk_products，已编译为高风险产品过滤。")
            matched = True
        if "不碰股票" in item or "不买股票" in item or "不能买股票" in item or "不碰个股" in item or "不买个股" in item or "不能买个股" in item:
            parsed.forbidden_wrappers.append("stock")
            parsed.notes.append("限制条件包含“不碰股票/个股”，已编译为禁止股票包装，不影响 ETF/基金权益敞口。")
            matched = True
        if "不碰科技" in item or "不买科技" in item or "不能买科技" in item:
            parsed.forbidden_themes.append("technology")
            parsed.notes.append("限制条件包含“不碰科技”，已编译为 technology 主题过滤。")
            matched = True
        if "不碰高风险产品" in item or "不买高风险产品" in item or "不能买高风险产品" in item:
            parsed.forbidden_risk_labels.append("high_risk_product")
            parsed.notes.append("限制条件包含“不碰高风险产品”，已编译为高风险产品过滤。")
            matched = True
        if "不买qdii" in item or "不碰qdii" in item or "不能买qdii" in item:
            parsed.qdii_allowed = False
            parsed.forbidden_regions.append("non_cn")
            parsed.notes.append("限制条件包含“不买QDII”，已关闭非 CN / QDII 产品。")
            matched = True
        if "只能黄金和现金" in item or "只要黄金和现金" in item:
            parsed.allowed_buckets = ["gold", "cash_liquidity"]
            parsed.forbidden_buckets.extend(["equity_cn", "bond_cn", "satellite"])
            parsed.notes.append("限制条件包含“只能黄金和现金”，当前产品 universe 会近似为黄金单桶并保留现金为未投资部分。")
            parsed.requires_confirmation = True
            matched = True
        if not matched:
            unmatched_items.append(item)

    parsed.forbidden_buckets = sorted(set(parsed.forbidden_buckets))
    parsed.forbidden_wrappers = sorted(set(parsed.forbidden_wrappers))
    parsed.forbidden_regions = sorted(set(parsed.forbidden_regions))
    parsed.forbidden_themes = sorted(set(parsed.forbidden_themes))
    parsed.forbidden_risk_labels = sorted(set(parsed.forbidden_risk_labels))
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
        raw_weights = {
            str(key): max(float(value), 0.0)
            for key, value in dict(explicit_current_weights).items()
            if float(value) > 0.0
        }
        total = sum(raw_weights.values())
        explicit_cash_weight = float(
            raw_weights.get("cash_liquidity", raw_weights.get("cash", 0.0)) or 0.0
        )
        if total <= 0.0:
            weights = {}
            cash_fraction = 1.0
        elif total <= 1.0 + 1e-6:
            weights = {key: round(value, 4) for key, value in raw_weights.items()}
            cash_fraction = 0.0 if explicit_cash_weight > 0.0 else max(0.0, 1.0 - total)
        else:
            weights = _normalize_weight_map(raw_weights)
            cash_fraction = max(0.0, 1.0 - sum(weights.values()))
        parsed.current_weights = weights
        parsed.available_cash_fraction = round(cash_fraction, 4)
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
