from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk.service import load_frontdesk_snapshot, run_frontdesk_followup, run_frontdesk_onboarding
from frontdesk.storage import FrontdeskStore
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
    assert parsed.forbidden_buckets == []
    assert parsed.forbidden_wrappers == ["stock"]
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
def test_profile_parser_compiles_canonical_restriction_tokens_without_partial_warning():
    parsed = parse_profile_semantics(
        current_holdings="",
        restrictions=["no_stock_picking", "forbidden_theme:technology", "no_qdii"],
    )

    assert parsed.forbidden_wrappers == ["stock"]
    assert parsed.forbidden_themes == ["technology"]
    assert parsed.qdii_allowed is False
    assert parsed.restrictions_parse_status == "parsed"
    assert parsed.requires_confirmation is False
    assert parsed.warnings == []


@pytest.mark.contract
def test_profile_parser_parses_amount_based_cash_and_gold_holdings():
    parsed = parse_profile_semantics(
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )

    assert parsed.holdings_parse_status == "parsed"
    assert parsed.current_weights == {"gold": 0.3333}
    assert parsed.available_cash_fraction == pytest.approx(0.6667, abs=1e-4)
    assert any("显式金额" in note for note in parsed.notes)


@pytest.mark.contract
def test_profile_parser_parses_reverse_order_amount_holdings_without_cash_bleed():
    parsed = parse_profile_semantics(
        current_holdings="黄金 6000 现金 12000",
        restrictions=[],
    )

    assert parsed.holdings_parse_status == "parsed"
    assert parsed.current_weights == {"gold": 0.3333}
    assert parsed.available_cash_fraction == pytest.approx(0.6667, abs=1e-4)


@pytest.mark.contract
def test_profile_parser_does_not_double_count_explicit_cash_bucket():
    parsed = parse_profile_semantics(
        current_holdings="",
        restrictions=[],
        explicit_current_weights={"gold": 0.2, "cash_liquidity": 0.3},
    )

    assert parsed.current_weights == {"gold": 0.2, "cash_liquidity": 0.3}
    assert parsed.available_cash_fraction == pytest.approx(0.0, abs=1e-6)


@pytest.mark.contract
def test_profile_parser_splits_compound_restriction_clauses_and_compiles_high_risk_filter():
    parsed = parse_profile_semantics(
        current_holdings="",
        restrictions=["不买个股，而且不碰科技主题；不碰高风险产品"],
    )

    assert parsed.forbidden_wrappers == ["stock"]
    assert parsed.forbidden_themes == ["technology"]
    assert parsed.forbidden_risk_labels == ["high_risk_product"]
    assert parsed.restrictions_parse_status == "parsed"
    assert parsed.warnings == []


@pytest.mark.contract
def test_onboarding_build_makes_target_explicit_and_compiles_restricted_constraints():
    bundle = build_user_onboarding_inputs(_restricted_profile(account_profile_id="contract_profile"))

    assert bundle.profile.current_weights == {"gold": 1.0}
    assert bundle.profile.forbidden_buckets == []
    assert bundle.profile.forbidden_wrappers == ["stock"]
    assert "目标期末总资产" in bundle.goal_solver_input["goal"]["goal_description"]
    assert bundle.goal_solver_input["constraints"]["ips_bucket_boundaries"]["equity_cn"][1] > 0.0
    assert bundle.goal_solver_input["constraints"]["ips_bucket_boundaries"]["satellite"][1] > 0.0
    assert (
        bundle.raw_inputs["allocation_engine_input"]["account_profile"]["forbidden_buckets"]
        == []
    )
    assert bundle.raw_inputs["allocation_engine_input"]["account_profile"]["forbidden_wrappers"] == ["stock"]
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
    pending_plan = summary["user_state"]["pending_execution_plan"]
    assert pending_plan is not None
    assert int(pending_plan["runtime_candidate_count"]) > 0
    assert "wrapper:stock" in set((pending_plan.get("candidate_filter_dropped_reasons") or {}).keys())
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=tmp_path / "restricted.sqlite")
    assert snapshot is not None
    assert snapshot["profile"]["profile"]["forbidden_buckets"] == []
    assert snapshot["profile"]["profile"]["forbidden_wrappers"] == ["stock"]


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
    assert "stock" in set(persisted_profile["forbidden_wrappers"] or [])
    assert "technology" in set(persisted_profile["forbidden_themes"] or [])
    assert "satellite" not in set(persisted_profile["forbidden_buckets"] or [])
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
def test_frontdesk_onboarding_compiles_canonical_theme_restriction_into_execution_plan(tmp_path):
    db_path = tmp_path / "canonical_theme.sqlite"
    profile = UserOnboardingProfile(
        account_profile_id="canonical_theme_profile",
        display_name="CanonicalTheme",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=["no_stock_picking", "forbidden_theme:technology"],
    )

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)
    assert summary["status"] in {"completed", "degraded"}
    assert snapshot is not None
    persisted_profile = snapshot["profile"]["profile"]
    assert "stock" in set(persisted_profile["forbidden_wrappers"] or [])
    assert "technology" in set(persisted_profile["forbidden_themes"] or [])
    assert not any("限制条件未能稳定编译" in note for note in persisted_profile.get("profile_parse_notes") or [])

    pending = snapshot["pending_execution_plan"]
    assert pending is not None
    plan_record = FrontdeskStore(db_path).get_execution_plan_record(
        profile.account_profile_id,
        plan_id=str(pending["plan_id"]),
        plan_version=int(pending["plan_version"]),
    )
    assert plan_record is not None
    selected_tags = {
        str(tag)
        for item in list((plan_record.payload or {}).get("items") or [])
        for tag in list(((item or {}).get("primary_product") or {}).get("tags") or [])
    }
    assert "technology" not in selected_tags
    assert any(
        "theme:technology" in reason
        for reason in dict(pending.get("candidate_filter_dropped_reasons") or {}).keys()
    )


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
