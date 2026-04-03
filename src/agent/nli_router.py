from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Intent:
    name: str
    confidence: float


def _extract_first(pattern: str, text: str, *, group: int = 1, default: Optional[str] = None) -> Optional[str]:
    match = re.search(pattern, text, flags=re.I)
    return match.group(group).strip() if match else default


def _normalized_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _to_float(raw: str | None) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _extract_number(pattern: str, text: str, *, group: int = 1) -> Optional[float]:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    return _to_float(match.group(group))


def _extract_money_value(text: str, patterns: list[str]) -> Optional[float]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = _to_float(match.group(1))
        if value is None:
            continue
        unit = (match.group(2) if match.lastindex and match.lastindex >= 2 else "") or ""
        if unit.lower() == "w" or unit == "万":
            value *= 10_000
        return value
    return None


def _extract_total_assets(text: str) -> Optional[float]:
    direct = _extract_money_value(
        text,
        [
            r"(?:assets?|total assets?|总资产|当前总资产)\s*[:=：]?\s*([0-9][0-9,\.]*)\s*(万|w|元)?",
        ],
    )
    if direct is not None:
        return direct
    holdings = list(
        re.finditer(
            r"([0-9][0-9,\.]*)\s*(万|w|元)?\s*(现金|黄金|股票|债券|基金|纳指|沪深|ETF)",
            text,
            flags=re.I,
        )
    )
    if not holdings:
        return None
    total = 0.0
    for match in holdings:
        raw_value, unit, _label = match.groups()
        prefix = text[max(0, match.start() - 12):match.start()].lower()
        if any(cue in prefix for cue in ("每月", "monthly", "月投", "月存", "月供", "月收", "月会")):
            continue
        value = _to_float(raw_value)
        if value is None:
            continue
        if (unit or "").lower() == "w" or unit == "万":
            value *= 10_000
        total += value
    return total or None


def _extract_horizon_months(text: str) -> Optional[int]:
    for pattern in (
        r"(?:in|for)\s*([0-9]+)\s*months?\b",
        r"([0-9]+)\s*months?\b",
        r"([0-9]+)\s*个?月",
    ):
        value = _extract_number(pattern, text)
        if value is not None:
            return max(int(round(value)), 1)
    year_value = _extract_number(r"([0-9]+(?:\.[0-9]+)?)\s*年", text)
    if year_value is not None:
        return max(int(round(year_value * 12)), 1)
    return None


def _extract_annual_return_target(text: str) -> Optional[float]:
    for pattern in (
        r"(?:年化收益率|年化收益|annual(?:ized)? return)\s*[:=：]?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:的\s*)?(?:年化|annualized)",
    ):
        value = _extract_number(pattern, text)
        if value is not None:
            return value / 100.0
    return None


def _derive_goal_amount(
    *,
    current_total_assets: float | None,
    monthly_contribution: float | None,
    goal_horizon_months: int | None,
    annual_return_target: float | None,
) -> Optional[float]:
    if (
        current_total_assets is None
        or monthly_contribution is None
        or goal_horizon_months is None
        or annual_return_target is None
    ):
        return None
    if goal_horizon_months <= 0:
        return None
    monthly_rate = math.pow(1.0 + annual_return_target, 1.0 / 12.0) - 1.0
    growth = math.pow(1.0 + monthly_rate, goal_horizon_months)
    if abs(monthly_rate) < 1e-9:
        contribution_fv = monthly_contribution * goal_horizon_months
    else:
        contribution_fv = monthly_contribution * ((growth - 1.0) / monthly_rate)
    return round(current_total_assets * growth + contribution_fv, 2)


def _infer_risk_preference(text: str) -> str:
    normalized = text.lower()
    if re.search(r"(保守|低风险|不喜欢炒股|不碰股票|股市风险很大|风险很大)", normalized):
        return "保守"
    if re.search(r"(激进|进取|高风险|risk high|aggressive)", normalized):
        return "进取"
    explicit = _extract_first(r"(?:risk|风险偏好)\s*[:=：]?\s*(low|moderate|medium|high|保守|中等|进取|激进)", normalized)
    mapping = {
        "low": "保守",
        "moderate": "中等",
        "medium": "中等",
        "high": "进取",
        "保守": "保守",
        "中等": "中等",
        "进取": "进取",
        "激进": "进取",
    }
    return mapping.get(explicit or "", "中等")


def _infer_max_drawdown_tolerance(text: str, *, risk_preference: str) -> float:
    dd = _extract_number(r"(?:dd|max drawdown|最大回撤)\s*[:=：]?\s*([0-9]+(?:\.[0-9]+)?)\s*%?", text)
    if dd is not None:
        return dd / 100.0 if dd > 1 else dd
    return {"保守": 0.08, "中等": 0.12, "进取": 0.18}.get(risk_preference, 0.10)


