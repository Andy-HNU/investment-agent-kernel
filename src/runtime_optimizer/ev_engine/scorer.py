from __future__ import annotations

import math
from typing import Any

from goal_solver.engine import run_goal_solver_lightweight
from runtime_optimizer.candidates import Action, ActionType
from runtime_optimizer.ev_engine.types import EVComponentScore, EVState
from runtime_optimizer.state_builder import augment_weights_with_cash_bucket


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _market_assumptions(state: EVState) -> dict[str, Any]:
    baseline = _obj(_obj(state)["goal_solver_baseline_inp"])
    solver_params = _obj(baseline.get("solver_params", {}))
    return _obj(solver_params.get("market_assumptions", {}))


def _is_qdii_bucket(bucket: str | None, constraints: dict[str, Any]) -> bool:
    if not bucket:
        return False
    normalized = bucket.lower()
    if "qdii" in normalized:
        return True
    return constraints.get("bucket_category", {}).get(bucket) == "qdii"


def _apply_action(action: Action, account: dict[str, Any]) -> dict[str, float]:
    weights = augment_weights_with_cash_bucket(
        account.get("current_weights", {}),
        account.get("total_portfolio_value", 0.0),
        account.get("available_cash", 0.0),
    )
    if action.type in {ActionType.FREEZE, ActionType.OBSERVE}:
        return weights
    delta = float(action.amount_pct or 0.0)
    if delta <= 0:
        return weights
    target = action.target_bucket or action.to_bucket or "equity_cn"
    cash_bucket = "cash_liquidity" if "cash_liquidity" in weights else ("cash" if "cash" in weights else None)
    if action.type in {ActionType.ADD_CASH_TO_CORE, ActionType.ADD_CASH_TO_DEF, ActionType.ADD_CASH_TO_SAT, ActionType.ADD_DEFENSE}:
        transferred = delta
        if cash_bucket is not None:
            available = max(0.0, float(weights.get(cash_bucket, 0.0)))
            transferred = min(delta, available)
            weights[cash_bucket] = max(0.0, available - transferred)
        weights[target] = weights.get(target, 0.0) + transferred
    elif action.type == ActionType.REDUCE_SATELLITE:
        reduced = min(delta, max(0.0, float(weights.get(target, 0.0))))
        weights[target] = max(0.0, weights.get(target, 0.0) - reduced)
        if reduced > 0.0:
            cash_target = cash_bucket or "cash_liquidity"
            weights[cash_target] = weights.get(cash_target, 0.0) + reduced
    elif action.type in {ActionType.REBALANCE_LIGHT, ActionType.REBALANCE_FULL}:
        from_bucket = action.from_bucket or target
        to_bucket = action.to_bucket or target
        weights[from_bucket] = max(0.0, weights.get(from_bucket, 0.0) - delta)
        weights[to_bucket] = weights.get(to_bucket, 0.0) + delta
    total = sum(weights.values()) or 1.0
    return {bucket: value / total for bucket, value in weights.items()}


def _portfolio_volatility(weights: dict[str, float], assumptions: dict[str, Any]) -> float:
    vol = assumptions.get("volatility", {}) or {}
    corr = assumptions.get("correlation_matrix", {}) or {}
    variance = 0.0
    for bucket_i, weight_i in weights.items():
        sigma_i = float(vol.get(bucket_i, 0.0))
        if sigma_i <= 0:
            continue
        for bucket_j, weight_j in weights.items():
            sigma_j = float(vol.get(bucket_j, 0.0))
            if sigma_j <= 0:
                continue
            if bucket_i == bucket_j:
                corr_ij = 1.0
            else:
                corr_ij = float(corr.get(bucket_i, {}).get(bucket_j, corr.get(bucket_j, {}).get(bucket_i, 0.0)))
            variance += weight_i * weight_j * sigma_i * sigma_j * corr_ij
    return math.sqrt(max(variance, 0.0))


def _parametric_cvar(weights: dict[str, float], assumptions: dict[str, Any], confidence: float = 0.95) -> float:
    sigma = _portfolio_volatility(weights, assumptions)
    cvar_multiplier = 2.0627 if confidence >= 0.95 else 1.7540
    return sigma * cvar_multiplier


