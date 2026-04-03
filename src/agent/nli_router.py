from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Intent:
    name: str
    confidence: float


def _extract_first(pattern: str, text: str, *, group: int = 1, default: Optional[str] = None) -> Optional[str]:
    m = re.search(pattern, text, flags=re.I)
    return m.group(group) if m else default


def _extract_number(pattern: str, text: str, *, group: int = 1) -> Optional[float]:
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    raw = m.group(group).replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_account_profile_id(text: str) -> str:
    return (
        _extract_first(r"\buser\s+([a-zA-Z0-9_\-:]+)", text)
        or _extract_first(r"\baccount\s+([a-zA-Z0-9_\-:]+)", text)
        or _extract_first(r"用户\s*([a-zA-Z0-9_\-:]+)", text)
        or _extract_first(r"账户\s*([a-zA-Z0-9_\-:]+)", text)
        or "user001"
    )


def route_intent(text: str) -> str:
    return route(text).name


def route(text: str) -> Intent:
    t = text.strip()
    tl = t.lower()

    rules: list[tuple[str, list[str], float]] = [
        ("onboarding", [r"\bonboard(ing)?\b", r"建档", r"新用户", r"开户"], 0.9),
        ("sync_portfolio_ocr", [r"\bocr\b", r"ocr", r"截图.*识别", r"截图.*同步持仓"], 0.95),
        ("sync_portfolio_import", [r"\bcsv\b", r"导入.*(持仓|账单|对账单)", r"import.*(statement|portfolio)"], 0.92),
        ("sync_portfolio_manual", [r"手工.*同步持仓", r"手工.*录入持仓", r"sync.*portfolio"], 0.9),
        ("approve_plan", [r"approve[-_\s]?plan", r"confirm\s+plan", r"批准计划", r"确认计划"], 0.9),
        ("show_user", [r"show[-_\s]?user", r"查看(用户|档案|画像)", r"展示(用户|档案)"], 0.85),
        ("status", [r"/status\b", r"\bstatus\b", r"show status", r"用户状态", r"账户状态"], 0.85),
        ("quarterly", [r"\bquarterly\b", r"季度(复核|复盘|检查|回顾)"], 0.9),
        ("monthly", [r"\bmonthly\b", r"follow-?up", r"月度(复核|复盘|检查|回顾)", r"下个月"], 0.85),
        ("event", [r"\bevent\b", r"事件(复核|检查|触发)", r"突发", r"大跌"], 0.82),
        ("daily_monitor", [r"监控", r"止盈止损", r"\bmonitor\b"], 0.88),
        ("explain_data_basis", [r"历史数据", r"推算历史", r"数据依据", r"数据基础"], 0.94),
        ("explain_execution_policy", [r"执行策略", r"季度执行策略", r"止盈止损规则"], 0.92),
        ("explain_plan_change", [r"计划变化", r"为什么.*替换.*计划", r"plan change", r"replace.*plan"], 0.9),
        ("explain_probability", [r"目标达成率", r"成功率", r"概率.*怎么", r"why.*probability"], 0.92),
        ("feedback", [r"已执行", r"已跳过", r"\bexecuted\b", r"\bskipped\b", r"\bi did\b", r"执行反馈"], 0.8),
    ]
    for name, patterns, confidence in rules:
        if any(re.search(pattern, tl if "\\b" in pattern else t, flags=re.I) for pattern in patterns):
            return Intent(name=name, confidence=confidence)
    return Intent(name="unknown", confidence=0.1)


def _extract_chinese_assets(text: str) -> Optional[float]:
    section = _extract_first(r"(?:目前有|现在有)(.+?)(?:每月|目标|风险|$)", text, default="") or ""
    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*万", section)
    if not matches:
        return None
    return float(sum(float(item) * 10000 for item in matches))


def parse_onboarding(text: str) -> dict[str, Any]:
    account_profile_id = _extract_account_profile_id(text)
    display_name = _extract_first(r"name\s+([\w\-]+)", text, default=account_profile_id) or account_profile_id
    current_total_assets = (
        _extract_number(r"assets?\s+([0-9,\.]+)", text)
        or _extract_number(r"总资产[:：]?\s*([0-9,\.]+)", text)
        or _extract_chinese_assets(text)
        or 50000.0
    )
    monthly_contribution = (
        _extract_number(r"monthly\s+([0-9,\.]+)", text)
        or _extract_number(r"每月(?:能)?(?:投入|定投|存款)?[:：]?\s*([0-9,\.]+)", text)
        or 10000.0
    )
    goal_amount = (
        _extract_number(r"goal\s+([0-9,\.]+)", text)
        or _extract_number(r"目标(?:金额|资产)?[:：]?\s*([0-9,\.]+)", text)
        or 1000000.0
    )
    months = (
        _extract_number(r"in\s+([0-9]+)\s+months", text)
        or _extract_number(r"for\s+([0-9]+)\s+months", text)
        or _extract_number(r"([0-9]+)\s*个月", text)
    )
    years = _extract_number(r"([0-9]+)\s*年", text)
    goal_horizon_months = int(months or ((years or 0.0) * 12) or 60)

    risk_token = (
        _extract_first(r"risk\s+(low|moderate|medium|high|低|中等|高)", text)
        or ("低" if re.search(r"(不喜欢炒股|不碰高风险|低风险)", text) else None)
        or "中等"
    )
    risk_map = {"low": "保守", "moderate": "中等", "medium": "中等", "high": "激进", "低": "保守", "中等": "中等", "高": "激进"}
    risk_preference = risk_map.get(str(risk_token).lower(), str(risk_token))
    max_drawdown_tolerance = _extract_number(r"dd\s*=?\s*([0-9,\.]+)", text) or 0.1
    current_holdings = _extract_first(r"holdings?\s+([a-zA-Z0-9_\-%\s]+)", text, default="cash") or "cash"

    restrictions: list[str] = []
    if re.search(r"不买股票|不碰股票", text):
        restrictions.append("不买股票")
    if re.search(r"不碰高风险|高风险产品", text):
        restrictions.append("不碰高风险产品")
    restrictions = list(dict.fromkeys(restrictions))

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
    return {"account_profile_id": _extract_account_profile_id(text)}


def parse_followup(text: str) -> dict[str, Any]:
    return {"account_profile_id": _extract_account_profile_id(text)}