def _extract_holdings_text(text: str) -> str:
    explicit = _extract_first(r"(?:holdings?|持仓)\s*[:=：]?\s*(.+?)(?:[。.!]|$)", text)
    if explicit:
        return explicit
    if re.search(r"(现金|黄金|股票|债券|基金|ETF|仓位)", text):
        return _normalized_text(text)
    return "cash"


def _extract_restrictions(text: str) -> list[str]:
    restrictions: list[str] = []
    normalized = text.lower()
    if re.search(r"(不碰股票|不买股票|不能买股票|不喜欢炒股|股市风险很大)", normalized):
        restrictions.append("不碰股票")
    if re.search(r"(只接受黄金和现金|只能黄金和现金|只要黄金和现金)", normalized):
        restrictions.append("只接受黄金和现金")
    if re.search(r"(不买qdii|不碰qdii|不能买qdii)", normalized):
        restrictions.append("不买QDII")
    return restrictions


def route(text: str) -> Intent:
    t = _normalized_text(text).lower()
    if re.search(r"(why|为什么).*(replace|plan|方案|替换|变更)", t):
        return Intent(name="explain_plan_change", confidence=0.92)
    if re.search(r"(why|为什么).*(probability|success|达成率|概率)", t):
        return Intent(name="explain_probability", confidence=0.92)
    if re.search(r"(\bapprove plan\b|\bconfirm plan\b|\bpromote\b|批准方案|确认方案|采用方案)", t):
        return Intent(name="approve_plan", confidence=0.95)
    if re.search(r"(\bshow[- ]user\b|\bshow user\b|\bshow profile\b|展示用户|用户全貌|查看用户快照)", t):
        return Intent(name="show_user", confidence=0.9)
    if re.search(r"(季度|季检|季度复查|\bquarterly\b|\bquarter review\b|\bquarterly review\b)", t):
        return Intent(name="quarterly", confidence=0.88)
    if re.search(r"(executed|skipped|i did|took action|已执行|跳过|没执行|未执行|暂不执行)", t):
        return Intent(name="feedback", confidence=0.86)
    if re.search(r"(\bshow status\b|\bstatus\b|\bhow am i doing\b|\bcheck user\b|状态查询|查看状态|近况)", t):
        return Intent(name="status", confidence=0.84)
    if re.search(r"(事件|回撤|大跌|突发|\bevent\b|\bdrawdown\b|\bselloff\b)", t):
        return Intent(name="event", confidence=0.84)
    if re.search(r"(\bonboard\b|\bonboarding\b|\bcreate profile\b|\bnew user\b|新用户|建档|开户|画像)", t):
        return Intent(name="onboarding", confidence=0.96)
    if re.search(r"(月度|月检|月度复查|\bmonthly\b|\bfollow-?up\b|\bnext month\b)", t):
        return Intent(name="monthly", confidence=0.84)

    has_profile_shape = any(
        token in t
        for token in (
            "新用户",
            "建档",
            "画像",
            "每月",
            "总资产",
            "goal",
            "目标",
            "年化",
        )
    )
    if has_profile_shape:
        return Intent(name="onboarding", confidence=0.7)
    return Intent(name="unknown", confidence=0.1)


