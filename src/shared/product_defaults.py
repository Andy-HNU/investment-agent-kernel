from __future__ import annotations

from copy import deepcopy
from typing import Any


def default_market_assumptions() -> dict[str, Any]:
    return {
        "expected_returns": {
            "equity_cn": 0.08,
            "bond_cn": 0.03,
            "gold": 0.04,
            "satellite": 0.10,
        },
        "volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "correlation_matrix": {
            "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.1, "gold": 0.2, "satellite": 0.7},
            "bond_cn": {"equity_cn": 0.1, "bond_cn": 1.0, "gold": 0.05, "satellite": 0.0},
            "gold": {"equity_cn": 0.2, "bond_cn": 0.05, "gold": 1.0, "satellite": 0.15},
            "satellite": {"equity_cn": 0.7, "bond_cn": 0.0, "gold": 0.15, "satellite": 1.0},
        },
    }


def default_universe() -> dict[str, Any]:
    return {
        "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
        "bucket_category": {
            "equity_cn": "core",
            "bond_cn": "defense",
            "gold": "defense",
            "satellite": "satellite",
        },
        "bucket_to_theme": {
            "equity_cn": None,
            "bond_cn": None,
            "gold": None,
            "satellite": None,
        },
        "liquidity_buckets": ["bond_cn"],
        "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
    }


def _compiled_bucket_boundaries(parsed_profile: dict[str, Any] | None = None) -> dict[str, tuple[float, float]]:
    parsed_profile = parsed_profile or {}
    allowed_buckets = set(parsed_profile.get("allowed_buckets") or [])
    forbidden_buckets = set(parsed_profile.get("forbidden_buckets") or [])
    forbidden_themes = set(parsed_profile.get("forbidden_themes") or [])
    universe = default_universe()
    boundaries: dict[str, tuple[float, float]] = {
        "equity_cn": (0.20, 0.70),
        "bond_cn": (0.10, 0.60),
        "gold": (0.0, 0.15),
        "satellite": (0.0, 0.15),
    }
    bucket_to_theme = universe["bucket_to_theme"]
    allowed_mode = bool(allowed_buckets)
    for bucket in list(boundaries):
        theme = bucket_to_theme.get(bucket)
        if bucket in forbidden_buckets or (allowed_mode and bucket not in allowed_buckets) or (theme and theme in forbidden_themes):
            boundaries[bucket] = (0.0, 0.0)
            continue
        if allowed_mode and bucket in allowed_buckets:
            boundaries[bucket] = (0.0, 1.0)
    total_hi = sum(hi for _lo, hi in boundaries.values())
    if 0.0 < total_hi < 1.0:
        deficit = 1.0 - total_hi
        priority_buckets = [
            bucket
            for bucket in list(universe["liquidity_buckets"]) + list(universe["bucket_order"])
            if bucket in boundaries and boundaries[bucket][1] > 0
        ]
        seen: set[str] = set()
        for bucket in priority_buckets:
            if bucket in seen:
                continue
            seen.add(bucket)
            lo, hi = boundaries[bucket]
            add = min(1.0 - hi, deficit)
            boundaries[bucket] = (lo, round(hi + add, 4))
            deficit -= add
            if deficit <= 1e-9:
                break
    if sum(hi for _lo, hi in boundaries.values()) <= 0:
        boundaries["bond_cn"] = (0.0, 1.0)
    return boundaries


def _risk_headroom(profile_dimensions: dict[str, Any] | None) -> float:
    model_inputs = dict((profile_dimensions or {}).get("model_inputs") or {})
    tolerance = float(model_inputs.get("risk_tolerance_score", 0.55))
    capacity = float(model_inputs.get("risk_capacity_score", 0.55))
    return max(0.0, min(1.0, min(tolerance, capacity)))


