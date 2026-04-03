from __future__ import annotations

import pytest

from agent.nli_router import (
    parse_event_context,
    parse_approve_plan,
    parse_feedback,
    parse_onboarding,
    route,
)


@pytest.mark.contract
def test_parse_onboarding_supports_in_months_and_derives_goal_amount_from_annual_return():
    payload = parse_onboarding(
        "我是AndyClaw，目前有2.5万现金和1万黄金，每月会收到5000元现金做为投资存款，想在3年内平均取得10%的年化收益率，不喜欢炒股。"
    )

    assert payload["display_name"] == "AndyClaw"
    assert payload["current_total_assets"] == pytest.approx(35_000.0, rel=1e-6)
    assert payload["monthly_contribution"] == pytest.approx(5_000.0, rel=1e-6)
    assert payload["goal_horizon_months"] == 36
    assert payload["goal_amount"] > payload["current_total_assets"]
    assert payload["risk_preference"] == "保守"
    assert "不碰股票" in payload["restrictions"]


@pytest.mark.contract
def test_parse_onboarding_supports_english_in_months_phrase():
    payload = parse_onboarding(
        "please onboard user demo_user with current assets 50000 monthly 12000 goal 1000000 in 36 months risk moderate"
    )

    assert payload["account_profile_id"] == "demo_user"
    assert payload["goal_horizon_months"] == 36
    assert payload["risk_preference"] == "中等"


@pytest.mark.contract
def test_parse_approve_plan_allows_colon_in_plan_id():
    parsed = parse_approve_plan("approve plan run123:allocation_alpha v2 for user demo_user")

    assert parsed["account_profile_id"] == "demo_user"
    assert parsed["plan_id"] == "run123:allocation_alpha"
    assert parsed["plan_version"] == 2


@pytest.mark.contract
def test_parse_approve_plan_without_explicit_plan_id_keeps_user_context_only():
    parsed = parse_approve_plan("confirm plan for user demo_user")

    assert parsed["account_profile_id"] == "demo_user"
    assert parsed["plan_id"] is None
    assert parsed["plan_version"] == 1


@pytest.mark.contract
def test_parse_feedback_allows_colon_run_id_and_chinese_execution_language():
    parsed = parse_feedback("用户 demo_user 已执行，run_id: frontdesk:monthly:001 actual_action: rebalance_partial 备注：已处理")

    assert parsed["account_profile_id"] == "demo_user"
    assert parsed["run_id"] == "frontdesk:monthly:001"
    assert parsed["executed"] is True
    assert parsed["actual_action"] == "rebalance_partial"
    assert parsed["note"] == "已处理"


@pytest.mark.contract
def test_parse_event_context_respects_negated_rebalance_requests():
    parsed = parse_event_context("event review for user demo_user after drawdown, do not rebalance, manual review only")

    assert parsed["drawdown_event"] is True
    assert parsed["manual_review_requested"] is True
    assert "high_risk_request" not in parsed
    assert "requested_action" not in parsed


@pytest.mark.contract
@pytest.mark.parametrize(
    ("task", "expected_intent"),
    [
        ("run quarterly review for user demo_user", "quarterly"),
        ("event review for user demo_user after drawdown", "event"),
        ("show-user for user demo_user", "show_user"),
        ("show status for user demo_user after drawdown", "status"),
        ("用户 demo_user 已执行，run_id: frontdesk:monthly:001 actual_action: rebalance_partial 备注：已处理", "feedback"),
        ("promote for user demo_user", "approve_plan"),
        ("check user demo_user", "status"),
        ("why did the probability change for user demo_user", "explain_probability"),
        ("为什么建议替换方案 user demo_user", "explain_plan_change"),
    ],
)
def test_route_recognizes_wave4_intents(task, expected_intent):
    assert route(task).name == expected_intent
