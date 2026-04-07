from __future__ import annotations

import json
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


def _default_drawdown_tolerance(risk_preference: str) -> float:
    normalized = str(risk_preference or "").strip().lower()
    return {
        "保守": 0.10,
        "中等": 0.20,
        "激进": 0.30,
        "low": 0.10,
        "moderate": 0.20,
        "medium": 0.20,
        "high": 0.30,
    }.get(normalized, 0.10)


def route(text: str) -> Intent:
    t = text.strip().lower()
    if re.search(r"\bsync\s+portfolio\b|\bupdate\s+portfolio\b|\bsync holdings\b", t):
        return Intent(name="sync_portfolio", confidence=0.9)
    if re.search(r"\bdaily\s+monitor\b|\bmonitor\b.*\bportfolio\b|\bmonitor\b.*\bposition", t):
        return Intent(name="daily_monitor", confidence=0.85)
    if re.search(r"\bexplain\b.*\bprobability\b|\bwhy\b.*\bprobability\b", t):
        return Intent(name="explain_probability", confidence=0.85)
    if re.search(r"\bexplain\b.*\bplan\b.*\bchange\b|\bplan diff\b|\bplan change\b", t):
        return Intent(name="explain_plan_change", confidence=0.85)
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
    target_annual_return = _extract_number(r"(?:annual|年化)\s*([0-9,\.]+)%?", text)
    goal_amount = _extract_number(r"goal\s+([0-9,\.]+)", text) or (0.0 if target_annual_return is not None else 1000000.0)
    goal_horizon_months = int(
        _extract_first(r"(?:in|for)\s+([0-9]+)\s+months", text)
        or _extract_first(r"months?\s+([0-9]+)", text)
        or 60
    )
    risk_preference = _extract_first(r"risk\s+(low|moderate|medium|high|低|中等|高)", text) or "中等"
    risk_map = {"low": "保守", "moderate": "中等", "medium": "中等", "high": "激进", "低": "保守", "中等": "中等", "高": "激进"}
    risk_preference = risk_map.get(risk_preference.lower(), risk_preference)
    max_drawdown_tolerance = _extract_number(r"dd\s*=?\s*([0-9,\.]+)", text)
    if max_drawdown_tolerance is None:
        max_drawdown_tolerance = _default_drawdown_tolerance(risk_preference)
    current_holdings = _extract_first(r"holdings?\s+([a-zA-Z0-9_\-]+)", text, default="cash")
    restrictions: list[str] = []
    return {
        "account_profile_id": account_profile_id,
        "display_name": display_name,
        "current_total_assets": current_total_assets,
        "monthly_contribution": monthly_contribution,
        "goal_amount": goal_amount,
        "goal_horizon_months": goal_horizon_months,
        "target_annual_return": None if target_annual_return is None else float(target_annual_return) / (100.0 if float(target_annual_return) > 1.0 else 1.0),
        "risk_preference": risk_preference,
        "max_drawdown_tolerance": max_drawdown_tolerance,
        "current_holdings": current_holdings,
        "restrictions": restrictions,
    }


def parse_status(text: str) -> dict[str, Any]:
    account_profile_id = _extract_first(r"user\s+([a-zA-Z0-9_\-]+)", text) or _extract_first(r"account\s+([a-zA-Z0-9_\-]+)", text) or "user001"
    return {"account_profile_id": account_profile_id}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def parse_sync_portfolio(text: str) -> dict[str, Any]:
    account_profile_id = parse_status(text)["account_profile_id"]
    payload = _extract_json_object(text) or {}
    if not payload:
        total = _extract_number(r"\btotal\s+([0-9,\.]+)", text)
        cash = _extract_number(r"\bcash\s+([0-9,\.]+)", text)
        gold = _extract_number(r"\bgold\s+([0-9,\.]+)", text)
        equity = _extract_number(r"\bequity\s+([0-9,\.]+)", text)
        bond = _extract_number(r"\bbond\s+([0-9,\.]+)", text)
        satellite = _extract_number(r"\bsatellite\s+([0-9,\.]+)", text)
        weights: dict[str, float] = {}
        if total and total > 0:
            if equity:
                weights["equity_cn"] = round(equity / total, 6)
            if bond:
                weights["bond_cn"] = round(bond / total, 6)
            if gold:
                weights["gold"] = round(gold / total, 6)
            if cash:
                weights["cash_liquidity"] = round(cash / total, 6)
            if satellite:
                weights["satellite"] = round(satellite / total, 6)
        payload = {
            "snapshot_id": f"sync_{account_profile_id}",
            "source_kind": "manual_json",
            "total_value": total,
            "available_cash": cash,
            "weights": weights,
            "holdings": [],
        }
    return {
        "account_profile_id": account_profile_id,
        "observed_portfolio": payload,
    }
