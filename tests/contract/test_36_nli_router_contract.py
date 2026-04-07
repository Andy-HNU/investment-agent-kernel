from __future__ import annotations

from agent.nli_router import parse_onboarding


def test_parse_onboarding_extracts_horizon_from_in_months_phrase():
    payload = parse_onboarding(
        "please onboard user demo_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate"
    )

    assert payload["goal_horizon_months"] == 36


def test_parse_onboarding_derives_drawdown_tolerance_from_risk_when_not_explicit():
    moderate = parse_onboarding(
        "please onboard user moderate_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate"
    )
    low = parse_onboarding(
        "please onboard user low_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk low"
    )
    high = parse_onboarding(
        "please onboard user high_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk high"
    )

    assert low["max_drawdown_tolerance"] == 0.10
    assert moderate["max_drawdown_tolerance"] == 0.20
    assert high["max_drawdown_tolerance"] == 0.30


def test_parse_onboarding_keeps_explicit_drawdown_override():
    payload = parse_onboarding(
        "please onboard user explicit_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate, dd=0.15"
    )

    assert payload["max_drawdown_tolerance"] == 0.15
