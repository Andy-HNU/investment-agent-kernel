from __future__ import annotations

from allocation_engine.types import AllocationEngineInput, AllocationTemplate


FAMILY_PRIORITY = {
    "defense_heavy": 0,
    "balanced_core": 1,
    "growth_tilt": 2,
    "max_return_unconstrained": 3,
    "theme_tilt": 4,
    "liquidity_buffered": 5,
    "satellite_light": 6,
}


def family_priority(template_name: str) -> int:
    for family, priority in FAMILY_PRIORITY.items():
        if template_name.startswith(family):
            return priority
    return 99


def template_family_name(template_name: str) -> str:
    for family in FAMILY_PRIORITY:
        if template_name.startswith(family):
            return family
    return template_name


def _has_negative_cashflow_within_horizon(
    inp: AllocationEngineInput,
    horizon_months: int,
) -> bool:
    return any(
        event.amount < 0 and event.month_index <= horizon_months
        for event in inp.cashflow_plan.cashflow_events
    )


def _risk_headroom(inp: AllocationEngineInput) -> float:
    flags = dict(inp.account_profile.profile_flags or {})
    tolerance = float(flags.get("risk_tolerance_score", 0.55) or 0.55)
    capacity = float(flags.get("risk_capacity_score", 0.55) or 0.55)
    return max(0.0, min(1.0, min(tolerance, capacity)))


def _target_return_pressure(inp: AllocationEngineInput) -> str:
    flags = dict(inp.account_profile.profile_flags or {})
    return str(flags.get("target_return_pressure") or "").strip().lower()


def _retarget_template(
    template: AllocationTemplate,
    *,
    satellite_cap: float | None = None,
    defense_floor: float | None = None,
    theme_tilt_strength: float | None = None,
    liquidity_buffer_bonus: float | None = None,
) -> AllocationTemplate:
    core_weight = template.target_core_weight
    defense_weight = template.target_defense_weight
    satellite_weight = template.target_satellite_weight

    if satellite_cap is not None and satellite_weight > satellite_cap:
        shifted = satellite_weight - satellite_cap
        satellite_weight = satellite_cap
        defense_weight += shifted

    if defense_floor is not None and defense_weight < defense_floor:
        shifted = min(core_weight, defense_floor - defense_weight)
        core_weight -= shifted
        defense_weight += shifted

    total = core_weight + defense_weight + satellite_weight
    if abs(total - 1.0) > 1e-9:
        defense_weight += 1.0 - total

    return AllocationTemplate(
        template_name=template.template_name,
        template_family=template.template_family,
        target_core_weight=round(core_weight, 4),
        target_defense_weight=round(defense_weight, 4),
        target_satellite_weight=round(satellite_weight, 4),
        preferred_theme=template.preferred_theme,
        theme_tilt_strength=(
            round(theme_tilt_strength, 4)
            if theme_tilt_strength is not None
            else template.theme_tilt_strength
        ),
        liquidity_buffer_bonus=(
            round(liquidity_buffer_bonus, 4)
            if liquidity_buffer_bonus is not None
            else template.liquidity_buffer_bonus
        ),
    )


def _adjust_template_for_profile(
    template: AllocationTemplate,
    inp: AllocationEngineInput,
    near_term_negative_cashflow: bool,
) -> AllocationTemplate:
    goal = inp.goal
    profile = inp.account_profile
    constraints = inp.constraints
    params = inp.params

    satellite_cap: float | None = None
    defense_floor: float | None = None
    theme_tilt_strength: float | None = None
    liquidity_buffer_bonus: float | None = None

    if goal.priority == "essential":
        satellite_cap = 0.05
        defense_floor = 0.45

    if goal.risk_preference == "conservative":
        satellite_cap = min(satellite_cap, 0.05) if satellite_cap is not None else 0.05
        defense_floor = max(defense_floor or 0.0, 0.45)
    elif goal.risk_preference == "aggressive" and template.template_family == "theme_tilt":
        theme_tilt_strength = max(params.theme_tilt_step * 1.5, template.theme_tilt_strength)

    if profile.complexity_tolerance == "low":
        satellite_cap = min(satellite_cap, 0.05) if satellite_cap is not None else 0.05
        defense_floor = max(defense_floor or 0.0, 0.40)

    if near_term_negative_cashflow and template.template_family == "liquidity_buffered":
        liquidity_buffer_bonus = max(
            template.liquidity_buffer_bonus,
            constraints.liquidity_reserve_min,
            params.liquidity_buffer_step * 2,
        )

    return _retarget_template(
        template,
        satellite_cap=satellite_cap,
        defense_floor=defense_floor,
        theme_tilt_strength=theme_tilt_strength,
        liquidity_buffer_bonus=liquidity_buffer_bonus,
    )


