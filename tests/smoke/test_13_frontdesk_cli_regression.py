from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "frontdesk_regression_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
    )


@pytest.mark.smoke
def test_frontdesk_cli_non_interactive_missing_input_fails_fast(tmp_path, monkeypatch):
    from frontdesk.cli import main

    db_path = tmp_path / "frontdesk.sqlite"

    def _unexpected_input(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("prompt should not run in non-interactive mode")

    monkeypatch.setattr("builtins.input", _unexpected_input)

    with pytest.raises(SystemExit, match="non-interactive onboarding requires"):
        main(
            [
                "onboard",
                "--db",
                str(db_path),
                "--non-interactive",
                "--display-name",
                "Andy",
            ]
        )


@pytest.mark.smoke
def test_frontdesk_cli_followup_profile_json_updates_state_and_output(tmp_path, capsys):
    from frontdesk.cli import main
    from frontdesk.service import load_user_state

    account_profile_id = "frontdesk_followup_profile_update"
    db_path = tmp_path / "frontdesk.sqlite"

    baseline_profile = _profile(account_profile_id=account_profile_id)
    baseline_path = tmp_path / "baseline_profile.json"
    baseline_path.write_text(
        json.dumps(baseline_profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    onboarding_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(baseline_path),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()
    assert onboarding_exit_code == 0

    updated_profile = baseline_profile.to_dict()
    updated_profile["display_name"] = "Andy Updated"
    updated_profile["current_total_assets"] = 62_000.0
    updated_profile["current_holdings"] = "cash"
    updated_profile_path = tmp_path / "updated_profile.json"
    updated_profile_path.write_text(
        json.dumps(updated_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monthly_exit_code = main(
        [
            "monthly",
            "--db",
            str(db_path),
            "--account-profile-id",
            account_profile_id,
            "--profile-json",
            str(updated_profile_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert monthly_exit_code == 0
    assert payload["display_name"] == "Andy Updated"
    assert payload["workflow_type"] == "monthly"

    user_state = load_user_state(account_profile_id, db_path=db_path)
    assert user_state is not None
    assert user_state["profile"]["display_name"] == "Andy Updated"
    assert user_state["profile"]["current_total_assets"] == 62_000.0
    assert user_state["profile"]["current_holdings"] == "cash"
    assert user_state["latest_result"]["workflow_type"] == "monthly"


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_wave1_probability_fields():
    from frontdesk.cli import render_frontdesk_summary

    rendered = render_frontdesk_summary(
        {
            "account_profile_id": "wave1_summary_user",
            "display_name": "Andy",
            "workflow_type": "onboarding",
            "status": "completed",
            "decision_card": {
                "card_type": "goal_baseline",
                "summary": "summary",
                "primary_recommendation": "稳健推进方案",
                "recommended_action": "adopt_recommended_plan",
                "model_disclaimer": "以下为模型模拟结果，不是历史回测收益承诺。",
            },
            "key_metrics": {
                "success_probability": "72.00%",
                "max_drawdown_90pct": "16.00%",
                "shortfall_probability": "28.00%",
                "expected_terminal_value": "¥1,030,000",
                "simulation_mode": "garch_t_dcc",
                "implied_required_annual_return": "8.12%",
                "highest_probability_success": "76.00%",
            },
            "input_provenance": {},
            "candidate_options": [
                {
                    "label": "稳健推进方案",
                    "highlight": "系统推荐",
                    "success_probability": "72.00%",
                    "max_drawdown_90pct": "16.00%",
                    "shortfall_probability": "28.00%",
                },
                {
                    "label": "增长倾向方案",
                    "highlight": "达成率更高",
                    "success_probability": "76.00%",
                    "max_drawdown_90pct": "24.00%",
                    "shortfall_probability": "24.00%",
                },
            ],
            "goal_alternatives": [],
            "goal_semantics": {},
            "profile_dimensions": {},
            "simulation_mode_used": "garch_t_dcc",
            "implied_required_annual_return": "8.12%",
            "highest_probability_result": {
                "allocation_name": "growth_tilt__aggressive__01",
                "success_probability": 0.76,
            },
        }
    )

    assert "simulation_mode=garch_t_dcc" in rendered
    assert "implied_required_annual_return=8.12%" in rendered
    assert "highest_probability_allocation=growth_tilt__aggressive__01" in rendered
    assert "highest_probability_success=76.00%" in rendered


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_blocked_execution_plan_details():
    from frontdesk.cli import render_frontdesk_summary

    rendered = render_frontdesk_summary(
        {
            "workflow": "onboard",
            "status": "blocked",
            "refresh_summary": {},
            "user_state": {
                "profile": {"account_profile_id": "blocked_user", "display_name": "Andy"},
                "decision_card": {
                    "card_type": "blocked",
                    "summary": "当前执行计划无法落地，需要调整约束或替代产品。",
                    "input_provenance": {},
                },
                "active_execution_plan": None,
                "pending_execution_plan": None,
                "blocked_execution_plan": {
                    "plan_id": "blocked_plan",
                    "plan_version": 1,
                    "status": "blocked",
                    "item_count": 1,
                    "coverage_ratio": 0.6,
                    "confirmation_required": False,
                    "warnings": ["资金桶 qdii 当前因用户限制无法执行。"],
                    "unmapped_bucket_count": 0,
                    "degraded_bucket_count": 0,
                    "items_preview": [
                        {
                            "asset_bucket": "bond_cn",
                            "target_weight": 0.6,
                            "primary_product_id": "cn_bond_gov_etf",
                            "primary_product_name": "国债ETF",
                            "alternate_product_ids": [],
                            "alternate_product_names": [],
                        }
                    ],
                },
            },
        }
    )

    assert "blocked_execution_plan:" in rendered
    assert "blocked_execution_plan_warning=资金桶 qdii 当前因用户限制无法执行。" in rendered
    assert "blocked_execution_plan_item: bucket=bond_cn" in rendered


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_blocked_execution_plan_details():
    from frontdesk.cli import render_frontdesk_summary

    rendered = render_frontdesk_summary(
        {
            "workflow": "status",
            "status": "blocked",
            "user_state": {
                "profile": {
                    "account_profile_id": "blocked_plan_user",
                    "display_name": "Blocked User",
                },
                "decision_card": {
                    "card_type": "status",
                    "summary": "需要先处理被阻断的执行计划。",
                    "primary_recommendation": "review_plan_blockers",
                    "recommended_action": "review",
                    "input_provenance": {},
                },
                "blocked_execution_plan": {
                    "plan_id": "blocked_plan",
                    "plan_version": 1,
                    "status": "blocked",
                    "item_count": 1,
                    "coverage_ratio": 0.6,
                    "confirmation_required": False,
                    "warnings": ["资金桶 qdii_global 当前因用户限制无法执行。"],
                    "unmapped_buckets": [],
                    "degraded_buckets": [],
                    "items_preview": [
                        {
                            "asset_bucket": "bond_cn",
                            "target_weight": 0.6,
                            "primary_product_id": "cn_bond_gov_etf",
                            "primary_product_name": "国债ETF",
                            "alternate_product_ids": [],
                            "alternate_product_names": [],
                        }
                    ],
                },
            },
        }
    )

    assert "blocked_execution_plan: plan_id=blocked_plan" in rendered
    assert "blocked_execution_plan_warning=资金桶 qdii_global 当前因用户限制无法执行。" in rendered
    assert "blocked_execution_plan_item: bucket=bond_cn" in rendered