def _theme_weight(new_weights: dict[str, float], constraints: dict[str, Any], theme: str) -> float:
    bucket_to_theme = constraints.get("bucket_to_theme", {}) or {}
    return sum(weight for bucket, weight in new_weights.items() if bucket_to_theme.get(bucket) == theme)


def _is_momentum_chase(action: Action, market: dict[str, Any]) -> bool:
    bucket = action.target_bucket or action.to_bucket
    if not bucket:
        return False
    valuation_positions = market.get("valuation_positions", {}) or {}
    valuation = str(valuation_positions.get(bucket, "")).lower()
    return valuation in {"rich", "extreme"}


def compute_goal_impact(action: Action, state: EVState, params: dict[str, Any], new_weights: dict[str, float]) -> float:
    state_dict = _obj(state)
    baseline_weights = augment_weights_with_cash_bucket(
        _obj(state_dict["account"])["current_weights"],
        _obj(state_dict["account"]).get("total_portfolio_value", 0.0),
        _obj(state_dict["account"]).get("available_cash", 0.0),
    )
    baseline, _risk = run_goal_solver_lightweight(
        weights=baseline_weights,
        baseline_inp=_obj(state_dict["goal_solver_baseline_inp"]),
    )
    after, _risk_after = run_goal_solver_lightweight(
        weights=new_weights,
        baseline_inp=_obj(state_dict["goal_solver_baseline_inp"]),
    )
    if action.type in {ActionType.FREEZE, ActionType.OBSERVE}:
        return 0.0
    delta = after - baseline
    min_delta = float(params.get("goal_solver_min_delta", 0.0) or 0.0)
    if abs(delta) < min_delta:
        delta = 0.0
    return delta * float(params.get("goal_impact_weight", 1.0))


def compute_risk_penalty(action: Action, state: EVState, params: dict[str, Any], new_weights: dict[str, float]) -> float:
    state_dict = _obj(state)
    market = _obj(state_dict["market"])
    constraints = _obj(state_dict["constraints"])
    assumptions = _market_assumptions(state)

    cvar_after = _parametric_cvar(new_weights, assumptions, confidence=0.95)
    baseline_weights = augment_weights_with_cash_bucket(
        _obj(state_dict["account"])["current_weights"],
        _obj(state_dict["account"]).get("total_portfolio_value", 0.0),
        _obj(state_dict["account"]).get("available_cash", 0.0),
    )
    cvar_before = _parametric_cvar(baseline_weights, assumptions, confidence=0.95)
    cvar_delta = max(0.0, cvar_after - cvar_before)

    concentration_penalty = 0.0
    for bucket, (lo, hi) in constraints.get("ips_bucket_boundaries", {}).items():
        weight = float(new_weights.get(bucket, 0.0))
        band = max(hi - lo, 1e-6)
        headroom = max(0.0, hi - weight) / band
        threshold = float(params.get("concentration_headroom_threshold", 0.0) or 0.0)
        if threshold > 0 and headroom < threshold:
            concentration_penalty += (threshold - headroom) ** 2
    if market.get("correlation_spike_alert", False):
        concentration_penalty *= 1.5

    liquidity_penalty = 0.0
    bucket = action.target_bucket or action.to_bucket
    liquidity_flag = market.get("liquidity_flag", {}) or {}
    liquidity_status = market.get("liquidity_status", {}) or {}
    if bucket and (liquidity_flag.get(bucket) or str(liquidity_status.get(bucket, "")).lower() in {"tight", "stressed"}):
        liquidity_penalty = 0.01

    raw_penalty = (
        cvar_delta * float(params.get("drawdown_penalty_coeff", 0.0) or 0.0)
        + concentration_penalty * float(params.get("volatility_penalty_coeff", 0.0) or 0.0)
        + liquidity_penalty
    )
    return max(0.0, raw_penalty) * float(params.get("risk_penalty_weight", 0.0))