def _apply_profile_dimensions_to_boundaries(
    boundaries: dict[str, tuple[float, float]],
    *,
    profile_dimensions: dict[str, Any] | None = None,
) -> dict[str, tuple[float, float]]:
    adjusted = deepcopy(boundaries)
    dimensions = profile_dimensions or {}
    model_inputs = dict(dimensions.get("model_inputs") or {})
    risk_headroom = _risk_headroom(dimensions)
    liquidity_need_level = str(model_inputs.get("liquidity_need_level") or "").lower()
    contribution_confidence = float(model_inputs.get("contribution_commitment_confidence", 0.82))
    target_return_pressure = str(model_inputs.get("target_return_pressure") or "").lower()

    if risk_headroom <= 0.35:
        adjusted["equity_cn"] = (adjusted["equity_cn"][0], min(adjusted["equity_cn"][1], 0.45))
        adjusted["bond_cn"] = (max(adjusted["bond_cn"][0], 0.35), adjusted["bond_cn"][1])
        adjusted["satellite"] = (adjusted["satellite"][0], min(adjusted["satellite"][1], 0.05))
    elif risk_headroom <= 0.55:
        adjusted["equity_cn"] = (adjusted["equity_cn"][0], min(adjusted["equity_cn"][1], 0.60))
        adjusted["bond_cn"] = (max(adjusted["bond_cn"][0], 0.20), adjusted["bond_cn"][1])
        adjusted["satellite"] = (adjusted["satellite"][0], min(adjusted["satellite"][1], 0.08))
    elif risk_headroom >= 0.75:
        adjusted["equity_cn"] = (max(adjusted["equity_cn"][0], 0.30), adjusted["equity_cn"][1])
        adjusted["bond_cn"] = (max(0.0, adjusted["bond_cn"][0] - 0.05), adjusted["bond_cn"][1])

    if liquidity_need_level == "high":
        adjusted["bond_cn"] = (max(adjusted["bond_cn"][0], 0.25), adjusted["bond_cn"][1])
        adjusted["equity_cn"] = (adjusted["equity_cn"][0], min(adjusted["equity_cn"][1], 0.55))

    if contribution_confidence < 0.70:
        adjusted["bond_cn"] = (max(adjusted["bond_cn"][0], 0.20), adjusted["bond_cn"][1])

    if target_return_pressure in {"high", "very_high"} and risk_headroom >= 0.45 and liquidity_need_level != "high":
        adjusted["equity_cn"] = (
            adjusted["equity_cn"][0],
            max(adjusted["equity_cn"][1], 0.70 if target_return_pressure == "high" else 0.75),
        )
        adjusted["satellite"] = (
            adjusted["satellite"][0],
            max(adjusted["satellite"][1], 0.12 if target_return_pressure == "high" else 0.15),
        )

    return adjusted


def default_goal_solver_constraints(
    max_drawdown_tolerance: float,
    parsed_profile: dict[str, Any] | None = None,
    *,
    profile_dimensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_profile = parsed_profile or {}
    qdii_allowed = parsed_profile.get("qdii_allowed")
    boundaries = _apply_profile_dimensions_to_boundaries(
        _compiled_bucket_boundaries(parsed_profile),
        profile_dimensions=profile_dimensions,
    )
    bond_allowed = boundaries["bond_cn"][1] > 0
    model_inputs = dict((profile_dimensions or {}).get("model_inputs") or {})
    risk_headroom = _risk_headroom(profile_dimensions)
    target_return_pressure = str(model_inputs.get("target_return_pressure") or "").lower()
    satellite_cap = min(boundaries["satellite"][1], 0.15)
    if risk_headroom <= 0.35:
        satellite_cap = min(satellite_cap, 0.05)
    elif risk_headroom <= 0.55:
        satellite_cap = min(satellite_cap, 0.08)
    if target_return_pressure in {"high", "very_high"} and risk_headroom >= 0.45:
        satellite_cap = max(satellite_cap, 0.12 if target_return_pressure == "high" else 0.15)
    liquidity_reserve_min = 0.05 if bond_allowed else 0.0
    if str(model_inputs.get("liquidity_need_level") or "").lower() == "high":
        liquidity_reserve_min = max(liquidity_reserve_min, 0.10)
    if float(model_inputs.get("contribution_commitment_confidence", 0.82)) < 0.70:
        liquidity_reserve_min = max(liquidity_reserve_min, 0.08)
    return {
        "max_drawdown_tolerance": float(max_drawdown_tolerance),
        "ips_bucket_boundaries": boundaries,
        "satellite_cap": satellite_cap,
        "theme_caps": {},
        "qdii_cap": (
            0.0
            if qdii_allowed is False
            else 0.25
            if target_return_pressure == "high" and risk_headroom >= 0.45
            else 0.30
            if target_return_pressure == "very_high" and risk_headroom >= 0.45
            else 0.20
        ),
        "liquidity_reserve_min": liquidity_reserve_min,
    }


def default_candidate_allocations() -> list[dict[str, Any]]:
    return [
        {
            "name": "base_allocation",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.2,
            "description": "baseline onboarding allocation",
        }
    ]


def build_product_market_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    assumptions = (goal_solver_input.get("solver_params") or {}).get("market_assumptions") or default_market_assumptions()
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.90,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.60,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.2,
        },
        "expected_returns": deepcopy(assumptions.get("expected_returns") or {}),
    }