def parse_onboarding(text: str) -> dict[str, Any]:
    normalized = _normalized_text(text)
    account_profile_id = (
        _extract_first(r"(?:user|account|用户|账户(?:名|id)?)\s*[:=：]?\s*([a-zA-Z0-9_\-]+)", normalized)
        or _extract_first(r"我是\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})", normalized)
        or "user001"
    )
    display_name = (
        _extract_first(r"(?:name|我叫|叫|昵称)\s*[:=：]?\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})", normalized)
        or account_profile_id
    )
    current_total_assets = _extract_total_assets(normalized) or 50_000.0
    monthly_contribution = _extract_money_value(
        normalized,
        [
            r"(?:monthly|每月(?:投入|定投|投资|存款|存入|可投)?)(?:\s*(?:contribution|deposit))?\s*[:=：]?\s*([0-9][0-9,\.]*)\s*(万|w|元)?",
            r"(?:每月(?:会收到|收到|会有|有)|monthly(?:\s+cash)?)\s*([0-9][0-9,\.]*)\s*(万|w|元)?",
        ],
    ) or 10_000.0
    goal_amount = _extract_money_value(
        normalized,
        [
            r"(?:goal|目标(?:金额|资产)?)\s*[:=：]?\s*([0-9][0-9,\.]*)\s*(万|w|元)?",
            r"(?:达到|到达)\s*([0-9][0-9,\.]*)\s*(万|w|元)?",
        ],
    )
    goal_horizon_months = _extract_horizon_months(normalized) or 60
    annual_return_target = _extract_annual_return_target(normalized)
    if goal_amount is None:
        goal_amount = _derive_goal_amount(
            current_total_assets=current_total_assets,
            monthly_contribution=monthly_contribution,
            goal_horizon_months=goal_horizon_months,
            annual_return_target=annual_return_target,
        ) or 1_000_000.0
    risk_preference = _infer_risk_preference(normalized)
    max_drawdown_tolerance = _infer_max_drawdown_tolerance(normalized, risk_preference=risk_preference)
    current_holdings = _extract_holdings_text(normalized)
    restrictions = _extract_restrictions(normalized)
    return {
        "account_profile_id": account_profile_id,
        "display_name": display_name,
        "current_total_assets": current_total_assets,
        "monthly_contribution": monthly_contribution,
        "goal_amount": goal_amount,
        "goal_horizon_months": goal_horizon_months,
        "risk_preference": risk_preference,
        "max_drawdown_tolerance": max_drawdown_tolerance,
        "current_holdings": current_holdings,
        "restrictions": restrictions,
    }


def parse_status(text: str) -> dict[str, Any]:
    account_profile_id = (
        _extract_first(r"\bfor\s+user\s+([a-zA-Z0-9_\-]+)", text)
        or _extract_first(r"(?<!-)\buser\s*[:=：]?\s*([a-zA-Z0-9_\-]+)", text)
        or _extract_first(r"\baccount\s*[:=：]?\s*([a-zA-Z0-9_\-]+)", text)
        or _extract_first(r"(?:用户|账户(?:名|id)?)\s*[:=：]?\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", text)
        or "user001"
    )
    return {"account_profile_id": account_profile_id}


def parse_approve_plan(text: str) -> dict[str, Any]:
    account = parse_status(text)
    version = (
        _extract_number(r"(?:version|版本)\s*[:=：]?\s*([0-9]+)", text)
        or _extract_number(r"\bv([0-9]+)\b", text)
        or 1
    )
    plan_id = (
        _extract_first(r"(?:plan(?:[_ ]?id)?|方案)\s*[:=：]?\s*([^\s,，]+)", text)
        or _extract_first(r"(?:approve plan|confirm plan|promote|批准方案|确认方案|采用方案)\s+([^\s,，]+)", text)
    )
    if plan_id in {"for", "user", "账户", "用户"} or re.fullmatch(r"v?\d+", str(plan_id or ""), flags=re.I):
        plan_id = None
    return {**account, "plan_id": plan_id, "plan_version": int(version)}


def parse_feedback(text: str) -> dict[str, Any]:
    account = parse_status(text)
    run_id = (
        _extract_first(r"(?:run(?:[_ -]?id)?|运行(?:编号|ID)?)\s*[:=：]?\s*([^\s,，]+)", text)
        or ""
    )
    executed = None
    if re.search(r"(executed|i did|已执行|执行了)", text, flags=re.I):
        executed = True
    elif re.search(r"(skipped|未执行|没执行|跳过|暂不执行)", text, flags=re.I):
        executed = False
    actual_action = _extract_first(r"(?:actual(?:[_ ]?action)?|动作)\s*[:=：]?\s*([^\s,，]+)", text)
    note = _extract_first(r"(?:note|备注)\s*[:=：]?\s*(.+)$", text)
    return {
        **account,
        "run_id": run_id,
        "executed": executed,
        "actual_action": actual_action,
        "note": note,
    }


def parse_event_context(text: str) -> dict[str, Any]:
    normalized = text.lower()
    event_context: dict[str, Any] = {}
    if re.search(r"(drawdown|selloff|回撤|大跌|暴跌)", normalized):
        event_context["drawdown_event"] = True
        event_context["manual_review_requested"] = True
    if re.search(r"(manual review|人工复核|人工审核)", normalized):
        event_context["manual_review_requested"] = True
    if re.search(r"(override|手动覆盖)", normalized):
        event_context["manual_override_requested"] = True
    if re.search(r"(?:do not|don't|不要|别|暂不|先不).{0,8}(rebalance|调仓|满仓|抄底)", normalized):
        event_context["manual_review_requested"] = True
    elif re.search(r"(rebalance|调仓|满仓|抄底|高风险)", normalized):
        event_context["high_risk_request"] = True
        event_context["requested_action"] = "rebalance_full"
    return event_context
