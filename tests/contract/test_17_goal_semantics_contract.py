from __future__ import annotations

import pytest

from shared.goal_semantics import build_goal_semantics
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


@pytest.mark.contract
def test_goal_semantics_defaults_explain_total_assets_not_return():
    profile = UserOnboardingProfile(
        account_profile_id="goal_semantics_default",
        display_name="Andy",
        current_total_assets=52_000.0,
        monthly_contribution=10_000.0,
        goal_amount=450_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="全现金",
    )

    semantics = build_goal_semantics(profile).to_dict()

    assert semantics["goal_amount_basis"] == "nominal"
    assert semantics["goal_amount_scope"] == "total_assets"
    assert semantics["tax_assumption"] == "pre_tax"
    assert semantics["fee_assumption"] == "transaction_cost_only"
    assert "目标期末总资产" not in semantics["explanation"] or "不是收益" in semantics["explanation"]
    assert any("不是收益" in line for line in semantics["disclosure_lines"])
    assert any("未单独折算通胀" in line for line in semantics["disclosure_lines"])


@pytest.mark.contract
def test_goal_semantics_supports_explicit_override_without_faking_solver_support():
    profile = UserOnboardingProfile(
        account_profile_id="goal_semantics_override",
        display_name="Andy",
        current_total_assets=80_000.0,
        monthly_contribution=8_000.0,
        goal_amount=500_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="股债六四",
        goal_amount_basis="real",
        goal_amount_scope="incremental_gain",
        tax_assumption="after_tax",
        fee_assumption="platform_fee_excluded",
        contribution_commitment_confidence=0.66,
    )

    semantics = build_goal_semantics(profile).to_dict()
    bundle = build_user_onboarding_inputs(profile)

    assert semantics["goal_amount_basis"] == "real"
    assert semantics["goal_amount_scope"] == "incremental_gain"
    assert semantics["tax_assumption"] == "after_tax"
    assert semantics["fee_assumption"] == "platform_fee_excluded"
    assert semantics["contribution_commitment_confidence"] == pytest.approx(0.66)
    assert any(token in line for line in semantics["disclosure_lines"] for token in ("只做披露", "只做透明披露"))
    assert bundle.goal_solver_input["goal"]["goal_amount_basis"] == "real"
    assert bundle.goal_solver_input["goal"]["goal_amount_scope"] == "incremental_gain"
    assert bundle.goal_solver_input["goal"]["tax_assumption"] == "after_tax"
    assert bundle.goal_solver_input["goal"]["fee_assumption"] == "platform_fee_excluded"


@pytest.mark.contract
def test_goal_semantics_preserves_unknown_fee_assumption_without_silent_fallback():
    profile = UserOnboardingProfile(
        account_profile_id="goal_semantics_fee_unknown",
        display_name="Andy",
        current_total_assets=60_000.0,
        monthly_contribution=6_000.0,
        goal_amount=400_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="全现金",
        fee_assumption="unknown",
    )

    semantics = build_goal_semantics(profile).to_dict()

    assert semantics["fee_assumption"] == "unknown"
    assert any("费用口径尚未指定" in line for line in semantics["disclosure_lines"])