def build_product_account_raw(
    goal_solver_input: dict[str, Any],
    live_portfolio: dict[str, Any],
) -> dict[str, Any]:
    return {
        "weights": deepcopy(live_portfolio["weights"]),
        "total_value": live_portfolio["total_value"],
        "available_cash": live_portfolio["available_cash"],
        "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
    }


def build_product_goal_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(goal_solver_input["goal"])


def build_product_constraint_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    constraints = deepcopy(goal_solver_input["constraints"])
    constraints.update(
        {
            "rebalancing_band": 0.10,
            "forbidden_actions": [],
            "cooling_period_days": 3,
            "soft_preferences": {},
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": default_universe()["bucket_to_theme"],
            "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
        }
    )
    return constraints


def build_product_behavior_raw(
    *,
    cooldown_active: bool = False,
    cooldown_until: str | None = None,
    override_count_90d: int = 0,
) -> dict[str, Any]:
    return {
        "recent_chase_risk": "low",
        "recent_panic_risk": "none",
        "trade_frequency_30d": 1.0,
        "override_count_90d": override_count_90d,
        "cooldown_active": cooldown_active,
        "cooldown_until": cooldown_until,
        "behavior_penalty_coeff": 0.2,
    }


def build_product_allocation_input(
    goal_solver_input: dict[str, Any],
    *,
    parsed_profile: dict[str, Any] | None = None,
    profile_dimensions: dict[str, Any] | None = None,
    allowed_buckets: list[str] | None = None,
    forbidden_buckets: list[str] | None = None,
    preferred_themes: list[str] | None = None,
    forbidden_themes: list[str] | None = None,
    qdii_allowed: bool = True,
    allowed_wrappers: list[str] | None = None,
    forbidden_wrappers: list[str] | None = None,
    allowed_regions: list[str] | None = None,
    forbidden_regions: list[str] | None = None,
) -> dict[str, Any]:
    parsed_profile = parsed_profile or {}
    profile_dimensions = profile_dimensions or {}
    model_inputs = dict(profile_dimensions.get("model_inputs") or {})
    allowed_buckets = list(parsed_profile.get("allowed_buckets") or allowed_buckets or [])
    forbidden_buckets = list(parsed_profile.get("forbidden_buckets") or forbidden_buckets or [])
    preferred_themes = list(parsed_profile.get("preferred_themes") or preferred_themes or [])
    forbidden_themes = list(parsed_profile.get("forbidden_themes") or forbidden_themes or [])
    allowed_wrappers = list(parsed_profile.get("allowed_wrappers") or allowed_wrappers or [])
    forbidden_wrappers = list(parsed_profile.get("forbidden_wrappers") or forbidden_wrappers or [])
    allowed_regions = list(parsed_profile.get("allowed_regions") or allowed_regions or [])
    forbidden_regions = list(parsed_profile.get("forbidden_regions") or forbidden_regions or [])
    qdii_value = parsed_profile.get("qdii_allowed")
    if qdii_value is None:
        qdii_value = qdii_allowed
    risk_headroom = _risk_headroom(profile_dimensions)
    complexity_tolerance = "medium"
    if str(model_inputs.get("liquidity_need_level") or "").lower() == "high" or risk_headroom <= 0.45:
        complexity_tolerance = "low"
    elif risk_headroom >= 0.75 and str(model_inputs.get("goal_priority") or "important") != "essential":
        complexity_tolerance = "high"
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input["account_profile_id"],
            "risk_preference": goal_solver_input["goal"]["risk_preference"],
            "complexity_tolerance": complexity_tolerance,
            "allowed_buckets": allowed_buckets,
            "forbidden_buckets": forbidden_buckets,
            "allowed_wrappers": allowed_wrappers,
            "forbidden_wrappers": forbidden_wrappers,
            "allowed_regions": allowed_regions,
            "forbidden_regions": forbidden_regions,
            "preferred_themes": preferred_themes,
            "forbidden_themes": forbidden_themes,
            "qdii_allowed": bool(qdii_value),
            "profile_flags": deepcopy(model_inputs),
        },
        "goal": deepcopy(goal_solver_input["goal"]),
        "cashflow_plan": deepcopy(goal_solver_input["cashflow_plan"]),
        "constraints": deepcopy(goal_solver_input["constraints"]),
        "universe": default_universe(),
    }