def compute_soft_constraint_penalty(
    action: Action,
    state: EVState,
    params: dict[str, Any],
    new_weights: dict[str, float],
) -> float:
    del action
    state_dict = _obj(state)
    constraints = _obj(state_dict["constraints"])
    penalty = 0.0

    ips_threshold = float(params.get("ips_headroom_warning_threshold", 0.0) or 0.0)
    if ips_threshold > 0:
        for bucket, (lo, hi) in constraints.get("ips_bucket_boundaries", {}).items():
            weight = float(new_weights.get(bucket, 0.0))
            headroom = min(max(weight - lo, 0.0), max(hi - weight, 0.0)) / max(hi - lo, 1e-6)
            if headroom < ips_threshold:
                penalty += (ips_threshold - headroom) ** 2

    theme_warning_pct = float(params.get("theme_budget_warning_pct", 0.0) or 0.0)
    if theme_warning_pct <= 0:
        theme_warning_pct = 1.0
    for theme, cap in (constraints.get("theme_caps", {}) or {}).items():
        theme_weight = _theme_weight(new_weights, constraints, theme)
        threshold = float(cap) * theme_warning_pct
        if theme_weight > threshold:
            penalty += (theme_weight - threshold) ** 2 * 2.0

    return max(0.0, penalty) * float(params.get("soft_constraint_weight", 0.0))


def compute_behavior_penalty(action: Action, state: EVState, params: dict[str, Any]) -> float:
    state_dict = _obj(state)
    behavior = _obj(state_dict["behavior"])
    market = _obj(state_dict["market"])

    raw_penalty = 0.0
    emotion_score = float(behavior.get("emotion_score", 0.0) or 0.0)
    emotion_threshold = float(params.get("emotion_score_threshold", 0.0) or 0.0)
    if (
        emotion_threshold > 0
        and emotion_score > emotion_threshold
        and action.type not in {ActionType.FREEZE, ActionType.OBSERVE}
    ):
        raw_penalty += (emotion_score - emotion_threshold) * 2.0

    if behavior.get("recent_chasing_flag") and _is_momentum_chase(action, market):
        raw_penalty += 0.6

    action_frequency = float(behavior.get("action_frequency_30d", 0.0) or 0.0)
    frequency_threshold = float(params.get("action_frequency_threshold", 0.0) or 0.0)
    if frequency_threshold > 0 and action_frequency >= frequency_threshold:
        raw_penalty += min((action_frequency - (frequency_threshold - 1.0)) * 0.3, 1.2)

    if behavior.get("panic_flag") and action.requires_sell:
        raw_penalty += 0.8

    scaled = raw_penalty * max(0.0, float(behavior.get("behavior_penalty_coeff", 0.0) or 0.0))
    return scaled * float(params.get("behavior_penalty_weight", 0.0))


def compute_execution_penalty(action: Action, state: EVState, params: dict[str, Any]) -> float:
    state_dict = _obj(state)
    constraints = _obj(state_dict["constraints"])

    amount_pct = float(action.amount_pct or 0.0)
    bucket = action.target_bucket or action.to_bucket or ""
    fee_rate = float(
        (constraints.get("transaction_fee_rate", {}) or {}).get(
            bucket,
            params.get("transaction_cost_rate", 0.001),
        )
    )
    fee_cost = amount_pct * fee_rate

    premium_discount = float((constraints.get("premium_discount", {}) or {}).get(bucket, 0.0) or 0.0)
    premium_cost = abs(premium_discount) * amount_pct
    if _is_qdii_bucket(bucket, constraints):
        premium_cost += amount_pct * float(params.get("qdii_premium_cost_rate", 0.0) or 0.0)

    complexity_cost = 0.003 if action.requires_sell else 0.0
    raw_cost = fee_cost + premium_cost + complexity_cost
    return max(0.0, raw_cost) * float(params.get("execution_penalty_weight", 0.0))


def score_action(action: Action, state: EVState) -> EVComponentScore:
    state_dict = _obj(state)
    params = _obj(state_dict["ev_params"])
    account = _obj(state_dict["account"])
    new_weights = _apply_action(action, account)
    goal_impact = compute_goal_impact(action, state, params, new_weights)
    risk_penalty = compute_risk_penalty(action, state, params, new_weights)
    soft_constraint_penalty = compute_soft_constraint_penalty(action, state, params, new_weights)
    behavior_penalty = compute_behavior_penalty(action, state, params)
    execution_penalty = compute_execution_penalty(action, state, params)
    total = goal_impact - risk_penalty - soft_constraint_penalty - behavior_penalty - execution_penalty
    return EVComponentScore(
        goal_impact=goal_impact,
        risk_penalty=risk_penalty,
        soft_constraint_penalty=soft_constraint_penalty,
        behavior_penalty=behavior_penalty,
        execution_penalty=execution_penalty,
        total=total,
    )
