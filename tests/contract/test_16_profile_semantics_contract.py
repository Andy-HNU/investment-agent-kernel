from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk.service import load_frontdesk_snapshot, run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from shared.profile_parser import parse_profile_semantics


def _restricted_profile(*, account_profile_id: str) -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="AndyClaw",
        current_total_assets=52_000.0,
        monthly_contribution=10_000.0,
        goal_amount=450_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="纯黄金",
        restrictions=["不碰股票"],
    )


@pytest.mark.contract
def test_profile_parser_compiles_known_constraints_and_marks_unknown_restrictions():
    parsed = parse_profile_semantics(
        current_holdings="纯黄金",
        restrictions=["不碰股票"],
    )

    assert parsed.current_weights == {"gold": 1.0}
    assert parsed.forbidden_buckets == ["equity_cn", "satellite"]
    assert parsed.warnings == []
    assert parsed.requires_confirmation is False

    partial = parse_profile_semantics(
        current_holdings="80%纳指 20%货基",
        restrictions=["不碰股票", "禁止衍生品"],
    )

    assert partial.current_weights == {"equity_cn": 0.8}
    assert partial.restrictions_parse_status == "partial"
    assert partial.requires_confirmation is True
    assert any("未解析" in warning for warning in partial.warnings)


@pytest.mark.contract
def test_onboarding_build_makes_target_explicit_and_compiles_restricted_constraints():
    bundle = build_user_onboarding_inputs(_restricted_profile(account_profile_id="contract_profile"))

    assert bundle.profile.current_weights == {"gold": 1.0}
    assert bundle.profile.forbidden_buckets == ["equity_cn", "satellite"]
    assert "目标期末总资产" in bundle.goal_solver_input["goal"]["goal_description"]
    assert bundle.goal_solver_input["constraints"]["ips_bucket_boundaries"]["equity_cn"] == (0.0, 0.0)
    assert bundle.goal_solver_input["constraints"]["ips_bucket_boundaries"]["satellite"] == (0.0, 0.0)
    assert bundle.goal_solver_input["constraints"]["ips_bucket_boundaries"]["bond_cn"][1] >= 0.85
    assert (
        bundle.raw_inputs["allocation_engine_input"]["account_profile"]["forbidden_buckets"]
        == ["equity_cn", "satellite"]
    )
    goal_amount_item = next(
        item for item in bundle.input_provenance["user_provided"] if item["field"] == "goal.goal_amount"
    )
    assert goal_amount_item["label"] == "目标期末总资产"
    assert "不是收益目标" in goal_amount_item["note"]


@pytest.mark.contract
def test_frontdesk_onboarding_does_not_block_restricted_no_stock_profile(tmp_path):
    profile = _restricted_profile(account_profile_id="restricted_frontdesk")

    summary = run_frontdesk_onboarding(profile, db_path=tmp_path / "restricted.sqlite")

    assert summary["status"] in {"completed", "degraded"}
    assert summary["status"] != "blocked"
    assert summary["candidate_options"]
    for option in summary["candidate_options"]:
        rendered_mix = " ".join(option.get("allocation_mix") or [])
        assert "权益" not in rendered_mix
        assert "卫星" not in rendered_mix
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=tmp_path / "restricted.sqlite")
    assert snapshot is not None
    assert snapshot["profile"]["profile"]["forbidden_buckets"] == ["equity_cn", "satellite"]


@pytest.mark.contract
def test_frontdesk_followup_reparses_updated_holdings_instead_of_reusing_stale_weights(tmp_path):
    db_path = tmp_path / "followup.sqlite"
    profile = _restricted_profile(account_profile_id="followup_reparse")

    run_frontdesk_onboarding(profile, db_path=db_path)
    monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        profile={"current_holdings": "全现金"},
    )
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert monthly["status"] in {"completed", "degraded"}
    assert monthly["status"] != "blocked"
    assert snapshot is not None
    assert snapshot["latest_run"]["workflow_type"] == "monthly"
    assert snapshot["profile"]["profile"]["current_holdings"] == "全现金"
    assert snapshot["profile"]["profile"]["current_weights"] == {}


@pytest.mark.contract
def test_long_natural_language_profile_text_flows_into_constraints_and_profile_model(tmp_path):
    db_path = tmp_path / "long_nl.sqlite"
    profile = UserOnboardingProfile(
        account_profile_id="long_form_profile",
        display_name="LongForm",
        current_total_assets=88_000.0,
        monthly_contribution=9_000.0,
        goal_amount=420_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="我现在账户里基本是纯黄金，短期内还是想先稳住，不考虑加别的风险资产。",
        restrictions=["我明确不碰股票，而且也不碰科技主题。"],
    )

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert summary["status"] in {"completed", "degraded"}
    assert snapshot is not None
    persisted_profile = snapshot["profile"]["profile"]
    assert persisted_profile["current_weights"] == {"gold": 1.0}
    assert "equity_cn" in set(persisted_profile["forbidden_buckets"] or [])
    assert "satellite" in set(persisted_profile["forbidden_buckets"] or [])
    assert summary["goal_semantics"]["goal_amount_scope"] == "total_assets"
    assert summary["profile_dimensions"]["model_inputs"]["goal_priority"] in {"important", "essential", "aspirational"}


@pytest.mark.contract
def test_degraded_onboarding_still_persists_baseline_and_allows_monthly_followup(tmp_path):
    db_path = tmp_path / "degraded_followup.sqlite"
    profile = _restricted_profile(account_profile_id="degraded_followup")

    onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        profile={"current_holdings": "全现金"},
    )
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert onboarding["status"] == "degraded"
    assert monthly["status"] in {"completed", "degraded"}
    assert monthly["status"] != "blocked"
    assert snapshot is not None
    assert snapshot["latest_baseline"]["run_id"] == onboarding["run_id"]
    assert snapshot["latest_run"]["workflow_type"] == "monthly"


@pytest.mark.contract
def test_release_gate_blocks_demo_builders_in_production_entrypoints():
    repo_root = Path(__file__).resolve().parents[2]
    production_paths = [
        repo_root / "src/frontdesk/service.py",
        repo_root / "src/frontdesk/cli.py",
        repo_root / "src/shared/onboarding.py",
        repo_root / "src/shared/product_defaults.py",
    ]

    for path in production_paths:
        text = path.read_text(encoding="utf-8")
        assert "build_demo_" not in text, f"demo builder leaked into production path: {path}"
        assert 'preferred_themes=["technology"]' not in text.replace(" ", ""), f"hardcoded product bias leaked into {path}"
    assert "technology" not in (repo_root / "src/shared/product_defaults.py").read_text(encoding="utf-8")
