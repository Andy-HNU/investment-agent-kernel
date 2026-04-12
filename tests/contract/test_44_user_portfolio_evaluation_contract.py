from __future__ import annotations

from copy import deepcopy

import pytest

from frontdesk.service import run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


def _profile(*, account_profile_id: str = "user_portfolio_contract") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=100_000.0,
        monthly_contribution=8_000.0,
        goal_amount=1_200_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.45,
            "bond_cn": 0.25,
            "gold": 0.10,
            "cash_liquidity": 0.20,
        },
    )


def _profile_bundle_with_user_portfolio(
    profile: UserOnboardingProfile,
    *,
    user_portfolio: list[dict[str, object]],
    as_of: str = "2026-04-07T00:00:00Z",
):
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    bundle.raw_inputs = deepcopy(bundle.raw_inputs)
    bundle.raw_inputs["user_portfolio"] = deepcopy(user_portfolio)
    return bundle


@pytest.mark.contract
def test_user_portfolio_is_evaluated_as_entered_without_rewrite(monkeypatch, tmp_path):
    user_portfolio = [
        {"product_id": "cn_equity_dividend_etf", "target_weight": 0.25},
        {"product_id": "cn_equity_csi300_etf", "target_weight": 0.25},
        {"product_id": "cn_gold_etf", "target_weight": 0.10},
        {"product_id": "cn_cash_money_fund", "target_weight": 0.40},
    ]
    profile = _profile(account_profile_id="user_portfolio_no_rewrite")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["requested_structure_visibility"]["rewrite_applied"] is False
    assert result["requested_structure_visibility"]["requested_structure"] == user_portfolio
    assert result["unknown_product_resolution"]["state"] == "resolved_formal_ready"


@pytest.mark.contract
def test_unrecognized_product_blocks_strict_formal_until_user_resolves(monkeypatch, tmp_path):
    user_portfolio = [
        {"product_id": "mystery_fund_x", "target_weight": 1.0},
    ]
    profile = _profile(account_profile_id="user_portfolio_unknown_product")

    def _fake_build_user_onboarding_inputs(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _profile_bundle_with_user_portfolio(profile, user_portfolio=user_portfolio, as_of=kwargs.get("as_of") or "2026-04-07T00:00:00Z")

    monkeypatch.setattr("frontdesk.service.build_user_onboarding_inputs", _fake_build_user_onboarding_inputs)

    result = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk_unknown.sqlite")

    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["unknown_product_resolution"]["state"] == "unrecognized_requires_user_action"
    assert result["unknown_product_resolution"]["strict_formal_blocked"] is True
    assert result["unknown_product_resolution"]["items"][0]["product_state"] == "unrecognized_product"
    assert result["run_outcome_status"] == "blocked"