def product_market_assumptions() -> dict[str, Any]:
    return default_market_assumptions()


def build_default_market_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return build_product_market_raw(goal_solver_input)


def build_default_account_raw(goal_solver_input: dict[str, Any], live_portfolio: dict[str, Any]) -> dict[str, Any]:
    return build_product_account_raw(goal_solver_input, live_portfolio)


def build_default_goal_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return build_product_goal_raw(goal_solver_input)


def build_default_behavior_raw(
    *,
    cooldown_active: bool = False,
    cooldown_until: str | None = None,
    override_count_90d: int = 0,
) -> dict[str, Any]:
    return build_product_behavior_raw(
        cooldown_active=cooldown_active,
        cooldown_until=cooldown_until,
        override_count_90d=override_count_90d,
    )


def build_default_constraint_raw(
    goal_solver_input: dict[str, Any] | None = None,
    *,
    max_drawdown_tolerance: float | None = None,
    parsed_profile: dict[str, Any] | None = None,
    profile_dimensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if goal_solver_input is not None:
        constraints = build_product_constraint_raw(goal_solver_input)
        if not parsed_profile:
            return constraints
        compiled = default_goal_solver_constraints(
            float(constraints.get("max_drawdown_tolerance", max_drawdown_tolerance or 0.1)),
            parsed_profile=parsed_profile,
            profile_dimensions=profile_dimensions,
        )
        constraints.update(
            {
                "ips_bucket_boundaries": compiled["ips_bucket_boundaries"],
                "satellite_cap": compiled["satellite_cap"],
                "theme_caps": compiled["theme_caps"],
                "qdii_cap": compiled["qdii_cap"],
                "liquidity_reserve_min": compiled["liquidity_reserve_min"],
            }
        )
        return constraints
    return {
        **default_goal_solver_constraints(
            float(max_drawdown_tolerance or 0.1),
            parsed_profile=parsed_profile,
            profile_dimensions=profile_dimensions,
        ),
        "rebalancing_band": 0.10,
        "forbidden_actions": [],
        "cooling_period_days": 3,
        "soft_preferences": {},
        "bucket_category": default_universe()["bucket_category"],
        "bucket_to_theme": default_universe()["bucket_to_theme"],
        "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
    }


def build_default_allocation_input(
    goal_solver_input: dict[str, Any],
    *,
    parsed_profile: dict[str, Any] | None = None,
    profile_dimensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_product_allocation_input(
        goal_solver_input,
        parsed_profile=parsed_profile,
        profile_dimensions=profile_dimensions,
    )
