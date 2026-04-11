from __future__ import annotations

from copy import deepcopy

import pytest

import orchestrator.engine as orchestrator_engine
from dataclasses import replace
from frontdesk.service import run_frontdesk_onboarding
from probability_engine.contracts import (
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
)
from shared.onboarding import UserOnboardingProfile
from tests.contract.test_12_frontdesk_regression import (
    _formal_market_raw_overrides,
    _observed_external_snapshot_source,
)
from tests.support.formal_snapshot_helpers import write_formal_snapshot_source


def _override_primary_recipe_for_smoke(monkeypatch, *, path_count: int = 32) -> None:
    from probability_engine import recipes as recipe_module

    override = replace(recipe_module.PRIMARY_RECIPE_V14, path_count=path_count)
    monkeypatch.setattr(recipe_module, "PRIMARY_RECIPE_V14", override)
    monkeypatch.setitem(recipe_module.RECIPE_REGISTRY, override.recipe_name, override)


@pytest.fixture(autouse=True)
def _fast_primary_recipe(monkeypatch):
    _override_primary_recipe_for_smoke(monkeypatch)


def _profile(*, account_profile_id: str = "frontdesk_v14_formal_daily_smoke") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="FormalDailySmoke",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )


def _smoke_probability_result() -> ProbabilityEngineRunResult:
    return ProbabilityEngineRunResult(
        run_outcome_status="degraded",
        resolved_result_category="degraded_formal_result",
        output=ProbabilityEngineOutput(
            primary_result=RecipeSimulationResult(
                recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
                role="primary",
                success_probability=0.54,
                success_probability_range=(0.49, 0.58),
                cagr_range=(0.02, 0.06),
                drawdown_range=(0.10, 0.18),
                sample_count=128,
                path_stats=PathStatsSummary(
                    terminal_value_mean=108_000.0,
                    terminal_value_p05=81_000.0,
                    terminal_value_p50=105_000.0,
                    terminal_value_p95=126_000.0,
                    cagr_p05=0.02,
                    cagr_p50=0.04,
                    cagr_p95=0.06,
                    max_drawdown_p05=0.08,
                    max_drawdown_p50=0.13,
                    max_drawdown_p95=0.18,
                    success_count=69,
                    path_count=128,
                ),
                calibration_link_ref="evidence://smoke/v14",
            ),
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=ProbabilityDisclosurePayload(
                published_point=None,
                published_range=(0.49, 0.58),
                disclosure_level="range_only",
                confidence_level="low",
                challenger_gap=None,
                stress_gap=None,
                gap_total=None,
                widening_method="smoke_fixture",
            ),
            evidence_refs=["evidence://smoke/v14"],
        ),
        failure_artifact=None,
    )


@pytest.mark.smoke
def test_frontdesk_onboarding_surfaces_v14_formal_daily_probability_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile()
    captured: dict[str, object] = {}

    def _capture(sim_input: dict[str, object]) -> ProbabilityEngineRunResult:
        captured.update(deepcopy(sim_input))
        return _smoke_probability_result()

    monkeypatch.setattr(orchestrator_engine, "run_probability_engine", _capture)

    result = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )

    assert captured["path_horizon_days"] == captured["success_event_spec"]["horizon_days"]
    assert result["run_outcome_status"] in {"completed", "degraded"}
    assert result["resolved_result_category"] in {
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert result["monthly_fallback_used"] is False
    assert result["bucket_fallback_used"] is False
    assert isinstance(result["disclosure_decision"], dict)
    assert result["disclosure_decision"]
    assert isinstance(result["evidence_bundle"], dict)
    assert result["evidence_bundle"]

    probability_result = dict(result.get("probability_engine_result") or {})
    probability_output = dict(probability_result.get("output") or {})
    disclosure_payload = dict(probability_output.get("probability_disclosure_payload") or {})

    assert probability_result
    assert probability_result["run_outcome_status"] in {"success", "degraded"}
    expected_top_level_status = (
        "completed" if probability_result["run_outcome_status"] == "success" else probability_result["run_outcome_status"]
    )
    assert result["run_outcome_status"] == expected_top_level_status
    assert probability_result["resolved_result_category"] != "formal_strict_result"
    assert disclosure_payload.get("confidence_level") != "high"


@pytest.mark.smoke
def test_frontdesk_onboarding_surfaces_live_probability_disclosure_gap_fields(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="frontdesk_v14_live_gap_smoke")
    snapshot_source = _observed_external_snapshot_source(
        tmp_path,
        profile,
        market_raw_overrides=_formal_market_raw_overrides(),
    )

    result = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=snapshot_source,
    )

    probability_result = dict(result.get("probability_engine_result") or {})
    probability_output = dict(probability_result.get("output") or {})
    disclosure_payload = dict(probability_output.get("probability_disclosure_payload") or {})

    assert probability_result
    assert probability_result["run_outcome_status"] in {"success", "degraded"}
    assert probability_output.get("challenger_results"), "expected live challenger_results to be populated"
    assert probability_output.get("stress_results"), "expected live stress_results to be populated"
    assert probability_output.get("model_disagreement", {}).get("gap_total") is not None
    assert disclosure_payload.get("challenger_gap") is not None
    assert disclosure_payload.get("stress_gap") is not None
    assert disclosure_payload.get("gap_total") is not None


@pytest.mark.smoke
def test_frontdesk_onboarding_helper_snapshot_can_surface_formal_strict_probability_truth(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="frontdesk_v14_live_strict_smoke")
    snapshot_source = write_formal_snapshot_source(tmp_path, profile)

    result = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=snapshot_source,
    )

    probability_result = dict(result.get("probability_engine_result") or {})
    probability_output = dict(probability_result.get("output") or {})
    disclosure_payload = dict(probability_output.get("probability_disclosure_payload") or {})

    assert result["run_outcome_status"] == "completed"
    assert result["resolved_result_category"] == "formal_independent_result"
    assert result["product_probability_method"] == "product_independent_path"
    assert probability_result["run_outcome_status"] == "success"
    assert probability_result["resolved_result_category"] == "formal_strict_result"
    assert disclosure_payload.get("disclosure_level") == "point_and_range"
