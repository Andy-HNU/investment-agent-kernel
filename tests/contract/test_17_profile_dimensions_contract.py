from __future__ import annotations

import pytest

from shared.goal_semantics import build_goal_semantics
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from shared.profile_dimensions import build_profile_dimensions
from shared.product_defaults import build_default_allocation_input, build_default_constraint_raw
from shared.profile_parser import parse_profile_semantics


def _base_profile(**overrides) -> UserOnboardingProfile:
    payload = {
        "account_profile_id": "p1_profile",
        "display_name": "Andy",
        "current_total_assets": 52_000.0,
        "monthly_contribution": 10_000.0,
        "goal_amount": 450_000.0,
        "goal_horizon_months": 36,
        "risk_preference": "中等",
        "max_drawdown_tolerance": 0.10,
        "current_holdings": "纯黄金",
        "restrictions": ["不碰股票"],
    }
    payload.update(overrides)
    return UserOnboardingProfile(**payload)


@pytest.mark.contract
def test_profile_dimensions_build_layered_schema_with_scores_in_range():
    profile = _base_profile()
    parsed = parse_profile_semantics(
        current_holdings=profile.current_holdings,
        restrictions=profile.restrictions,
    )
    dimensions = build_profile_dimensions(
        profile,
        parsed_profile={**parsed.to_dict(), "requires_confirmation": parsed.requires_confirmation},
        goal_semantics=build_goal_semantics(profile).to_dict(),
    ).to_dict()

    assert {"goal", "risk", "cashflow", "account", "behavior", "model_inputs"}.issubset(set(dimensions))
    for key in ("risk_tolerance_score", "risk_capacity_score", "liquidity_need_score", "contribution_commitment_confidence"):
        assert 0.0 <= float(dimensions["model_inputs"][key]) <= 1.0
    assert dimensions["model_inputs"]["loss_limit"] == pytest.approx(0.10)
    assert dimensions["model_inputs"]["goal_priority"] in {"essential", "important", "aspirational"}


@pytest.mark.contract
def test_profile_dimensions_allow_explicit_goal_priority_override():
    profile = _base_profile(
        profile_dimensions={"goal": {"goal_priority": "essential"}},
        goal_priority="essential",
    )
    parsed = parse_profile_semantics(
        current_holdings=profile.current_holdings,
        restrictions=profile.restrictions,
    )
    dimensions = build_profile_dimensions(
        profile,
        parsed_profile={**parsed.to_dict(), "requires_confirmation": parsed.requires_confirmation},
        goal_semantics=build_goal_semantics(profile).to_dict(),
    ).to_dict()

    assert dimensions["goal_profile"]["goal_priority"] == "essential"
    assert dimensions["goal_profile"]["goal_priority_source"] == "user_provided"


@pytest.mark.contract
def test_onboarding_persists_profile_dimensions_and_applies_risk_overlay():
    profile = _base_profile(
        risk_preference="保守",
        max_drawdown_tolerance=0.06,
        current_holdings="全现金",
    )
    bundle = build_user_onboarding_inputs(profile)
    dimensions = bundle.profile.profile_dimensions

    assert bundle.profile.goal_semantics["goal_amount_scope"] == "total_assets"
    assert dimensions["model_inputs"]["risk_tolerance_score"] < 0.5
    assert bundle.goal_solver_input["goal"]["priority"] in {"important", "essential", "aspirational"}

    constraints = build_default_constraint_raw(
        bundle.goal_solver_input,
        parsed_profile=bundle.raw_inputs["profile_parse"],
        profile_dimensions=dimensions,
    )
    allocation_input = build_default_allocation_input(
        bundle.goal_solver_input,
        parsed_profile=bundle.raw_inputs["profile_parse"],
        profile_dimensions=dimensions,
    )

    assert constraints["satellite_cap"] <= 0.08
    assert constraints["liquidity_reserve_min"] >= 0.08
    assert allocation_input["account_profile"]["complexity_tolerance"] == "low"
    assert allocation_input["account_profile"]["profile_flags"]["goal_priority"] == dimensions["model_inputs"]["goal_priority"]


@pytest.mark.contract
def test_high_return_pressure_profiles_emit_pressure_flags_and_relax_caps():
    profile = _base_profile(
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=124_203.16,
        goal_horizon_months=36,
        max_drawdown_tolerance=0.20,
        current_holdings="",
        restrictions=[],
    )

    bundle = build_user_onboarding_inputs(profile)
    dimensions = bundle.profile.profile_dimensions
    model_inputs = dimensions["model_inputs"]
    constraints = bundle.goal_solver_input["constraints"]

    assert model_inputs["target_return_pressure"] == "high"
    assert model_inputs["implied_required_annual_return"] == pytest.approx(0.083, abs=1e-3)
    assert constraints["satellite_cap"] >= 0.12
    assert constraints["ips_bucket_boundaries"]["equity_cn"][1] >= 0.70
    assert constraints["qdii_cap"] >= 0.25
