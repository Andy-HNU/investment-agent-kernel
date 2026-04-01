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


def _extract_number(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    raw = m.group(1).replace(',', '')
    try:
        return float(raw)
    except ValueError:
        return None


def route(text: str) -> Intent:
    t = text.strip().lower()
    if re.search(r"\bonboard(ing)?\b", t):
        return Intent(name="onboarding", confidence=0.95)
    if re.search(r"\bstatus|show status|how am i doing\b", t):
        return Intent(name="status", confidence=0.8)
    if re.search(r"\bmonthly|follow-?up|next month\b", t):
        return Intent(name="monthly", confidence=0.8)
    if re.search(r"\bapprove plan|confirm plan\b", t):
        return Intent(name="approve_plan", confidence=0.8)
    if re.search(r"\bexecuted|skipped|i did\b", t):
        return Intent(name="feedback", confidence=0.7)
    return Intent(name="unknown", confidence=0.1)


def parse_onboarding(text: str) -> dict[str, Any]:
    account_profile_id = _extract_first(r"user\s+([a-zA-Z0-9_\-]+)", text) or _extract_first(r"account\s+([a-zA-Z0-9_\-]+)", text) or "user001"
    display_name = _extract_first(r"name\s+([\w\-]+)", text, default=account_profile_id)
    current_total_assets = _extract_number(r"assets\s+([0-9,\.]+)", text) or 50000.0
    monthly_contribution = _extract_number(r"monthly\s+([0-9,\.]+)", text) or 10000.0
    goal_amount = _extract_number(r"goal\s+([0-9,\.]+)", text) or 1000000.0
    goal_horizon_months = int(_extract_number(r"(in|for)\s+([0-9]+)\s+months", text) or _extract_number(r"months?\s+([0-9]+)", text) or 60)
    risk_preference = _extract_first(r"risk\s+(low|moderate|medium|high|低|中等|高)", text) or "中等"
    risk_map = {"low": "保守", "moderate": "中等", "medium": "中等", "high": "激进", "低": "保守", "中等": "中等", "高": "激进"}
    risk_preference = risk_map.get(risk_preference.lower(), risk_preference)
    max_drawdown_tolerance = _extract_number(r"dd\s*=?\s*([0-9,\.]+)", text) or 0.1
    current_holdings = _extract_first(r"holdings?\s+([a-zA-Z0-9_\-]+)", text, default="cash")
    restrictions: list[str] = []
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
    account_profile_id = _extract_first(r"user\s+([a-zA-Z0-9_\-]+)", text) or _extract_first(r"account\s+([a-zA-Z0-9_\-]+)", text) or "user001"
    return {"account_profile_id": account_profile_id}

