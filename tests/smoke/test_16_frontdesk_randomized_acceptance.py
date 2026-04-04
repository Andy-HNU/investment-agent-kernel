from __future__ import annotations

from random import Random

import pytest

from frontdesk.service import (
    load_frontdesk_snapshot,
    load_user_state,
    record_frontdesk_execution_feedback,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from shared.onboarding import UserOnboardingProfile


_FAMILY_CONFIG = {
    "defensive": {
        "risk_preference": "保守",
        "drawdown": 0.08,
        "holdings": ["全现金", "纯黄金", "60%债券 40%货基"],
        "monthly_holdings": ["全现金", "70%债券 30%货基", "纯黄金"],
        "restrictions": [[], ["不碰科技"]],
        "goal_semantics": [
            {"goal_amount_basis": "nominal", "goal_amount_scope": "total_assets"},
            {"goal_amount_basis": "real", "goal_amount_scope": "total_assets", "tax_assumption": "after_tax"},
        ],
        "goal_multiplier": (0.95, 1.10),
    },
    "balanced": {
        "risk_preference": "中等",
        "drawdown": 0.12,
        "holdings": ["股债六四", "50%沪深300 30%债券 20%货基", "40%黄金 40%债券 20%货基"],
        "monthly_holdings": ["股债五五", "60%沪深300 20%债券 20%货基", "50%黄金 30%债券 20%货基"],
        "restrictions": [[], ["不碰科技"]],
        "goal_semantics": [
            {"goal_amount_basis": "nominal", "goal_amount_scope": "total_assets"},
            {"goal_amount_basis": "real", "goal_amount_scope": "incremental_gain", "fee_assumption": "platform_fee_excluded"},
        ],
        "goal_multiplier": (1.00, 1.25),
    },
    "growth": {
        "risk_preference": "进取",
        "drawdown": 0.18,
        "holdings": ["股债八二", "80%纳指 20%货基", "70%股票 20%债券 10%货基"],
        "monthly_holdings": ["股债七三", "75%纳指 25%货基", "60%股票 30%债券 10%货基"],
        "restrictions": [[], ["不买QDII"]],
        "goal_semantics": [
            {"goal_amount_basis": "nominal", "goal_amount_scope": "total_assets"},
            {"goal_amount_basis": "real", "goal_amount_scope": "incremental_gain", "contribution_commitment_confidence": 0.68},
        ],
        "goal_multiplier": (1.10, 1.45),
    },
    "restricted": {
        "risk_preference": "中等",
        "drawdown": 0.10,
        "holdings": ["纯黄金", "全现金", "60%债券 40%货基"],
        "monthly_holdings": ["全现金", "纯黄金", "70%债券 30%货基"],
        "restrictions": [["不碰股票"], ["不碰科技"]],
        "goal_semantics": [
            {"goal_amount_basis": "nominal", "goal_amount_scope": "total_assets"},
            {"goal_amount_basis": "real", "goal_amount_scope": "total_assets", "tax_assumption": "after_tax"},
        ],
        "goal_multiplier": (1.00, 1.20),
    },
}


def _profile_for_seed(seed: int, family: str) -> UserOnboardingProfile:
    rng = Random(seed)
    config = _FAMILY_CONFIG[family]
    current_total_assets = float(rng.randrange(30_000, 160_001, 1_000))
    monthly_contribution = float(rng.randrange(3_000, 15_001, 1_000))
    goal_horizon_months = rng.choice([24, 36, 60, 84])
    goal_floor = current_total_assets + monthly_contribution * goal_horizon_months
    goal_amount = round(goal_floor * rng.uniform(*config["goal_multiplier"]), -3)
    semantics = dict(rng.choice(config["goal_semantics"]))
    return UserOnboardingProfile(
        account_profile_id=f"acceptance_{family}_{seed}",
        display_name=f"{family}_{seed}",
        current_total_assets=current_total_assets,
        monthly_contribution=monthly_contribution,
        goal_amount=float(goal_amount),
        goal_horizon_months=goal_horizon_months,
        risk_preference=config["risk_preference"],
        max_drawdown_tolerance=float(config["drawdown"]),
        current_holdings=rng.choice(config["holdings"]),
        restrictions=list(rng.choice(config["restrictions"])),
        goal_amount_basis=str(semantics.get("goal_amount_basis", "nominal")),
        goal_amount_scope=str(semantics.get("goal_amount_scope", "total_assets")),
        tax_assumption=str(semantics.get("tax_assumption", "pre_tax")),
        fee_assumption=str(semantics.get("fee_assumption", "transaction_cost_only")),
        contribution_commitment_confidence=semantics.get("contribution_commitment_confidence"),
    )


def _monthly_override(profile: UserOnboardingProfile, seed: int) -> dict[str, object]:
    rng = Random(seed + 10_000)
    config = _FAMILY_CONFIG[
        "restricted"
        if profile.restrictions in _FAMILY_CONFIG["restricted"]["restrictions"]
        else (
            "growth"
            if profile.risk_preference == "进取"
            else "defensive"
            if profile.risk_preference == "保守"
            else "balanced"
        )
    ]
    drift = rng.uniform(-0.08, 0.20)
    return {
        "current_total_assets": round(profile.current_total_assets * (1.0 + drift), 2),
        "current_holdings": rng.choice(config["monthly_holdings"]),
        "restrictions": list(profile.restrictions),
    }


def _assert_profile_restrictions_respected(snapshot: dict[str, object], onboarding_summary: dict[str, object]) -> None:
    profile = snapshot["profile"]["profile"]
    candidate_options = onboarding_summary.get("candidate_options") or []
    restrictions = set(profile.get("restrictions") or [])

    if "不碰股票" in restrictions or "只能黄金和现金" in restrictions:
        assert "equity_cn" in set(profile.get("forbidden_buckets") or [])
        assert "satellite" in set(profile.get("forbidden_buckets") or [])
        for option in candidate_options:
            rendered_mix = " ".join(option.get("allocation_mix") or [])
            assert "权益" not in rendered_mix
            assert "卫星" not in rendered_mix
    if "不碰科技" in restrictions:
        assert "technology" in set(profile.get("forbidden_themes") or [])


def _assert_p1_profile_model_present(snapshot: dict[str, object], onboarding_summary: dict[str, object]) -> None:
    profile = snapshot["profile"]["profile"]
    goal_semantics = dict(profile.get("goal_semantics") or {})
    profile_dimensions = dict(profile.get("profile_dimensions") or {})
    model_inputs = dict(profile_dimensions.get("model_inputs") or {})

    assert goal_semantics.get("goal_amount_basis") in {"nominal", "real"}
    assert goal_semantics.get("goal_amount_scope") in {"total_assets", "incremental_gain", "spending_need"}
    assert "explanation" in goal_semantics
    assert model_inputs.get("goal_priority") in {"essential", "important", "aspirational"}
    assert 0.0 <= float(model_inputs.get("risk_tolerance_score", 0.0)) <= 1.0
    assert 0.0 <= float(model_inputs.get("risk_capacity_score", 0.0)) <= 1.0
    assert onboarding_summary.get("goal_semantics")
    assert onboarding_summary.get("profile_dimensions")


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("seed", "family"),
    [
        (13, "defensive"),
        (31, "growth"),
        (53, "restricted"),
    ],
)
def test_randomized_frontdesk_acceptance_onboarding_three_profiles(seed, family, tmp_path):
    profile = _profile_for_seed(seed, family)
    db_path = tmp_path / f"onboarding_{profile.account_profile_id}.sqlite"

    onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert onboarding["status"] in {"completed", "degraded"}
    assert onboarding["status"] != "blocked"
    assert onboarding["candidate_options"] or onboarding["goal_alternatives"]
    assert snapshot is not None
    assert snapshot["latest_baseline"]["run_id"] == onboarding["run_id"]
    _assert_profile_restrictions_respected(snapshot, onboarding)
    _assert_p1_profile_model_present(snapshot, onboarding)


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("seed", "family"),
    [
        (17, "defensive"),
        (37, "balanced"),
        (59, "restricted"),
    ],
)
def test_randomized_frontdesk_acceptance_monthly_continuity_three_profiles(seed, family, tmp_path):
    profile = _profile_for_seed(seed, family)
    db_path = tmp_path / f"monthly_{profile.account_profile_id}.sqlite"

    onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        profile=_monthly_override(profile, seed),
    )
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert onboarding["status"] in {"completed", "degraded"}
    assert onboarding["status"] != "blocked"
    assert monthly["status"] in {"completed", "degraded"}
    assert monthly["status"] != "blocked"
    assert snapshot is not None
    assert snapshot["latest_run"]["workflow_type"] == "monthly"
    _assert_p1_profile_model_present(snapshot, onboarding)


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("seed", "family"),
    [
        (11, "defensive"),
        (29, "balanced"),
        (47, "restricted"),
    ],
)
def test_randomized_frontdesk_acceptance_full_flow(seed, family, tmp_path):
    profile = _profile_for_seed(seed, family)
    db_path = tmp_path / f"{profile.account_profile_id}.sqlite"

    onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    snapshot_after_onboarding = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert onboarding["status"] in {"completed", "degraded"}
    assert onboarding["status"] != "blocked"
    assert onboarding["input_provenance"]["counts"]["user_provided"] >= 8
    assert onboarding["candidate_options"] or onboarding["goal_alternatives"]
    assert snapshot_after_onboarding is not None
    assert snapshot_after_onboarding["profile"]["profile"]["account_profile_id"] == profile.account_profile_id
    _assert_profile_restrictions_respected(snapshot_after_onboarding, onboarding)
    _assert_p1_profile_model_present(snapshot_after_onboarding, onboarding)

    monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        profile=_monthly_override(profile, seed),
    )
    snapshot_after_monthly = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert monthly["status"] in {"completed", "degraded"}
    assert monthly["status"] != "blocked"
    assert snapshot_after_monthly is not None
    assert snapshot_after_monthly["latest_run"]["workflow_type"] == "monthly"

    feedback = record_frontdesk_execution_feedback(
        account_profile_id=profile.account_profile_id,
        source_run_id=monthly["run_id"],
        user_executed=bool(seed % 2),
        actual_action=monthly["decision_card"].get("recommended_action"),
        note=f"seed={seed}",
        db_path=db_path,
    )
    user_state = load_user_state(profile.account_profile_id, db_path=db_path)

    assert feedback["status"] == "recorded"
    assert feedback["execution_feedback"]["source_run_id"] == monthly["run_id"]
    assert user_state is not None
    assert user_state["latest_result"]["workflow_type"] == "monthly"
    assert user_state["execution_feedback"]["source_run_id"] == monthly["run_id"]
    assert user_state["execution_feedback_summary"]["counts"]["executed"] + user_state["execution_feedback_summary"]["counts"]["skipped"] >= 1
