from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_andy",
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=[],
    )


@pytest.mark.smoke
def test_frontdesk_cli_non_interactive_onboarding_smoke(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["workflow"] == "onboard"
    assert payload["status"] == "completed"
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    assert payload["user_state"]["decision_card"]["card_type"] == "goal_baseline"
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1


@pytest.mark.smoke
def test_frontdesk_cli_accepts_inline_profile_json(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["plan_id"]
        == payload["user_state"]["pending_execution_plan"]["plan_id"]
    )


@pytest.mark.smoke
def test_frontdesk_cli_status_reads_existing_state(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    first_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()
    assert first_exit_code == 0

    status_exit_code = main(
        [
            "status",
            "--db",
            str(db_path),
            "--user-id",
            profile.account_profile_id,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert status_exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    serialized = json.dumps(payload["user_state"], ensure_ascii=False, sort_keys=True)
    for label in ("用户提供", "系统推断", "默认假设", "外部抓取"):
        assert label in serialized


@pytest.mark.smoke
def test_frontdesk_cli_text_summary_surfaces_readable_candidates_and_disclaimer(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "onboarding",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "candidate_1=" in output
    assert "bucket_success=" in output
    assert "product_success=" in output
    assert "required_return=" in output
    assert "input_sources=" in output
    assert "model_disclaimer=" in output
    assert "goal_semantics:" in output
    assert "profile_model:" in output
    assert "refresh:" in output
    assert "pending_execution_plan:" in output
    assert "pending_execution_plan_proxy_mode=" in output
    assert "pending_execution_plan_proxy_covered_buckets=" in output
    assert "execution_feedback:" in output


@pytest.mark.smoke
def test_frontdesk_cli_approve_plan_promotes_pending_execution_plan(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert onboard_exit == 0
    assert approve_exit == 0
    assert payload["workflow"] == "approve_plan"
    assert payload["status"] == "approved"
    assert payload["approved_execution_plan"]["plan_id"] == pending_plan["plan_id"]
    assert payload["user_state"]["active_execution_plan"]["status"] == "approved"
    assert payload["user_state"]["pending_execution_plan"] is None


@pytest.mark.smoke
def test_frontdesk_cli_show_user_surfaces_execution_plan_comparison(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    capsys.readouterr()

    updated_profile = profile.to_dict()
    updated_profile["restrictions"] = ["不碰股票"]
    second_onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(updated_profile, ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()

    show_user_exit = main(
        [
            "show-user",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
        ]
    )
    output = capsys.readouterr().out

    assert onboard_exit == 0
    assert approve_exit == 0
    assert second_onboard_exit == 0
    assert show_user_exit == 0
    assert "execution_plan_comparison:" in output
    assert "recommendation=keep_active" in output
    assert "runtime_candidates=" in output
    assert "candidate_filter_drop_reasons=" in output
    assert "wrapper:stock" in output


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_degraded_scope_and_execution_eligibility():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "workflow": "onboard",
            "status": "completed",
            "refresh_summary": {
                "external_status": "fallback",
                "freshness_state": "fallback",
                "domain_details": [
                    {"domain": "market", "freshness_state": "fallback", "source_label": "外部抓取"},
                ],
            },
            "user_state": {
                "profile": {
                    "account_profile_id": "formal_path_user",
                    "display_name": "Andy",
                },
                "decision_card": {
                    "card_type": "goal_baseline",
                    "status_badge": "degraded",
                    "summary": "下面先展示临时参考，不应当作正式推荐。",
                    "primary_recommendation": "流动性缓冲方案",
                    "recommended_action": "adopt_recommended_plan",
                    "guardrails": ["calibration_quality=partial", "candidate_poverty=true"],
                    "recommendation_reason": [
                        "当前不存在满足你回撤约束的配置。",
                        "下面展示的是最接近可行的临时参考，不是正式推荐。",
                    ],
                    "execution_notes": ["manual_review_required"],
                    "input_provenance": {},
                },
            },
        }
    )

    assert "formal_path:" in output
    assert "degraded_scope=" in output
    assert "calibration" in output
    assert "market" in output
    assert "runtime_candidates" in output
    assert "fallback_used=true" in output
    assert "fallback_scope=" in output
    assert "external_snapshot" in output
    assert "goal_solver" in output
    assert "execution_eligible=false" in output


@pytest.mark.smoke
def test_frontdesk_cli_json_surfaces_formal_path_visibility(tmp_path, capsys, monkeypatch):
    from frontdesk import cli

    db_path = tmp_path / "frontdesk.sqlite"

    monkeypatch.setattr(
        cli,
        "run_frontdesk_onboarding",
        lambda *args, **kwargs: {
            "status": "completed",
            "run_id": "run_formal_path_cli",
            "user_state": {
                "profile": {"account_profile_id": "andy_cli", "display_name": "Andy"},
                "decision_card": {
                    "card_type": "goal_baseline",
                    "status_badge": "degraded",
                    "summary": "下面先展示临时参考，不应当作正式推荐。",
                    "primary_recommendation": "流动性缓冲方案",
                    "recommended_action": "adopt_recommended_plan",
                    "guardrails": ["bundle_quality=partial"],
                    "recommendation_reason": ["下面展示的是最接近可行的临时参考，不是正式推荐。"],
                    "input_provenance": {},
                },
            },
            "refresh_summary": {
                "external_status": "fallback",
                "freshness_state": "fallback",
                "domain_details": [{"domain": "market", "freshness_state": "fallback"}],
            },
            "external_snapshot_status": "fallback",
        },
    )

    exit_code = cli.main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(_profile().to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["formal_path_visibility"]["fallback_used"] is True
    assert payload["formal_path_visibility"]["execution_eligible"] is False
    assert payload["user_state"]["formal_path_visibility"]["degraded_scope"] == ["bundle", "market"]


@pytest.mark.smoke
def test_frontdesk_cli_json_preserves_policy_news_audit_summary(tmp_path, capsys, monkeypatch):
    from frontdesk import cli

    db_path = tmp_path / "frontdesk.sqlite"

    monkeypatch.setattr(
        cli,
        "run_frontdesk_onboarding",
        lambda *args, **kwargs: {
            "status": "completed",
            "run_id": "run_policy_news_cli",
            "decision_card": {
                "card_type": "goal_baseline",
                "execution_plan_summary": {
                    "plan_id": "plan_policy_news",
                    "policy_news_audit_summary": {
                        "source_status": "observed",
                        "realtime_eligible": True,
                        "matched_signal_count": 2,
                        "latest_published_at": "2026-04-04T12:00:00Z",
                    },
                },
            },
            "user_state": {
                "profile": {"account_profile_id": "andy_cli", "display_name": "Andy"},
                "decision_card": {
                    "card_type": "goal_baseline",
                    "execution_plan_summary": {
                        "plan_id": "plan_policy_news",
                        "policy_news_audit_summary": {
                            "source_status": "observed",
                            "realtime_eligible": True,
                            "matched_signal_count": 2,
                        },
                    },
                },
            },
        },
    )

    exit_code = cli.main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(_profile().to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["policy_news_audit_summary"]["source_status"]
        == "observed"
    )
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["policy_news_audit_summary"][
            "realtime_eligible"
        ]
        is True
    )


@pytest.mark.smoke
def test_render_frontdesk_summary_surfaces_execution_plan_valuation_audit():
    from frontdesk.cli import render_frontdesk_summary

    output = render_frontdesk_summary(
        {
            "workflow": "status",
            "status": "loaded",
            "user_state": {
                "profile": {
                    "account_profile_id": "valuation_audit_user",
                    "display_name": "Andy",
                },
                "decision_card": {
                    "card_type": "goal_baseline",
                    "summary": "估值筛选已进入产品层。",
                    "primary_recommendation": "防守优先方案",
                    "recommended_action": "review",
                    "input_provenance": {},
                },
                "pending_execution_plan": {
                    "plan_id": "run_val:allocation_val",
                    "plan_version": 1,
                    "status": "draft",
                    "item_count": 2,
                    "confirmation_required": True,
                    "runtime_candidate_count": 4,
                    "registry_candidate_count": 8,
                    "candidate_filter_dropped_reasons": {
                        "valuation:pe_above_40": 1,
                        "valuation:percentile_above_0.30": 1,
                    },
                    "valuation_audit_summary": {
                        "source_status": "observed",
                        "source_name": "akshare_dynamic_valuation",
                        "rule_max_pe": 40.0,
                        "rule_max_percentile": 0.30,
                        "applicable_candidate_count": 3,
                        "passed_candidate_count": 1,
                    },
                },
            },
        }
    )

    assert "pending_execution_plan_candidate_filter_drop_reasons=" in output
    assert "valuation:pe_above_40" in output
    assert "pending_execution_plan_valuation_audit=" in output
    assert "akshare_dynamic_valuation" in output
