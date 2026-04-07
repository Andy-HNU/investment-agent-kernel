from __future__ import annotations

import pytest

from calibration.types import (
    CalibrationSummary,
    DistributionModelState,
    ModeResolutionDecision,
    SimulationModeEligibility,
)


@pytest.mark.contract
def test_v13_mode_contract_dataclasses_validate_and_serialize():
    eligibility = SimulationModeEligibility(
        simulation_mode="static_gaussian",
        minimum_sample_months=0,
        minimum_weight_adjusted_coverage=0.0,
        requires_regime_stability=False,
        requires_jump_calibration=False,
        allowed_result_categories=[
            "formal_independent_result",
            "formal_estimated_result",
            "degraded_formal_result",
        ],
        downgrade_target=None,
        ineligibility_action="mark_unavailable",
    )
    decision = ModeResolutionDecision(
        requested_mode="static_gaussian",
        selected_mode="static_gaussian",
        eligible_modes_in_order=["static_gaussian"],
        ineligibility_action="mark_unavailable",
        downgraded=False,
        downgrade_reason=None,
    )
    summary = CalibrationSummary(
        sample_count=0,
        brier_score=None,
        reliability_buckets=[],
        regime_breakdown=[],
        calibration_quality="insufficient_sample",
        source_ref="bundle_acc001::static_gaussian",
    )
    state = DistributionModelState(
        simulation_mode="static_gaussian",
        selected_mode="static_gaussian",
        tail_model=None,
        regime_sensitive=False,
        jump_overlay_enabled=False,
        eligibility_decision=eligibility.to_dict(),
        mode_resolution_decision=decision.to_dict(),
        calibration_summary=summary.to_dict(),
        source_ref="bundle_acc001::static_gaussian",
        as_of="2026-03-29T12:00:00Z",
        data_status="observed",
    )

    assert state.simulation_mode == "static_gaussian"
    assert state.selected_mode == "static_gaussian"
    assert state.eligibility_decision.simulation_mode == "static_gaussian"
    assert state.mode_resolution_decision.requested_mode == "static_gaussian"
    assert state.calibration_summary is not None
    assert state.calibration_summary.calibration_quality == "insufficient_sample"
    assert state.to_dict()["mode_resolution_decision"]["selected_mode"] == "static_gaussian"
    assert state.to_dict()["calibration_summary"]["source_ref"] == "bundle_acc001::static_gaussian"


@pytest.mark.contract
def test_v13_mode_contract_rejects_invalid_actions_and_quality():
    with pytest.raises(ValueError, match="unknown ineligibility_action"):
        SimulationModeEligibility(
            simulation_mode="static_gaussian",
            minimum_sample_months=0,
            minimum_weight_adjusted_coverage=0.0,
            requires_regime_stability=False,
            requires_jump_calibration=False,
            allowed_result_categories=["formal_independent_result"],
            downgrade_target=None,
            ineligibility_action="silently_fallback",
        )

    with pytest.raises(ValueError, match="unknown calibration_quality"):
        CalibrationSummary(
            sample_count=0,
            brier_score=None,
            reliability_buckets=[],
            regime_breakdown=[],
            calibration_quality="good_enough",
            source_ref="bundle_acc001::static_gaussian",
        )