def build_template_family(inp: AllocationEngineInput) -> list[AllocationTemplate]:
    goal = inp.goal
    profile = inp.account_profile
    constraints = inp.constraints
    params = inp.params
    risk_headroom = _risk_headroom(inp)
    target_return_pressure = _target_return_pressure(inp)
    near_term_negative_cashflow = _has_negative_cashflow_within_horizon(inp, horizon_months=12)
    templates: list[AllocationTemplate] = [
        AllocationTemplate(
            template_name="defense_heavy",
            template_family="defense_heavy",
            target_core_weight=0.40,
            target_defense_weight=0.55,
            target_satellite_weight=0.05,
        ),
        AllocationTemplate(
            template_name="balanced_core",
            template_family="balanced_core",
            target_core_weight=0.55,
            target_defense_weight=0.35,
            target_satellite_weight=0.10,
        ),
    ]

    allow_growth_tilt = goal.priority != "essential" and (
        goal.risk_preference == "aggressive"
        or (
            goal.risk_preference == "moderate"
            and (
                goal.horizon_months >= 60
                or target_return_pressure in {"high", "very_high"}
                or risk_headroom >= 0.75
            )
        )
    )
    if allow_growth_tilt:
        templates.append(
            AllocationTemplate(
                template_name="growth_tilt",
                template_family="growth_tilt",
                target_core_weight=0.65,
                target_defense_weight=0.20,
                target_satellite_weight=0.15,
            )
        )

    if (
        goal.priority != "essential"
        and goal.risk_preference != "conservative"
        and (
            target_return_pressure in {"high", "very_high"}
            or goal.priority == "aspirational"
            or risk_headroom >= 0.80
        )
    ):
        templates.append(
            AllocationTemplate(
                template_name="max_return_unconstrained",
                template_family="max_return_unconstrained",
                target_core_weight=0.75,
                target_defense_weight=0.10,
                target_satellite_weight=0.15,
            )
        )

    if (
        goal.priority == "essential"
        or constraints.liquidity_reserve_min > 0
        or near_term_negative_cashflow
    ):
        templates.append(
            AllocationTemplate(
                template_name="liquidity_buffered",
                template_family="liquidity_buffered",
                target_core_weight=0.45,
                target_defense_weight=0.50,
                target_satellite_weight=0.05,
                liquidity_buffer_bonus=max(
                    params.liquidity_buffer_step,
                    constraints.liquidity_reserve_min,
                ),
            )
        )

    available_themes = {
        theme
        for theme in inp.universe.bucket_to_theme.values()
        if theme is not None
    }
    preferred_themes = [
        theme
        for theme in profile.preferred_themes
        if theme not in profile.forbidden_themes
        and theme in constraints.theme_caps
        and theme in available_themes
    ]
    if profile.complexity_tolerance == "low":
        preferred_themes = preferred_themes[:1]

    for preferred_theme in preferred_themes:
        templates.append(
            AllocationTemplate(
                template_name=f"theme_tilt_{preferred_theme}",
                template_family="theme_tilt",
                target_core_weight=0.55,
                target_defense_weight=0.30,
                target_satellite_weight=0.15,
                preferred_theme=preferred_theme,
                theme_tilt_strength=params.theme_tilt_step,
            )
        )

    templates.append(
        AllocationTemplate(
            template_name="satellite_light",
            template_family="satellite_light",
            target_core_weight=0.55,
            target_defense_weight=0.40,
            target_satellite_weight=0.05,
        )
    )

    adjusted = [
        _adjust_template_for_profile(template, inp, near_term_negative_cashflow)
        for template in templates
    ]
    if profile.complexity_tolerance == "low" and len(adjusted) > 4:
        adjusted = [
            template
            for template in adjusted
            if template.template_family != "satellite_light"
        ]
    return adjusted
