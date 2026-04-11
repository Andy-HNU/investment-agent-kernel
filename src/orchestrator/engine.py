from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any

import numpy as np

from allocation_engine.engine import run_allocation_engine
from calibration.engine import run_calibration
from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType
from goal_solver.engine import run_goal_solver
from goal_solver.types import normalize_product_probability_method
from probability_engine.engine import run_probability_engine
from product_mapping import build_candidate_product_context, build_execution_plan
from product_mapping.types import ProductCandidate
from product_mapping.runtime_inputs import enrich_market_raw_with_runtime_product_inputs
from runtime_optimizer.engine import run_runtime_optimizer
from runtime_optimizer.types import RuntimeOptimizerMode
from snapshot_ingestion.engine import build_snapshot_bundle
from shared.audit import (
    AuditWindow,
    CoverageSummary,
    DataStatus,
    DisclosureDecision,
    EvidenceBundle,
    ExecutionPolicy,
    FailureArtifact,
    RunOutcomeStatus,
    build_evidence_invariance_report,
    coerce_data_status,
    coerce_execution_policy,
)

from orchestrator.types import (
    OrchestratorAuditRecord,
    OrchestratorPersistencePlan,
    OrchestratorResult,
    RuntimeRestriction,
    TriggerSignal,
    WorkflowDecision,
    WorkflowStatus,
    WorkflowType,
)


_GOAL_SOLVER_CONSTRAINT_FIELDS = (
    "max_drawdown_tolerance",
    "ips_bucket_boundaries",
    "satellite_cap",
    "theme_caps",
    "qdii_cap",
    "liquidity_reserve_min",
    "bucket_category",
    "bucket_to_theme",
)

_SAFE_ACTION_TYPES = ("freeze", "observe")
_FORMAL_PATH_REQUIRED_FIELDS = {"market_raw", "account_raw", "behavior_raw", "live_portfolio"}
_FORMAL_EXECUTION_POLICIES = {
    ExecutionPolicy.FORMAL_STRICT,
    ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED,
}
_GATE1_SOURCE_PRIORITY = {
    "externally_fetched": 5,
    "user_provided": 4,
    "system_inferred": 3,
    "default_assumed": 2,
    "synthetic_demo": 1,
}
_GATE1_DATA_STATUS_PRIORITY = {
    DataStatus.OBSERVED: 5,
    DataStatus.COMPUTED_FROM_OBSERVED: 4,
    DataStatus.INFERRED: 3,
    DataStatus.PRIOR_DEFAULT: 2,
    DataStatus.MANUAL_ANNOTATION: 1,
    DataStatus.SYNTHETIC_DEMO: 0,
}
_GATE1_NON_FORMAL_DATA_STATUSES = {
    DataStatus.PRIOR_DEFAULT,
    DataStatus.SYNTHETIC_DEMO,
    DataStatus.MANUAL_ANNOTATION,
}
_GATE1_SOURCE_TO_DATA_STATUS = {
    "user_provided": DataStatus.OBSERVED,
    "system_inferred": DataStatus.INFERRED,
    "default_assumed": DataStatus.PRIOR_DEFAULT,
    "externally_fetched": DataStatus.OBSERVED,
}
_GATE1_DOMAIN_FIELD_PREFIXES = {
    "market_raw": ("market", "market."),
    "account_raw": ("account", "account.", "holdings"),
    "behavior_raw": ("behavior", "behavior."),
    "live_portfolio": ("live_portfolio", "account", "account.", "holdings"),
}
_HIGH_RISK_ACTION_TYPES = {
    "rebalance_full",
    "sell_all",
    "switch_all",
    "all_in_equity",
    "all_in_satellite",
    "chase_hot_theme",
    "add_cash_sat",
    "reduce_defense",
}


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    data = _obj(value)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(getattr(value, "value", value)).strip()
    return normalized or None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = _text(value)
    if text is None:
        return False
    normalized = text.lower()
    if normalized in {"0", "false", "no", "n", "off", "none", ""}:
        return False
    if normalized in {"1", "true", "yes", "y", "on", "required", "active"}:
        return True
    return bool(normalized)


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text is not None:
            return text
    return None


def _utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_text(value: Any) -> str | None:
    moment = _utc_datetime(value)
    if moment is not None:
        return moment.date().isoformat()
    text = _text(value)
    if text is None:
        return None
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _payload(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _normalized_weights(values: dict[str, Any] | None) -> dict[str, float]:
    normalized = {
        str(key): max(float(item), 0.0)
        for key, item in dict(values or {}).items()
        if _text(key) is not None
    }
    total = sum(normalized.values())
    if total <= 0.0:
        return {}
    return {key: value / total for key, value in normalized.items()}


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def _add_calendar_months(anchor: date, months: int) -> date:
    total_month = (anchor.month - 1) + months
    year = anchor.year + total_month // 12
    month = total_month % 12 + 1
    day = min(anchor.day, _days_in_month(year, month))
    return date(year, month, day)


def _future_business_days_until(as_of: str, end_date: date) -> list[str]:
    anchor = date.fromisoformat(as_of)
    days: list[str] = []
    current = anchor
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days.append(current.isoformat())
    return days


def _series_variance(series: list[Any]) -> float:
    values = [float(item) for item in series]
    if not values:
        return 1e-4
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(len(values), 1)
    return max(variance, 1e-6)


def _negative_loss_profile(series: list[Any]) -> tuple[float, float]:
    negatives = [abs(float(value)) for value in series if float(value) < 0.0]
    if not negatives:
        return (0.015, 0.0075)
    mean_loss = sum(negatives) / len(negatives)
    variance = sum((value - mean_loss) ** 2 for value in negatives) / max(len(negatives), 1)
    return (max(mean_loss, 0.005), max(variance**0.5, 0.0025))


def _asset_bucket_factor_betas(asset_bucket: str, factor_names: list[str]) -> dict[str, float]:
    betas = {name: 0.0 for name in factor_names}

    def _assign(pattern: str, value: float) -> bool:
        for factor_name in factor_names:
            if pattern in factor_name.lower():
                betas[factor_name] = value
                return True
        return False

    bucket = str(asset_bucket or "").strip().lower()
    if bucket in {"equity_cn", "satellite"}:
        _assign("cn_eq_broad", 0.84 if bucket == "equity_cn" else 0.92)
        _assign("cn_eq_growth", 0.03 if bucket == "equity_cn" else 0.05)
        _assign("cn_eq_value", 0.02)
        _assign("gold", 0.02 if bucket == "equity_cn" else 0.01)
        _assign("usd", 0.01)
    elif bucket == "bond_cn":
        _assign("cn_rate_duration", 0.73)
        _assign("cn_credit_spread", 0.17)
        _assign("gold", 0.04)
        _assign("usd", 0.03)
        _assign("cn_eq_broad", 0.01)
    elif bucket == "gold":
        _assign("gold", 0.95)
        _assign("usd", 0.05)
    elif bucket in {"cash", "cash_liquidity"}:
        _assign("cn_rate_duration", 0.10)
    else:
        _assign("cn_eq_broad", 0.50)
    return betas


def _build_probability_engine_run_input(
    *,
    run_id: str,
    envelope: dict[str, Any],
    calibration_result: Any,
    goal_solver_input: Any,
    goal_solver_output: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    goal_input = _as_dict(goal_solver_input)
    solver_output = _as_dict(goal_solver_output)
    recommended_result = _as_dict(solver_output.get("recommended_result"))
    recommended_name = _first_text(
        solver_output.get("recommended_allocation_name"),
        recommended_result.get("allocation_name"),
    )
    candidate_contexts = _as_dict(goal_input.get("candidate_product_contexts"))
    recommended_context = _as_dict(candidate_contexts.get(recommended_name)) if recommended_name else {}
    simulation_input = _as_dict(recommended_context.get("product_simulation_input"))
    simulation_products = [
        _as_dict(item) for item in list(simulation_input.get("products") or []) if _as_dict(item)
    ]
    calibration_data = _as_dict(calibration_result)
    factor_dynamics = _payload(calibration_data.get("factor_dynamics"))
    regime_state = _payload(calibration_data.get("regime_state"))
    jump_state = _payload(calibration_data.get("jump_state"))
    factor_names = [str(item) for item in list(_as_dict(factor_dynamics).get("factor_names") or []) if _text(item)]
    if not simulation_products or factor_dynamics is None or regime_state is None or jump_state is None or not factor_names:
        return None, {}

    observed_series = []
    observed_lengths: set[int] = set()
    for item in simulation_products:
        series = [float(value) for value in list(item.get("return_series") or [])]
        if not series:
            return None, {}
        observed_series.append((str(item.get("product_id") or "").strip(), series))
        observed_lengths.add(len(series))
    if len(observed_lengths) != 1:
        return None, {}
    observed_length = observed_lengths.pop()
    portfolio_returns = [
        sum(series[index] for _, series in observed_series) / float(len(observed_series))
        for index in range(observed_length)
    ]
    if portfolio_returns:
        lower_threshold = float(np.quantile(portfolio_returns, 0.33))
        upper_threshold = float(np.quantile(portfolio_returns, 0.67))
    else:
        lower_threshold = 0.0
        upper_threshold = 0.0
    observed_regime_labels = [
        "stress"
        if value <= lower_threshold
        else "risk_off"
        if value <= upper_threshold
        else "normal"
        for value in portfolio_returns
    ]
    observed_current_regime = (
        observed_regime_labels[max(0, len(observed_regime_labels) - 2)]
        if observed_regime_labels
        else "normal"
    )

    as_of = (
        _date_text(envelope.get("as_of"))
        or _date_text(_as_dict(_as_dict(envelope.get("market_raw")).get("historical_dataset")).get("as_of"))
        or date.today().isoformat()
    )

    goal = _as_dict(goal_input.get("goal"))
    constraints = _as_dict(goal_input.get("constraints"))
    cashflow_plan = _as_dict(goal_input.get("cashflow_plan"))
    horizon_months = int(goal.get("horizon_months") or 1)
    horizon_months = max(horizon_months, 1)
    end_date = _add_calendar_months(date.fromisoformat(as_of), horizon_months)
    trading_calendar = _future_business_days_until(as_of, end_date)
    path_horizon_days = len(trading_calendar)
    if path_horizon_days <= 0:
        return None, {}
    live_portfolio = _as_dict(envelope.get("live_portfolio"))
    account_raw = _as_dict(envelope.get("account_raw"))
    total_value = float(
        live_portfolio.get("total_value")
        or account_raw.get("total_value")
        or goal_input.get("current_portfolio_value")
        or 0.0
    )
    if total_value <= 0.0:
        return None, {}

    target_weights = _normalized_weights(
        {str(item.get("product_id") or ""): float(item.get("target_weight") or 0.0) for item in simulation_products}
    )
    if not target_weights:
        equal_weight = 1.0 / float(len(simulation_products))
        target_weights = {
            str(item.get("product_id") or f"product_{index}"): equal_weight
            for index, item in enumerate(simulation_products)
            if _text(item.get("product_id")) is not None
        }
    if not target_weights:
        return None, {}

    factor_mapping_products = _extract_probability_engine_factor_mapping_context(envelope)
    products: list[dict[str, Any]] = []
    current_positions: list[dict[str, Any]] = []
    jump_data = _as_dict(jump_state)
    jump_profiles = {
        str(key): _as_dict(value)
        for key, value in _as_dict(jump_data.get("idio_jump_profile_by_product")).items()
    }
    for item in simulation_products:
        product_id = _text(item.get("product_id"))
        if product_id is None:
            continue
        series = [float(value) for value in list(item.get("return_series") or [])]
        observation_dates = [
            str(value).strip()
            for value in list(item.get("observation_dates") or [])
            if str(value).strip()
        ]
        loss_mean, loss_std = _negative_loss_profile(series)
        variance = _series_variance(series)
        jump_profile = jump_profiles.get(product_id) or {
            "probability_1d": 0.012,
            "loss_mean": -loss_mean,
            "loss_std": loss_std,
        }
        mapping_payload = _as_dict(factor_mapping_products.get(product_id))
        factor_betas_payload = _as_dict(
            mapping_payload.get("factor_betas")
            or item.get("factor_betas")
            or {}
        )
        factor_betas = {
            factor_name: float(factor_betas_payload.get(factor_name, 0.0))
            for factor_name in factor_names
        }
        if not any(abs(value) > 0.0 for value in factor_betas.values()):
            factor_betas = _asset_bucket_factor_betas(_text(item.get("asset_bucket")) or "", factor_names)
        mapping_confidence = _first_text(
            mapping_payload.get("mapping_confidence"),
            item.get("mapping_confidence"),
        ) or "medium"
        factor_mapping_source = _first_text(
            mapping_payload.get("factor_mapping_source"),
            item.get("factor_mapping_source"),
        ) or "product_level_evidence"
        factor_mapping_evidence = deepcopy(
            list(mapping_payload.get("factor_mapping_evidence") or item.get("factor_mapping_evidence") or [])
        )
        if not factor_mapping_evidence:
            factor_mapping_evidence = [
                {
                    "source": "product_level_evidence",
                    "observed_points": int(item.get("observed_points") or len(series)),
                    "sample_count": len(series),
                }
            ]
        products.append(
            {
                "product_id": product_id,
                "asset_bucket": _text(item.get("asset_bucket")) or "",
                "factor_betas": factor_betas,
                "innovation_family": "student_t",
                "tail_df": float(_as_dict(factor_dynamics).get("tail_df") or 7.0),
                "volatility_process": "product_garch_11",
                "garch_params": {
                    "omega": variance * 0.03,
                    "alpha": 0.07,
                    "beta": 0.90,
                    "nu": float(_as_dict(factor_dynamics).get("tail_df") or 7.0),
                    "long_run_variance": variance,
                },
                "idiosyncratic_jump_profile": jump_profile,
                "carry_profile": {"carry_drag": -0.00001},
                "valuation_profile": {"valuation_drag": -0.000005},
                "mapping_confidence": mapping_confidence,
                "factor_mapping_source": factor_mapping_source,
                "factor_mapping_evidence": factor_mapping_evidence,
                "observed_series_ref": _text(item.get("source_ref")) or f"observed://product_simulation/{product_id}",
                "observed_daily_returns": series,
                "observed_return_series": series,
                "observed_dates": observation_dates,
            }
        )
        weight = float(target_weights.get(product_id, 0.0))
        market_value = total_value * weight
        current_positions.append(
            {
                "product_id": product_id,
                "units": market_value,
                "market_value": market_value,
                "weight": weight,
                "cost_basis": market_value,
                "tradable": True,
            }
        )

    if not products or not current_positions:
        return None, {}

    monthly_contribution = float(cashflow_plan.get("monthly_contribution") or 0.0)
    contribution_schedule: list[dict[str, Any]] = []
    if monthly_contribution > 0.0:
        for month_index in range(1, horizon_months + 1):
            contribution_date = _add_calendar_months(date.fromisoformat(as_of), month_index)
            target_date = next(
                (item for item in trading_calendar if item >= contribution_date.isoformat()),
                trading_calendar[-1],
            )
            contribution_schedule.append(
                {
                    "date": target_date,
                    "amount": monthly_contribution,
                    "allocation_mode": "target_weights",
                    "target_weights": dict(target_weights),
                }
            )

    target_value = float(goal.get("goal_amount") or recommended_result.get("target_value") or total_value)
    probability_input = {
        "as_of": as_of,
        "path_horizon_days": path_horizon_days,
        "trading_calendar": trading_calendar,
        "products": products,
        "factor_dynamics": factor_dynamics,
        "regime_state": regime_state,
        "jump_state": jump_state,
        "current_positions": current_positions,
        "contribution_schedule": contribution_schedule,
        "withdrawal_schedule": [],
        "rebalancing_policy": {
            "policy_type": "hybrid",
            "calendar_frequency": "daily",
            "threshold_band": 0.04,
            "execution_timing": "end_of_day_after_return",
            "transaction_cost_bps": 5.0,
            "min_trade_amount": 250.0,
        },
        "success_event_spec": {
            "horizon_days": path_horizon_days,
            "horizon_months": horizon_months,
            "target_type": "goal_amount",
            "target_value": target_value,
            "drawdown_constraint": float(constraints.get("max_drawdown_tolerance") or 0.20),
            "benchmark_ref": None,
            "contribution_policy": "scheduled_fixed" if monthly_contribution > 0.0 else "none",
            "withdrawal_policy": "none",
            "rebalancing_policy_ref": "policy://orchestrator/hybrid_daily",
            "return_basis": "nominal",
            "fee_basis": "net",
            "success_logic": "joint_target_and_drawdown",
        },
        "recipes": [
            {
                "recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1",
            }
        ],
        "observed_regime_labels": observed_regime_labels,
        "observed_current_regime": observed_current_regime,
        "challenger_block_size": 2,
        "challenger_path_count": 32,
        "stress_path_count": 16,
        "evidence_bundle_ref": f"evidence://probability_engine/{run_id}",
        "random_seed": int(_as_dict(goal_input.get("solver_params")).get("seed") or 17),
    }
    return probability_input, {
        "daily_product_path_available": True,
        "monthly_fallback_used": False,
        "bucket_fallback_used": False,
    }


def _mapped_probability_result_category(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if normalized == "formal_strict_result":
        return "formal_independent_result"
    if normalized in {"formal_estimated_result", "degraded_formal_result"}:
        return normalized
    return None


def _probability_truth_product_method(
    *,
    resolved_result_category: str | None,
    probability_engine_result: Any,
    evidence_bundle: dict[str, Any] | None = None,
) -> str:
    probability_payload = _as_dict(probability_engine_result)
    internal_category = _text(probability_payload.get("resolved_result_category"))
    if probability_payload:
        if internal_category == "formal_strict_result":
            return "product_independent_path"
        if internal_category in {"formal_estimated_result", "degraded_formal_result"}:
            return "product_estimated_path"
        return ""
    if internal_category:
        if internal_category == "formal_strict_result":
            return "product_independent_path"
        if internal_category in {"formal_estimated_result", "degraded_formal_result"}:
            return "product_estimated_path"
        return ""
    coverage_summary = _as_dict(_as_dict(evidence_bundle).get("coverage_summary"))
    if (
        not _bool(_as_dict(evidence_bundle).get("monthly_fallback_used"))
        and not _bool(_as_dict(evidence_bundle).get("bucket_fallback_used"))
        and float(coverage_summary.get("independent_weight_adjusted_coverage") or 0.0) >= 0.999
        and float(coverage_summary.get("independent_horizon_complete_coverage") or 0.0) >= 0.999
        and float(coverage_summary.get("distribution_ready_coverage") or 0.0) >= 0.999
        and int(coverage_summary.get("selected_product_count") or 0) > 0
    ):
        return "product_independent_path"
    mapped_category = _text(resolved_result_category)
    if mapped_category == "formal_independent_result":
        return "product_independent_path"
    if mapped_category in {"formal_estimated_result", "degraded_formal_result"}:
        return "product_estimated_path"
    return ""


def _probability_truth_view(
    *,
    probability_engine_result: Any,
    run_outcome_status: str | None,
    resolved_result_category: str | None,
    disclosure_decision: dict[str, Any],
    evidence_bundle: dict[str, Any],
) -> dict[str, Any]:
    product_probability_method = _probability_truth_product_method(
        resolved_result_category=resolved_result_category,
        probability_engine_result=probability_engine_result,
        evidence_bundle=evidence_bundle,
    )
    formal_path_visibility = {
        "status": _text(run_outcome_status) or "",
        "fallback_used": _bool(_as_dict(evidence_bundle).get("monthly_fallback_used"))
        or _bool(_as_dict(evidence_bundle).get("bucket_fallback_used")),
        "monthly_fallback_used": _bool(_as_dict(evidence_bundle).get("monthly_fallback_used")),
        "bucket_fallback_used": _bool(_as_dict(evidence_bundle).get("bucket_fallback_used")),
    }
    return {
        "run_outcome_status": _text(run_outcome_status) or "",
        "resolved_result_category": _text(resolved_result_category),
        "product_probability_method": product_probability_method,
        "disclosure_decision": dict(disclosure_decision or {}),
        "formal_path_visibility": formal_path_visibility,
        "evidence_bundle": dict(evidence_bundle or {}),
    }


def _bridged_probability_surface(
    *,
    probability_engine_result: Any,
    run_outcome_status: str,
    resolved_result_category: str | None,
    disclosure_decision: dict[str, Any],
    evidence_bundle: dict[str, Any],
) -> dict[str, Any]:
    probability_payload = _as_dict(probability_engine_result)
    if not probability_payload:
        return {}
    probability_status = str(probability_payload.get("run_outcome_status") or "").strip().lower()
    if probability_status == "failure":
        bridged_disclosure = dict(disclosure_decision or {})
        bridged_disclosure["result_category"] = None
        bridged_disclosure["disclosure_level"] = "unavailable"
        bridged_disclosure["point_value_allowed"] = False
        bridged_disclosure["range_required"] = False
        bridged_disclosure["diagnostic_only"] = False
        bridged_disclosure["precision_cap"] = "unavailable"
        bridged_disclosure["confidence_level"] = "low"

        bridged_evidence = dict(evidence_bundle or {})
        bridged_evidence["run_outcome_status"] = RunOutcomeStatus.UNAVAILABLE.value
        bridged_evidence["resolved_result_category"] = None
        bridged_evidence["formal_path_status"] = RunOutcomeStatus.UNAVAILABLE.value
        bridged_evidence["monthly_fallback_used"] = False
        bridged_evidence["bucket_fallback_used"] = False
        bridged_evidence["disclosure_decision"] = dict(bridged_disclosure)
        bridged_evidence["failure_artifact"] = _as_dict(probability_payload.get("failure_artifact"))

        return {
            "run_outcome_status": RunOutcomeStatus.UNAVAILABLE.value,
            "resolved_result_category": None,
            "disclosure_decision": bridged_disclosure,
            "evidence_bundle": bridged_evidence,
        }
    mapped_category = _mapped_probability_result_category(probability_payload.get("resolved_result_category"))
    if mapped_category is None or probability_status not in {"success", "degraded"}:
        return {}
    top_level_status = "completed" if probability_status == "success" else "degraded"

    output_payload = _as_dict(probability_payload.get("output"))
    disclosure_payload = _as_dict(output_payload.get("probability_disclosure_payload"))
    bridged_disclosure = dict(disclosure_decision or {})
    bridged_evidence = dict(evidence_bundle or {})
    bridged_disclosure["result_category"] = mapped_category
    if disclosure_payload.get("disclosure_level") is not None:
        bridged_disclosure["disclosure_level"] = disclosure_payload.get("disclosure_level")
        bridged_disclosure["point_value_allowed"] = disclosure_payload.get("disclosure_level") == "point_and_range"
        bridged_disclosure["range_required"] = disclosure_payload.get("disclosure_level") in {
            "point_and_range",
            "range_only",
        }
        bridged_disclosure["diagnostic_only"] = disclosure_payload.get("disclosure_level") == "diagnostic_only"
        bridged_disclosure["precision_cap"] = disclosure_payload.get("disclosure_level")
    if disclosure_payload.get("confidence_level") is not None:
        bridged_disclosure["confidence_level"] = disclosure_payload.get("confidence_level")
    if mapped_category == "degraded_formal_result":
        bridged_disclosure["confidence_level"] = "low"

    bridged_evidence["run_outcome_status"] = top_level_status
    bridged_evidence["resolved_result_category"] = mapped_category
    bridged_evidence["formal_path_status"] = top_level_status
    bridged_evidence["monthly_fallback_used"] = False
    bridged_evidence["bucket_fallback_used"] = False
    bridged_evidence["disclosure_decision"] = dict(bridged_disclosure)

    return {
        "run_outcome_status": top_level_status,
        "resolved_result_category": mapped_category,
        "disclosure_decision": bridged_disclosure,
        "evidence_bundle": bridged_evidence,
    }


def _probability_runtime_telemetry(probability_engine_input: Any, probability_engine_result: Any) -> dict[str, Any]:
    input_payload = _as_dict(probability_engine_input)
    result_payload = _as_dict(probability_engine_result)
    output_payload = _as_dict(result_payload.get("output"))
    primary_result = _as_dict(output_payload.get("primary_result"))
    primary_path_stats = _as_dict(primary_result.get("path_stats"))
    challenger_results = [_as_dict(item) for item in list(output_payload.get("challenger_results") or [])]
    stress_results = [_as_dict(item) for item in list(output_payload.get("stress_results") or [])]

    def _path_count(result: dict[str, Any]) -> int:
        return int(_as_dict(result.get("path_stats")).get("path_count") or 0)

    return {
        "path_horizon_days": int(input_payload.get("path_horizon_days") or 0) or None,
        "path_count_primary": int(primary_path_stats.get("path_count") or 0) or None,
        "path_count_challenger": sum(_path_count(item) for item in challenger_results),
        "path_count_stress": sum(_path_count(item) for item in stress_results),
    }


def _has_any_raw_snapshot_inputs(envelope: dict[str, Any]) -> bool:
    return any(
        key in envelope
        and not (key == "market_raw" and bool(envelope.get("_auto_market_raw_injected")))
        for key in (
            "market_raw",
            "account_raw",
            "goal_raw",
            "constraint_raw",
            "behavior_raw",
            "as_of",
            "snapshot_as_of",
        )
    )


def _snapshot_primary_formal_path(envelope: dict[str, Any]) -> bool:
    return _bool(envelope.get("snapshot_primary_formal_path"))


def _snapshot_build_context(
    envelope: dict[str, Any],
    prior_solver_input: Any | None,
) -> tuple[dict[str, Any], list[str]]:
    baseline_input = _as_dict(envelope.get("goal_solver_input") or prior_solver_input)
    allocation_input = _as_dict(envelope.get("allocation_engine_input"))
    allocation_profile = _as_dict(allocation_input.get("account_profile"))
    live_portfolio = _as_dict(envelope.get("live_portfolio"))

    account_profile_id = _first_text(
        envelope.get("account_profile_id"),
        baseline_input.get("account_profile_id"),
        allocation_profile.get("account_profile_id"),
    )
    as_of = _utc_datetime(envelope.get("as_of")) or _utc_datetime(envelope.get("snapshot_as_of"))
    market_raw = _as_dict(envelope.get("market_raw"))
    account_raw = _as_dict(envelope.get("account_raw")) or live_portfolio
    goal_raw = _as_dict(envelope.get("goal_raw")) or _as_dict(baseline_input.get("goal"))
    constraint_raw = _as_dict(envelope.get("constraint_raw")) or _as_dict(baseline_input.get("constraints"))
    behavior_raw = envelope.get("behavior_raw")
    remaining_horizon_months = envelope.get("remaining_horizon_months")
    if remaining_horizon_months is None:
        remaining_horizon_months = (
            _as_dict(goal_raw).get("horizon_months")
            or _as_dict(account_raw).get("remaining_horizon_months")
            or _as_dict(baseline_input.get("goal")).get("horizon_months")
        )

    missing: list[str] = []
    if account_profile_id is None:
        missing.append("account_profile_id")
    if as_of is None:
        missing.append("as_of")
    if not market_raw:
        missing.append("market_raw")
    if not account_raw:
        missing.append("account_raw")
    if not goal_raw:
        missing.append("goal_raw")
    if not constraint_raw:
        missing.append("constraint_raw")
    if remaining_horizon_months is None:
        missing.append("remaining_horizon_months")

    return (
        {
            "account_profile_id": account_profile_id,
            "as_of": as_of,
            "market_raw": market_raw,
            "account_raw": account_raw,
            "goal_raw": goal_raw,
            "constraint_raw": constraint_raw,
            "behavior_raw": None if behavior_raw is None else _as_dict(behavior_raw),
            "policy_news_signals": list(
                envelope.get("policy_news_signals")
                or _as_dict(market_raw).get("policy_news_signals")
                or []
            ),
            "remaining_horizon_months": remaining_horizon_months,
            "schema_version": _first_text(envelope.get("snapshot_schema_version"), "v1.0"),
        },
        missing,
    )


def _resolve_snapshot_bundle(
    envelope: dict[str, Any],
    prior_solver_input: Any | None,
    blocking_reasons: list[str],
) -> tuple[Any | None, str]:
    provided_snapshot_bundle = envelope.get("snapshot_bundle")
    if provided_snapshot_bundle is not None:
        return provided_snapshot_bundle, "provided"
    if not _has_any_raw_snapshot_inputs(envelope):
        return None, "absent"

    context, missing = _snapshot_build_context(envelope, prior_solver_input)
    if missing:
        blocking_reasons.append(
            "raw snapshot inputs incomplete: " + ", ".join(missing)
        )
        return None, "incomplete"

    return (
        build_snapshot_bundle(
            account_profile_id=str(context["account_profile_id"]),
            as_of=context["as_of"],
            market_raw=context["market_raw"],
            account_raw=context["account_raw"],
            goal_raw=context["goal_raw"],
            constraint_raw=context["constraint_raw"],
            behavior_raw=context["behavior_raw"],
            remaining_horizon_months=int(context["remaining_horizon_months"]),
            policy_news_signals=context["policy_news_signals"],
            schema_version=str(context["schema_version"]),
        ),
        "generated",
    )


def _snapshot_bundle_has_required_domains(snapshot_bundle: Any) -> bool:
    data = _as_dict(snapshot_bundle)
    return all(data.get(field) not in (None, {}) for field in ("market", "account", "goal", "constraint"))


def _calibration_manual_override_requested(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
) -> bool:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    request_context = _as_dict(envelope.get("user_request_context"))
    return any(
        _bool(value)
        for value in (
            control_flags.get("manual_override_requested"),
            control_flags.get("override_requested"),
            review_context.get("manual_override_requested"),
            request_context.get("manual_override_requested"),
            trigger.manual_override_requested,
            envelope.get("manual_override_requested"),
            envelope.get("override_requested"),
        )
    )


def _calibration_replay_mode(envelope: dict[str, Any]) -> bool:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    return any(
        _bool(value)
        for value in (
            control_flags.get("replay_mode"),
            control_flags.get("replay_requested"),
            review_context.get("replay_mode"),
            envelope.get("replay_mode"),
            envelope.get("replay_requested"),
        )
    )


def _calibration_updated_reason(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
    *,
    manual_override: bool,
    replay_mode: bool,
) -> str | None:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    explicit = _first_text(
        control_flags.get("updated_reason"),
        review_context.get("updated_reason"),
        envelope.get("updated_reason"),
    )
    if explicit is not None:
        return explicit
    if manual_override or replay_mode:
        return None
    if trigger.workflow_type == WorkflowType.ONBOARDING:
        return "onboarding_calibration"
    if trigger.workflow_type == WorkflowType.QUARTERLY:
        return "quarterly_calibration"
    if trigger.workflow_type == WorkflowType.EVENT:
        return "event_calibration"
    return "monthly_calibration"


def _resolve_calibration_result(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
    snapshot_bundle: Any | None,
    snapshot_bundle_origin: str,
    prior_calibration: Any | None,
    prior_solver_input: Any | None,
) -> tuple[Any | None, str]:
    provided_calibration = envelope.get("calibration_result")
    if provided_calibration is not None:
        return provided_calibration, "provided"
    if snapshot_bundle is None:
        if prior_calibration is None:
            return None, "absent"
        return prior_calibration, "prior"
    if snapshot_bundle_origin != "generated" and not _snapshot_bundle_has_required_domains(snapshot_bundle):
        if prior_calibration is None:
            return None, "absent"
        return prior_calibration, "prior"

    baseline_input = _as_dict(envelope.get("goal_solver_input") or prior_solver_input)
    manual_override = _calibration_manual_override_requested(envelope, trigger)
    replay_mode = _calibration_replay_mode(envelope)
    updated_reason = _calibration_updated_reason(
        envelope,
        trigger,
        manual_override=manual_override,
        replay_mode=replay_mode,
    )
    return (
        run_calibration(
            snapshot_bundle,
            prior_calibration=prior_calibration,
            default_goal_solver_params=baseline_input.get("solver_params"),
            default_runtime_params=envelope.get("default_runtime_optimizer_params"),
            default_ev_params=envelope.get("default_ev_params"),
            updated_reason=updated_reason,
            manual_override=manual_override,
            replay_mode=replay_mode,
        ),
        "generated",
    )


def _requested_workflow_from_any(value: TriggerSignal | dict[str, Any]) -> WorkflowType | None:
    if isinstance(value, TriggerSignal):
        return value.workflow_type
    data = _as_dict(value)
    if "workflow_type" not in data:
        return None
    raw = data.get("workflow_type")
    if raw in {None, "", "auto"}:
        return None
    return WorkflowType(str(getattr(raw, "value", raw)))


def _requested_action_from_inputs(envelope: dict[str, Any]) -> str | None:
    request_context = _as_dict(envelope.get("user_request_context"))
    control_flags = _as_dict(envelope.get("control_flags"))
    return _first_text(
        request_context.get("requested_action"),
        request_context.get("action_type"),
        request_context.get("request_type"),
        control_flags.get("requested_action"),
        control_flags.get("action_type"),
        envelope.get("requested_action"),
    )


def _is_high_risk_request(envelope: dict[str, Any]) -> bool:
    request_context = _as_dict(envelope.get("user_request_context"))
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    explicit_flag = any(
        _bool(value)
        for value in (
            request_context.get("high_risk_request"),
            request_context.get("high_risk_action_request"),
            request_context.get("high_heat_narrative_request"),
            request_context.get("hot_theme_request"),
            control_flags.get("high_risk_request"),
            control_flags.get("high_risk_action_request"),
            control_flags.get("high_heat_narrative_request"),
            review_context.get("high_risk_request"),
            envelope.get("high_risk_request"),
            envelope.get("high_risk_action_request"),
        )
    )
    if explicit_flag:
        return True

    risk_level = _first_text(
        request_context.get("risk_level"),
        request_context.get("requested_action_risk_level"),
        control_flags.get("risk_level"),
        envelope.get("risk_level"),
    )
    if risk_level is not None and risk_level.lower() in {"high", "elevated"}:
        return True

    requested_action = _requested_action_from_inputs(envelope)
    return requested_action is not None and requested_action.lower() in _HIGH_RISK_ACTION_TYPES


def _extract_control_flags(
    envelope: dict[str, Any],
    calibration_data: dict[str, Any],
    trigger: TriggerSignal,
) -> dict[str, Any]:
    behavior_state = _as_dict(calibration_data.get("behavior_state"))
    constraint_state = _as_dict(calibration_data.get("constraint_state"))
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    request_context = _as_dict(envelope.get("user_request_context"))

    manual_review_requested = any(
        _bool(value)
        for value in (
            control_flags.get("manual_review_requested"),
            control_flags.get("require_manual_review"),
            review_context.get("manual_review_requested"),
            review_context.get("require_manual_review"),
            request_context.get("manual_review_requested"),
            trigger.manual_review_requested,
            envelope.get("manual_review_requested"),
            envelope.get("require_manual_review"),
        )
    )
    manual_override_requested = any(
        _bool(value)
        for value in (
            control_flags.get("manual_override_requested"),
            control_flags.get("override_requested"),
            review_context.get("manual_override_requested"),
            request_context.get("manual_override_requested"),
            trigger.manual_override_requested,
            envelope.get("manual_override_requested"),
            envelope.get("override_requested"),
        )
    )
    quarterly_review_requested = any(
        _bool(value)
        for value in (
            control_flags.get("quarterly_review"),
            control_flags.get("quarterly_review_requested"),
            review_context.get("quarterly_review"),
            review_context.get("quarterly_review_requested"),
            envelope.get("quarterly_review"),
            envelope.get("quarterly_review_requested"),
        )
    )
    force_full_recalc = any(
        _bool(value)
        for value in (
            control_flags.get("force_full_recalc"),
            control_flags.get("force_recompute_baseline"),
            review_context.get("force_full_recalc"),
            review_context.get("force_recompute_baseline"),
            trigger.force_full_review,
            envelope.get("force_full_recalc"),
            envelope.get("force_recompute_baseline"),
        )
    )
    major_parameter_update = any(
        _bool(value)
        for value in (
            control_flags.get("major_parameter_update"),
            review_context.get("major_parameter_update"),
            envelope.get("major_parameter_update"),
        )
    )
    high_risk_request = trigger.high_risk_request or _is_high_risk_request(envelope)
    requested_action = _requested_action_from_inputs(envelope)
    cooldown_active = any(
        _bool(value)
        for value in (
            behavior_state.get("cooldown_active"),
            constraint_state.get("cooldown_currently_active"),
        )
    )

    return {
        "manual_review_requested": manual_review_requested,
        "manual_override_requested": manual_override_requested,
        "quarterly_review_requested": quarterly_review_requested,
        "force_full_recalc": force_full_recalc,
        "major_parameter_update": major_parameter_update,
        "high_risk_request": high_risk_request,
        "requested_action": requested_action,
        "cooldown_active": cooldown_active,
        "override_count_90d": int(behavior_state.get("override_count_90d", 0) or 0),
        "cooldown_until": behavior_state.get("cooldown_until"),
        "audit_mode": any(
            _bool(value)
            for value in (
                control_flags.get("audit_mode"),
                envelope.get("audit_mode"),
            )
        ),
        "enforce_provenance_checks": not any(
            _bool(value)
            for value in (
                control_flags.get("disable_provenance_checks"),
                review_context.get("disable_provenance_checks"),
                envelope.get("disable_provenance_checks"),
            )
        ),
        "allow_degraded_continue": any(
            _bool(value)
            for value in (
                control_flags.get("allow_degraded_continue"),
                envelope.get("allow_degraded_continue"),
            )
        ),
    }


def _select_workflow(
    requested_workflow: WorkflowType | None,
    trigger: TriggerSignal,
    envelope: dict[str, Any],
    prior_solver_output: Any | None,
    prior_solver_input: Any | None,
    control_flags: dict[str, Any],
) -> WorkflowDecision:
    has_prior_baseline = prior_solver_output is not None and prior_solver_input is not None
    has_rebuild_inputs = (
        _has_any_raw_snapshot_inputs(envelope)
        or (
            envelope.get("allocation_engine_input") is not None
            and envelope.get("goal_solver_input") is not None
        )
    )
    has_event_signal = any(
        (
            trigger.structural_event,
            trigger.behavior_event,
            trigger.drawdown_event,
            trigger.satellite_event,
            control_flags["manual_review_requested"],
            control_flags["manual_override_requested"],
            control_flags["high_risk_request"],
        )
    )
    quarterly_signal = any(
        (
            control_flags["quarterly_review_requested"],
            control_flags["force_full_recalc"],
            control_flags["major_parameter_update"],
        )
    )

    if has_event_signal and has_prior_baseline:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.EVENT,
            selection_reason="event_signal_detected",
            auto_selected=requested_workflow != WorkflowType.EVENT,
        )
    if requested_workflow == WorkflowType.QUARTERLY or quarterly_signal:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.QUARTERLY,
            selection_reason="quarterly_review_requested",
            auto_selected=requested_workflow != WorkflowType.QUARTERLY,
        )
    if not has_prior_baseline and (has_rebuild_inputs or requested_workflow == WorkflowType.ONBOARDING):
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.ONBOARDING,
            selection_reason="missing_prior_baseline",
            auto_selected=requested_workflow != WorkflowType.ONBOARDING,
        )
    if requested_workflow == WorkflowType.EVENT:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.EVENT,
            selection_reason="explicit_event_request",
            auto_selected=False,
        )
    if requested_workflow == WorkflowType.ONBOARDING:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.ONBOARDING,
            selection_reason="explicit_onboarding_request",
            auto_selected=False,
        )
    if requested_workflow == WorkflowType.MONTHLY:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.MONTHLY,
            selection_reason="explicit_monthly_request",
            auto_selected=False,
        )
    if has_prior_baseline:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.MONTHLY,
            selection_reason="default_monthly_with_prior_baseline",
            auto_selected=True,
        )
    return WorkflowDecision(
        requested_workflow_type=requested_workflow,
        selected_workflow_type=WorkflowType.ONBOARDING,
        selection_reason="default_onboarding_without_prior_baseline",
        auto_selected=True,
    )


def _trigger_from_any(value: TriggerSignal | dict[str, Any]) -> TriggerSignal:
    if isinstance(value, TriggerSignal):
        return value
    data = dict(_obj(value))
    workflow_type_raw = data.get("workflow_type", WorkflowType.MONTHLY.value)
    if workflow_type_raw in {None, "", "auto"}:
        workflow_type = WorkflowType.MONTHLY
    else:
        workflow_type = WorkflowType(str(getattr(workflow_type_raw, "value", workflow_type_raw)))
    return TriggerSignal(
        workflow_type=workflow_type,
        run_id=str(data.get("run_id", "")),
        structural_event=bool(data.get("structural_event", False)),
        behavior_event=bool(data.get("behavior_event", False)),
        drawdown_event=bool(data.get("drawdown_event", False)),
        satellite_event=bool(data.get("satellite_event", False)),
        manual_review_requested=bool(data.get("manual_review_requested", False)),
        manual_override_requested=bool(data.get("manual_override_requested", False)),
        high_risk_request=bool(data.get("high_risk_request", False)),
        force_full_review=bool(data.get("force_full_review", False)),
    )


def _build_run_id(run_id: str, workflow_type: WorkflowType) -> str:
    if run_id:
        return run_id
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"{workflow_type.value}_{timestamp}"


def _card_type_for_workflow(
    workflow_type: WorkflowType,
    blocked: bool,
) -> DecisionCardType:
    if blocked:
        return DecisionCardType.BLOCKED
    if workflow_type == WorkflowType.ONBOARDING:
        return DecisionCardType.GOAL_BASELINE
    if workflow_type == WorkflowType.QUARTERLY:
        return DecisionCardType.QUARTERLY_REVIEW
    return DecisionCardType.RUNTIME_ACTION


def _build_input_provenance(
    envelope: dict[str, Any],
    workflow_type: WorkflowType,
    *,
    has_prior_baseline: bool,
) -> dict[str, Any]:
    explicit = envelope.get("input_provenance")
    if explicit is not None:
        data = _as_dict(explicit)
        if isinstance(data.get("items"), list):
            normalized = {
                "items": list(data.get("items", [])),
                "user_provided": [],
                "system_inferred": [],
                "default_assumed": [],
                "externally_fetched": [],
            }
            for item in data.get("items", []):
                entry = _as_dict(item)
                source_type = _text(entry.get("source_type")) or "default_assumed"
                if source_type == "external_data":
                    source_type = "externally_fetched"
                normalized.setdefault(source_type, []).append(entry)
            return normalized
        normalized = {
            "user_provided": list(data.get("user_provided", [])) if isinstance(data.get("user_provided", []), list) else [],
            "system_inferred": list(data.get("system_inferred", [])) if isinstance(data.get("system_inferred", []), list) else [],
            "default_assumed": list(data.get("default_assumed", [])) if isinstance(data.get("default_assumed", []), list) else [],
            "externally_fetched": list(data.get("externally_fetched", [])) if isinstance(data.get("externally_fetched", []), list) else [],
        }
        return normalized

    provenance = {
        "user_provided": [],
        "system_inferred": [],
        "default_assumed": [],
        "externally_fetched": [],
    }

    def add(field: str, label: str, source_type: str, detail: str) -> None:
        normalized_source = "externally_fetched" if source_type == "external_data" else source_type
        provenance.setdefault(normalized_source, []).append(
            {
                "field": field,
                "label": label,
                "source_type": normalized_source,
                "detail": detail,
            }
        )

    if workflow_type == WorkflowType.ONBOARDING:
        add(
            "profile",
            "账户画像",
            "user_provided" if envelope.get("account_profile_id") is not None else "default_assumed",
            "首次建档时录入的账户与风险偏好信息。",
        )
        add(
            "holdings",
            "当前资产与持仓",
            "user_provided" if any(key in envelope for key in ("account_raw", "live_portfolio")) else "default_assumed",
            "来自本轮建档时提交的资产快照；未显式标注时按用户输入处理。",
        )
        add(
            "goal",
            "目标与期限",
            "user_provided" if any(key in envelope for key in ("goal_raw", "goal_solver_input")) else "default_assumed",
            "来自首次建档时填写的目标期末总资产、期限和月投入。",
        )
        add(
            "constraints",
            "风险约束",
            "user_provided" if any(key in envelope for key in ("constraint_raw", "goal_solver_input")) else "default_assumed",
            "来自建档时填写的回撤约束和投资限制。",
        )
    else:
        add(
            "baseline",
            "已有基线方案",
            "system_inferred" if has_prior_baseline else "default_assumed",
            "来自上一轮建档或季度复审沉淀的正式基线。",
        )
        add(
            "goal",
            "目标与期限",
            "system_inferred" if has_prior_baseline else "user_provided",
            "本轮沿用上一轮确认过的目标与期限，除非用户重新提交。",
        )
        add(
            "constraints",
            "风险约束",
            "system_inferred" if has_prior_baseline else "user_provided",
            "本轮默认沿用上一轮约束配置，除非用户主动修改。",
        )

    add(
        "market",
        "市场数据",
        "external_data" if any(key in envelope for key in ("market_raw", "market_state")) else "default_assumed",
        "若未显式标注来源，则仅表示系统收到一份市场快照，并不保证为实时抓取。",
    )
    add(
        "behavior",
        "行为信号",
        "system_inferred" if envelope.get("behavior_raw") is not None else "default_assumed",
        "来自系统对近期行为、复核请求和冷静期状态的推断或默认值。",
    )
    if envelope.get("user_request_context") is not None:
        add(
            "user_request",
            "用户指令",
            "user_provided",
            "来自本轮用户明确提出的动作请求。",
        )

    return provenance


def _gate1_input_record_priority(record: dict[str, Any]) -> tuple[int, int, int, int]:
    source_type = str(record.get("source_type") or "").strip()
    data_status_raw = record.get("data_status")
    try:
        data_status = coerce_data_status(
            data_status_raw or _GATE1_SOURCE_TO_DATA_STATUS.get(source_type, DataStatus.INFERRED).value
        )
    except ValueError:
        data_status = DataStatus.INFERRED
    audit_window = AuditWindow.from_any(record.get("audit_window"))
    return (
        _GATE1_SOURCE_PRIORITY.get(source_type, 0),
        _GATE1_DATA_STATUS_PRIORITY.get(data_status, 0),
        1 if str(record.get("source_ref") or "").strip() else 0,
        1 if audit_window is not None and audit_window.has_required_window() else 0,
    )


def _gate1_best_input_records(input_provenance: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    provenance = input_provenance or {}
    preferred: dict[str, dict[str, Any]] = {}
    ordered_sources = ("externally_fetched", "user_provided", "system_inferred", "default_assumed")
    for source_type in ordered_sources:
        for item in list(provenance.get(source_type) or []):
            record = dict(_as_dict(item))
            field = str(record.get("field") or "").strip()
            if not field:
                continue
            record.setdefault("source_type", source_type)
            current = preferred.get(field)
            if current is None or _gate1_input_record_priority(record) > _gate1_input_record_priority(current):
                preferred[field] = record
    return preferred


def _gate1_record_matches_required_domain(domain: str, record: dict[str, Any]) -> bool:
    field = str(record.get("field") or "").strip()
    if not field:
        return False
    if field == domain:
        return True
    prefixes = _GATE1_DOMAIN_FIELD_PREFIXES.get(domain, ())
    return any(field == prefix or field.startswith(prefix) for prefix in prefixes)


def _gate1_record_for_required_domain(
    domain: str,
    *,
    input_provenance: dict[str, Any] | None,
    preferred_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    preferred = preferred_records or _gate1_best_input_records(input_provenance)
    exact = preferred.get(domain)
    if exact is not None:
        return exact
    best: dict[str, Any] | None = None
    for record in preferred.values():
        if not _gate1_record_matches_required_domain(domain, record):
            continue
        if best is None or _gate1_input_record_priority(record) > _gate1_input_record_priority(best):
            best = record
    return best


def _gate1_formal_evidence_degradation_reasons(
    *,
    input_provenance: dict[str, Any] | None,
    snapshot_primary_formal_path: bool = False,
    snapshot_bundle: Any | None = None,
    market_raw: Any | None = None,
) -> list[str]:
    records = _gate1_best_input_records(input_provenance)
    reasons: list[str] = []
    for field in sorted(_FORMAL_PATH_REQUIRED_FIELDS):
        record = _gate1_record_for_required_domain(
            field,
            input_provenance=input_provenance,
            preferred_records=records,
        )
        if record is None:
            reasons.append(f"{field} formal audit record missing")
            continue
        source_type = str(record.get("source_type") or "").strip()
        try:
            data_status = coerce_data_status(
                record.get("data_status")
                or _GATE1_SOURCE_TO_DATA_STATUS.get(source_type, DataStatus.INFERRED).value
            )
        except ValueError:
            data_status = DataStatus.INFERRED
        if data_status in _GATE1_NON_FORMAL_DATA_STATUSES:
            reasons.append(f"{field} is backed by non-formal data_status={data_status.value}")
        if source_type == "externally_fetched":
            audit_window = AuditWindow.from_any(record.get("audit_window"))
            if not str(record.get("source_ref") or "").strip():
                reasons.append(f"{field} missing formal audit source_ref")
            if not str(record.get("as_of") or "").strip():
                reasons.append(f"{field} missing formal audit as_of")
            if audit_window is None or not audit_window.has_required_window():
                reasons.append(f"{field} missing formal audit_window")
    if snapshot_primary_formal_path:
        snapshot_data = _as_dict(snapshot_bundle)
        snapshot_market = _as_dict(snapshot_data.get("market"))
        raw_market = _as_dict(market_raw)
        universe_payload = _as_dict(
            raw_market.get("product_universe_result")
            or raw_market.get("runtime_product_universe_result")
            or raw_market.get("product_universe_snapshot")
            or snapshot_market.get("product_universe_result")
            or snapshot_market.get("runtime_product_universe_result")
            or snapshot_market.get("product_universe_snapshot")
        )
        valuation_payload = _as_dict(
            raw_market.get("product_valuation_result")
            or raw_market.get("valuation_result")
            or snapshot_market.get("product_valuation_result")
            or snapshot_market.get("valuation_result")
        )
        historical_payload = _as_dict(
            raw_market.get("historical_dataset")
            or snapshot_market.get("historical_dataset")
            or snapshot_data.get("historical_dataset_metadata")
        )
        simulation_input = _as_dict(historical_payload.get("product_simulation_input"))
        simulation_coverage = _as_dict(simulation_input.get("coverage_summary"))

        universe_status = (
            _text(universe_payload.get("source_status") or universe_payload.get("data_status")) or ""
        ).lower()
        valuation_status = (
            _text(valuation_payload.get("source_status") or valuation_payload.get("data_status")) or ""
        ).lower()
        try:
            observed_product_count = int(simulation_coverage.get("observed_product_count") or 0)
        except (TypeError, ValueError):
            observed_product_count = 0

        if not universe_payload:
            reasons.append("snapshot_primary_formal_path missing product_universe_result")
        elif universe_status not in {"observed", "verified"}:
            reasons.append(
                "snapshot_primary_formal_path product_universe_result is not formal_observed"
            )
        if not valuation_payload:
            reasons.append("snapshot_primary_formal_path missing product_valuation_result")
        elif valuation_status not in {"observed", "verified"}:
            reasons.append(
                "snapshot_primary_formal_path product_valuation_result is not formal_observed"
            )
        if not simulation_input:
            reasons.append("snapshot_primary_formal_path missing product_simulation_input")
        elif observed_product_count <= 0:
            reasons.append(
                "snapshot_primary_formal_path product_simulation_input has no observed products"
            )
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def _gate1_simulation_mode_degradation_reasons(
    *,
    calibration_result: Any,
    execution_policy: ExecutionPolicy,
    probability_engine_result: Any = None,
) -> list[str]:
    if execution_policy not in _FORMAL_EXECUTION_POLICIES:
        return []
    probability_payload = _as_dict(probability_engine_result)
    probability_output = _as_dict(probability_payload.get("output"))
    probability_primary = _as_dict(probability_output.get("primary_result"))
    selected_mode = (
        _text(probability_primary.get("recipe_name"))
        or _text(probability_output.get("simulation_mode_used"))
        or _text(probability_payload.get("simulation_mode"))
        or ""
    ).lower()
    if selected_mode and selected_mode != "static_gaussian":
        return []
    calibration_data = _as_dict(calibration_result)
    distribution_state = _as_dict(calibration_data.get("distribution_model_state"))
    selected_mode = (
        _text(distribution_state.get("selected_mode"))
        or _text(distribution_state.get("simulation_mode"))
        or _text(calibration_data.get("selected_mode"))
        or _text(calibration_data.get("simulation_mode"))
        or ""
    ).lower()
    if selected_mode == "static_gaussian":
        return ["simulation_mode static_gaussian is demo_only_for_formal_and_claw_paths"]
    return []


def _whole_number_text(value: Any) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return _text(value) or ""


def _goal_amount_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _text(value) or ""
    if numeric >= 10000 and numeric % 10000 == 0:
        return f"{int(numeric / 10000)}万"
    return _whole_number_text(numeric)


def _horizon_text(months: Any) -> str:
    try:
        month_count = int(months)
    except (TypeError, ValueError):
        return _text(months) or ""
    if month_count > 0 and month_count % 12 == 0:
        return f"{month_count // 12}年"
    return f"{month_count}个月"


def _drawdown_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _text(value) or ""
    if numeric <= 1.0:
        numeric *= 100.0
    return f"{int(round(numeric))}%"


def _build_goal_fallback_suggestions(goal_solver_input: Any) -> list[dict[str, Any]]:
    baseline = _as_dict(goal_solver_input)
    if not baseline:
        return []

    goal = _as_dict(baseline.get("goal"))
    cashflow_plan = _as_dict(baseline.get("cashflow_plan"))
    constraints = _as_dict(baseline.get("constraints"))

    current_months = int(goal.get("horizon_months", 0) or 0)
    current_goal_amount = float(goal.get("goal_amount", 0.0) or 0.0)
    current_monthly = float(cashflow_plan.get("monthly_contribution", 0.0) or 0.0)
    current_drawdown = float(constraints.get("max_drawdown_tolerance", 0.0) or 0.0)

    scenario_inputs: list[tuple[str, dict[str, Any]]] = []

    extend_horizon = deepcopy(baseline)
    extend_horizon_goal = _as_dict(extend_horizon.get("goal"))
    extend_horizon_goal["horizon_months"] = current_months + 12
    extend_horizon["goal"] = extend_horizon_goal
    scenario_inputs.append(
        (
            f"把期限从{_horizon_text(current_months)}延长到{_horizon_text(current_months + 12)}",
            extend_horizon,
        )
    )

    reduce_goal = deepcopy(baseline)
    reduce_goal_goal = _as_dict(reduce_goal.get("goal"))
    reduced_goal_amount = round(current_goal_amount * 0.9, -4 if current_goal_amount >= 100000 else -3)
    reduce_goal_goal["goal_amount"] = reduced_goal_amount
    reduce_goal["goal"] = reduce_goal_goal
    scenario_inputs.append(
        (
            f"把目标期末总资产从{_goal_amount_text(current_goal_amount)}下调到{_goal_amount_text(reduced_goal_amount)}",
            reduce_goal,
        )
    )

    increase_monthly = deepcopy(baseline)
    increase_monthly_plan = _as_dict(increase_monthly.get("cashflow_plan"))
    increased_monthly = round(current_monthly * 1.25, -3)
    increase_monthly_plan["monthly_contribution"] = increased_monthly
    increase_monthly["cashflow_plan"] = increase_monthly_plan
    scenario_inputs.append(
        (
            f"把每月投入从{_whole_number_text(current_monthly)}提高到{_whole_number_text(increased_monthly)}",
            increase_monthly,
        )
    )

    relax_drawdown = deepcopy(baseline)
    relax_drawdown_constraints = _as_dict(relax_drawdown.get("constraints"))
    relaxed_drawdown = min(current_drawdown + 0.05, 0.35)
    relax_drawdown_constraints["max_drawdown_tolerance"] = relaxed_drawdown
    relax_drawdown["constraints"] = relax_drawdown_constraints
    scenario_inputs.append(
        (
            f"把最大回撤容忍度从{_drawdown_text(current_drawdown)}放宽到{_drawdown_text(relaxed_drawdown)}",
            relax_drawdown,
        )
    )

    suggestions: list[dict[str, Any]] = []
    for label, scenario_input in scenario_inputs:
        scenario_output = _obj(run_goal_solver(scenario_input))
        result = _as_dict(scenario_output.get("recommended_result"))
        suggestions.append(
            {
                "label": label,
                "success_probability": result.get("success_probability"),
                "risk_summary": _as_dict(result.get("risk_summary")),
                "evidence_source": "model_estimate",
            }
        )
    return suggestions


def _enrich_goal_solver_output(goal_solver_output: Any, goal_solver_input: Any) -> Any:
    output = _obj(goal_solver_output)
    if not output:
        return goal_solver_output
    notes = [_text(note) or "" for note in output.get("solver_notes", [])]
    if not any("warning=no_feasible_allocation" in note for note in notes):
        return goal_solver_output
    existing = output.get("fallback_suggestions", [])
    if existing:
        return goal_solver_output
    suggestions = _build_goal_fallback_suggestions(goal_solver_input)
    if isinstance(goal_solver_output, dict):
        goal_solver_output["fallback_suggestions"] = suggestions
        return goal_solver_output
    if hasattr(goal_solver_output, "fallback_suggestions"):
        goal_solver_output.fallback_suggestions = suggestions
    return goal_solver_output


def _build_card_input(
    *,
    run_id: str,
    workflow_type: WorkflowType,
    bundle_id: str | None,
    calibration_id: str | None,
    solver_snapshot_id: str | None,
    goal_solver_output: Any,
    goal_solver_input: Any,
    runtime_result: Any,
    probability_engine_result: Any,
    workflow_decision: WorkflowDecision,
    runtime_restriction: RuntimeRestriction,
    execution_plan_summary: dict[str, Any],
    audit_record: OrchestratorAuditRecord | None,
    run_outcome_status: str | None,
    resolved_result_category: str | None,
    probability_truth_view: dict[str, Any] | None = None,
    disclosure_decision: dict[str, Any],
    evidence_bundle: dict[str, Any],
    input_provenance: Any,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
    control_directives: list[str],
) -> DecisionCardBuildInput:
    return DecisionCardBuildInput(
        card_type=_card_type_for_workflow(workflow_type, bool(blocking_reasons)),
        workflow_type=workflow_type.value,
        run_id=run_id,
        bundle_id=bundle_id,
        calibration_id=calibration_id,
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        goal_solver_input=goal_solver_input,
        runtime_result=runtime_result,
        probability_engine_result=probability_engine_result,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        execution_plan_summary=execution_plan_summary,
        audit_record=audit_record,
        run_outcome_status=run_outcome_status,
        resolved_result_category=resolved_result_category,
        probability_truth_view=dict(probability_truth_view or {}),
        disclosure_decision=disclosure_decision,
        evidence_bundle=evidence_bundle,
        input_provenance=input_provenance,
        blocking_reasons=list(blocking_reasons),
        degraded_notes=list(degraded_notes),
        escalation_reasons=list(escalation_reasons),
        control_directives=list(control_directives),
    )


def _replace_candidate_allocations(
    goal_solver_input: dict[str, Any],
    candidate_allocations: list[Any],
    bundle_id: str | None,
) -> dict[str, Any]:
    updated = dict(goal_solver_input)
    updated["candidate_allocations"] = [
        allocation.to_dict() if hasattr(allocation, "to_dict") else dict(allocation)
        for allocation in candidate_allocations
    ]
    if bundle_id:
        updated["snapshot_id"] = bundle_id
    return updated


def _apply_calibration_to_goal_solver_input(
    goal_solver_input: dict[str, Any],
    calibration_data: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(goal_solver_input)
    constraint_state = _as_dict(calibration_data.get("constraint_state"))
    if constraint_state:
        constraints = _as_dict(updated.get("constraints"))
        for field_name in _GOAL_SOLVER_CONSTRAINT_FIELDS:
            if field_name in constraint_state:
                constraints[field_name] = constraint_state[field_name]
        if constraints:
            updated["constraints"] = constraints

    goal_solver_params = _as_dict(calibration_data.get("goal_solver_params"))
    if goal_solver_params:
        updated["solver_params"] = goal_solver_params
    else:
        solver_params = _as_dict(updated.get("solver_params"))
        market_assumptions = calibration_data.get("market_assumptions")
        if solver_params and market_assumptions is not None:
            solver_params["market_assumptions"] = _obj(market_assumptions)
            updated["solver_params"] = solver_params
    return updated


def _resolve_runtime_inputs(
    envelope: dict[str, Any],
    calibration_data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    resolved = {
        "live_portfolio": envelope.get("live_portfolio"),
        "market_state": envelope.get("market_state") or calibration_data.get("market_state"),
        "behavior_state": envelope.get("behavior_state") or calibration_data.get("behavior_state"),
        "constraint_state": envelope.get("constraint_state") or calibration_data.get("constraint_state"),
        "ev_params": envelope.get("ev_params") or calibration_data.get("ev_params"),
        "optimizer_params": envelope.get("optimizer_params") or calibration_data.get("runtime_optimizer_params"),
    }
    missing = [name for name, value in resolved.items() if value is None]
    return resolved, missing


def _validate_solver_baseline_pair(
    solver_output: Any,
    solver_input: Any,
    blocking_reasons: list[str],
) -> None:
    output_data = _as_dict(solver_output)
    solver_input_data = _as_dict(solver_input)
    output_snapshot_id = _text(output_data.get("input_snapshot_id"))
    solver_snapshot_id = _text(solver_input_data.get("snapshot_id"))
    if output_snapshot_id and solver_snapshot_id and output_snapshot_id != solver_snapshot_id:
        blocking_reasons.append("prior solver baseline snapshot mismatch")

    output_params_version = _text(output_data.get("params_version"))
    solver_params_version = _text(_as_dict(solver_input_data.get("solver_params")).get("version"))
    if output_params_version and solver_params_version and output_params_version != solver_params_version:
        blocking_reasons.append("prior solver baseline params_version mismatch")


def _status_from_flags(
    *,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> WorkflowStatus:
    if blocking_reasons:
        return WorkflowStatus.BLOCKED
    if escalation_reasons:
        return WorkflowStatus.ESCALATED
    if degraded_notes:
        return WorkflowStatus.DEGRADED
    return WorkflowStatus.COMPLETED


def _quality_value(value: Any, key: str) -> str:
    return (_text(_as_dict(value).get(key)) or "").lower()


def _gate1_coverage_summary(goal_solver_output: Any) -> CoverageSummary:
    result = _as_dict(_as_dict(goal_solver_output).get("recommended_result"))
    return CoverageSummary.from_any(result.get("simulation_coverage_summary")) or CoverageSummary.from_any({})  # type: ignore[return-value]


def _gate1_run_outcome_status(
    *,
    status: WorkflowStatus,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
    formal_evidence_degradation_reasons: list[str],
) -> RunOutcomeStatus:
    if status == WorkflowStatus.BLOCKED or blocking_reasons:
        return RunOutcomeStatus.BLOCKED
    if (
        status in {WorkflowStatus.DEGRADED, WorkflowStatus.ESCALATED}
        or degraded_notes
        or escalation_reasons
        or formal_evidence_degradation_reasons
    ):
        return RunOutcomeStatus.DEGRADED
    return RunOutcomeStatus.COMPLETED


def _gate1_resolved_result_category(
    *,
    run_outcome_status: RunOutcomeStatus,
    goal_solver_output: Any,
    coverage_summary: CoverageSummary,
) -> str | None:
    if run_outcome_status in {RunOutcomeStatus.UNAVAILABLE, RunOutcomeStatus.BLOCKED}:
        return None
    if run_outcome_status == RunOutcomeStatus.DEGRADED:
        return "degraded_formal_result"
    result = _as_dict(_as_dict(goal_solver_output).get("recommended_result"))
    if not result:
        return None
    normalized_method = normalize_product_probability_method(
        result.get("product_probability_method") or "product_estimated_path"
    )
    if (
        normalized_method == "product_independent_path"
        and coverage_summary.independent_weight_adjusted_coverage >= 0.999
        and coverage_summary.independent_horizon_complete_coverage >= 0.999
        and coverage_summary.distribution_ready_coverage >= 0.999
    ):
        return "formal_independent_result"
    return "formal_estimated_result"


def _gate1_data_completeness(
    coverage_summary: CoverageSummary,
    *,
    formal_evidence_degraded: bool,
) -> str:
    if formal_evidence_degraded:
        return "partial"
    if (
        coverage_summary.weight_adjusted_coverage >= 0.95
        and coverage_summary.explanation_ready_coverage >= 0.95
    ):
        return "complete"
    if coverage_summary.weight_adjusted_coverage >= 0.5 or coverage_summary.selected_product_count > 0:
        return "partial"
    return "sparse"


def _gate1_calibration_quality(calibration_result: Any) -> str:
    quality = _quality_value(calibration_result, "calibration_quality")
    if quality in {"strong", "acceptable", "weak", "insufficient_sample"}:
        return quality
    return {
        "full": "acceptable",
        "partial": "weak",
        "degraded": "weak",
    }.get(quality, "insufficient_sample")


def _gate1_confidence_level(
    *,
    resolved_result_category: str | None,
    data_completeness: str,
    calibration_quality: str,
    coverage_summary: CoverageSummary,
    formal_evidence_degraded: bool,
) -> str:
    if (
        resolved_result_category == "formal_independent_result"
        and data_completeness == "complete"
        and calibration_quality in {"strong", "acceptable"}
        and coverage_summary.distribution_ready_coverage >= 0.95
        and not formal_evidence_degraded
    ):
        return "high"
    if resolved_result_category == "formal_estimated_result":
        return "medium"
    return "low"


def _gate1_disclosure_decision(
    *,
    resolved_result_category: str | None,
    run_outcome_status: RunOutcomeStatus,
    coverage_summary: CoverageSummary,
    calibration_result: Any,
    degraded_notes: list[str],
    blocking_reasons: list[str],
    formal_evidence_degradation_reasons: list[str],
) -> DisclosureDecision:
    data_completeness = _gate1_data_completeness(
        coverage_summary,
        formal_evidence_degraded=bool(formal_evidence_degradation_reasons),
    )
    calibration_quality = _gate1_calibration_quality(calibration_result)
    confidence_level = _gate1_confidence_level(
        resolved_result_category=resolved_result_category,
        data_completeness=data_completeness,
        calibration_quality=calibration_quality,
        coverage_summary=coverage_summary,
        formal_evidence_degraded=bool(formal_evidence_degradation_reasons),
    )
    if resolved_result_category == "formal_independent_result" and confidence_level == "high":
        disclosure_level = "point_and_range"
    elif resolved_result_category in {"formal_estimated_result", "degraded_formal_result"}:
        disclosure_level = "range_only"
    elif run_outcome_status in {RunOutcomeStatus.UNAVAILABLE, RunOutcomeStatus.BLOCKED}:
        disclosure_level = "unavailable"
    else:
        disclosure_level = "diagnostic_only"
    reasons = list(formal_evidence_degradation_reasons or degraded_notes or blocking_reasons)
    if not reasons and resolved_result_category == "formal_estimated_result":
        reasons = ["estimated_result_requires_range_disclosure"]
    if not reasons and disclosure_level == "unavailable":
        reasons = ["formal_result_unavailable"]
    return DisclosureDecision(
        result_category=resolved_result_category or "",
        disclosure_level=disclosure_level,
        confidence_level=confidence_level,
        data_completeness=data_completeness,
        calibration_quality=calibration_quality,
        point_value_allowed=disclosure_level == "point_and_range",
        range_required=disclosure_level in {"point_and_range", "range_only"},
        diagnostic_only=disclosure_level == "diagnostic_only",
        precision_cap=disclosure_level,
        reasons=reasons,
    )


def _gate1_evidence_bundle(
    *,
    run_id: str,
    bundle_id: str | None,
    solver_snapshot_id: str | None,
    goal_solver_input: Any,
    goal_solver_output: Any,
    calibration_result: Any,
    run_outcome_status: RunOutcomeStatus,
    resolved_result_category: str | None,
    coverage_summary: CoverageSummary,
    disclosure_decision: DisclosureDecision,
    execution_policy: ExecutionPolicy,
    failure_artifact: FailureArtifact | None,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    snapshot_bundle: Any,
    runtime_result: Any,
    probability_engine_result: Any = None,
) -> EvidenceBundle:
    goal_input = _as_dict(goal_solver_input)
    snapshot_data = _as_dict(snapshot_bundle)
    market = _as_dict(snapshot_data.get("market"))
    runtime_data = _as_dict(runtime_result)
    universe_payload = _as_dict(
        market.get("product_universe_result")
        or market.get("runtime_product_universe_result")
        or market.get("product_universe_snapshot")
    )
    valuation_payload = _as_dict(
        market.get("product_valuation_result")
        or market.get("valuation_result")
    )
    historical_payload = _as_dict(
        market.get("historical_dataset")
        or snapshot_data.get("historical_dataset_metadata")
    )
    next_recoverable_actions: list[str] = []
    if blocking_reasons:
        next_recoverable_actions.append("repair_formal_inputs")
    elif degraded_notes:
        next_recoverable_actions.append("improve_evidence_coverage")
    input_refs = {
        key: value
        for key, value in {
            "snapshot_id": _text(goal_input.get("snapshot_id")) or "",
            "bundle_id": bundle_id or "",
            "solver_snapshot_id": solver_snapshot_id or "",
            "provider_signature": _text(universe_payload.get("provider_signature"))
            or _text(valuation_payload.get("provider_signature"))
            or "",
        }.items()
        if value
    }
    evidence_refs = {
        key: value
        for key, value in {
            "run_id": run_id,
            "calibration_id": _text(_as_dict(calibration_result).get("calibration_id")) or "",
            "universe_signature": _text(universe_payload.get("universe_signature")) or "",
            "valuation_signature": _text(valuation_payload.get("valuation_signature")) or "",
            "historical_version": _text(historical_payload.get("version_id")) or "",
            **(
                {}
                if failure_artifact is None
                else {
                    f"failure_ref:{key}": value
                    for key, value in failure_artifact.available_evidence_refs.items()
                }
            ),
        }.items()
        if value
    }
    if failure_artifact is not None:
        next_recoverable_actions = list(failure_artifact.next_recoverable_actions)
    failed_stage = None
    if run_outcome_status == RunOutcomeStatus.BLOCKED:
        failed_stage = (
            failure_artifact.failed_stage
            if failure_artifact is not None
            else "result_category_resolution"
        )
    calibration_payload = _as_dict(calibration_result)
    distribution_state = _as_dict(calibration_payload.get("distribution_model_state"))
    probability_payload = _as_dict(probability_engine_result)
    probability_output = _as_dict(probability_payload.get("output"))
    probability_primary = _as_dict(probability_output.get("primary_result"))
    simulation_mode = (
        _text(probability_primary.get("recipe_name"))
        or _text(probability_output.get("simulation_mode_used"))
        or _text(probability_payload.get("simulation_mode"))
        or
        _text(distribution_state.get("selected_mode"))
        or _text(distribution_state.get("simulation_mode"))
        or _text(_as_dict(goal_solver_output).get("simulation_mode_used"))
        or _text(calibration_payload.get("selected_mode"))
        or _text(calibration_payload.get("simulation_mode"))
        or _text(_as_dict(_as_dict(goal_solver_input).get("solver_params")).get("simulation_mode"))
    )
    return EvidenceBundle(
        bundle_schema_version="v1.3",
        execution_policy_version="v1.3",
        disclosure_policy_version="v1.3",
        mapping_signature=(
            _text(universe_payload.get("mapping_signature"))
            or _text(universe_payload.get("universe_signature"))
            or f"goal_solver:{goal_input.get('snapshot_id') or 'unknown'}"
        ),
        history_revision=(
            _text(historical_payload.get("history_revision"))
            or _text(historical_payload.get("version_id"))
            or _text(historical_payload.get("as_of"))
            or _text(_as_dict(goal_input.get("solver_params")).get("version"))
            or "unknown"
        ),
        distribution_revision=(
            _text(_as_dict(calibration_result).get("distribution_revision"))
            or _text(_as_dict(calibration_result).get("calibration_id"))
            or "unknown"
        ),
        solver_revision=_text(_as_dict(goal_input.get("solver_params")).get("version")) or "unknown",
        code_revision=_text(runtime_data.get("code_revision")) or "v1.3-package4",
        calibration_revision=_text(_as_dict(calibration_result).get("calibration_id")) or "unknown",
        request_id=run_id,
        account_profile_id=_text(goal_input.get("account_profile_id")) or "",
        as_of=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        requested_result_category="formal_independent_result",
        resolved_result_category=resolved_result_category,
        run_outcome_status=run_outcome_status,
        execution_policy=execution_policy.value,
        disclosure_policy="FORMAL_STANDARD",
        simulation_mode=simulation_mode,
        input_refs=input_refs,
        evidence_refs=evidence_refs,
        coverage_summary=coverage_summary,
        calibration_summary={
            "calibration_quality": _gate1_calibration_quality(calibration_result),
        },
        formal_path_status=run_outcome_status.value,
        failed_stage=failed_stage,
        blocking_predicates=list(
            failure_artifact.blocking_predicates if failure_artifact is not None else blocking_reasons
        ),
        degradation_reasons=list(degraded_notes),
        next_recoverable_actions=next_recoverable_actions,
        diagnostics_trustworthy=(
            failure_artifact.trustworthy_partial_diagnostics
            if failure_artifact is not None
            else run_outcome_status != RunOutcomeStatus.BLOCKED
        ),
        disclosure_decision=disclosure_decision,
    )


def _evaluate_preflight_controls(
    raw_bundle_id: Any,
    snapshot_bundle: Any,
    calibration_result: Any,
) -> tuple[str | None, list[str], list[str]]:
    snapshot_data = _as_dict(snapshot_bundle)
    blocking_reasons: list[str] = []
    degraded_notes: list[str] = []
    raw_bundle_text = _text(raw_bundle_id)
    bundle_id = raw_bundle_text or _text(snapshot_data.get("bundle_id"))

    snapshot_bundle_id = _text(snapshot_data.get("bundle_id"))
    if raw_bundle_text and snapshot_bundle_id and raw_bundle_text != snapshot_bundle_id:
        blocking_reasons.append("bundle_id mismatch between raw_inputs and snapshot_bundle")

    bundle_quality = _quality_value(snapshot_data, "bundle_quality")
    if bundle_quality == "degraded":
        blocking_reasons.append("bundle_quality=degraded")
    elif bundle_quality and bundle_quality not in {"full"}:
        degraded_notes.append(f"bundle_quality={bundle_quality}")

    calibration_quality = _quality_value(calibration_result, "calibration_quality")
    if calibration_quality == "degraded":
        blocking_reasons.append("calibration_quality=degraded")
    elif calibration_quality == "partial":
        degraded_notes.append("calibration_quality=partial")
    elif calibration_quality not in {"", "full"}:
        degraded_notes.append(f"calibration_quality={calibration_quality}")

    return bundle_id, blocking_reasons, degraded_notes


def _append_bundle_provenance_checks(
    bundle_id: str | None,
    calibration_data: dict[str, Any],
    blocking_reasons: list[str],
) -> None:
    if bundle_id is None:
        return
    refs = (
        ("calibration.source_bundle_id", calibration_data.get("source_bundle_id")),
        (
            "param_version_meta.source_bundle_id",
            _as_dict(calibration_data.get("param_version_meta")).get("source_bundle_id"),
        ),
        (
            "market_state.source_bundle_id",
            _as_dict(calibration_data.get("market_state")).get("source_bundle_id"),
        ),
        (
            "constraint_state.source_bundle_id",
            _as_dict(calibration_data.get("constraint_state")).get("source_bundle_id"),
        ),
        (
            "behavior_state.source_bundle_id",
            _as_dict(calibration_data.get("behavior_state")).get("source_bundle_id"),
        ),
    )
    for label, source_bundle_id in refs:
        source_bundle_text = _text(source_bundle_id)
        if source_bundle_text is not None and source_bundle_text != bundle_id:
            blocking_reasons.append(f"{label} mismatch with bundle_id")


def _relax_provenance_blocking_reasons(blocking_reasons: list[str]) -> list[str]:
    return [reason for reason in blocking_reasons if "mismatch" not in reason]


def _control_directives_from_runtime_restriction(
    runtime_restriction: RuntimeRestriction,
) -> list[str]:
    directives: list[str] = []
    if runtime_restriction.allowed_actions:
        directives.append(
            "allowed_actions=" + ",".join(runtime_restriction.allowed_actions)
        )
    if runtime_restriction.blocked_actions:
        directives.append(
            "blocked_actions=" + ",".join(runtime_restriction.blocked_actions)
        )
    if runtime_restriction.forced_safe_action:
        directives.append(
            f"forced_safe_action={runtime_restriction.forced_safe_action}"
        )
    if runtime_restriction.requires_escalation:
        directives.append("manual_review_required")
    return directives


def _action_type_from_ranked_entry(entry: Any) -> str | None:
    entry_data = _as_dict(entry)
    action_data = _as_dict(entry_data.get("action"))
    return _text(action_data.get("type"))


def _safe_ranked_actions(ranked_actions: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    safe_actions: list[dict[str, Any]] = []
    blocked_action_types: list[str] = []
    for entry in ranked_actions:
        entry_data = _as_dict(entry)
        action_type = _action_type_from_ranked_entry(entry_data)
        if action_type in _SAFE_ACTION_TYPES:
            safe_actions.append(entry_data)
        elif action_type is not None and action_type not in blocked_action_types:
            blocked_action_types.append(action_type)
    return safe_actions, blocked_action_types


def _restrict_runtime_result(runtime_result: Any, forced_safe_action: str) -> tuple[Any, list[str]]:
    runtime_data = _as_dict(runtime_result)
    ev_report = _as_dict(runtime_data.get("ev_report"))
    ranked_actions = list(ev_report.get("ranked_actions", []))
    safe_ranked_actions, blocked_action_types = _safe_ranked_actions(ranked_actions)

    if safe_ranked_actions:
        preferred = next(
            (
                entry
                for entry in safe_ranked_actions
                if _action_type_from_ranked_entry(entry) == forced_safe_action
            ),
            safe_ranked_actions[0],
        )
        recommended_action = _as_dict(preferred.get("action"))
        recommended_score = preferred.get("score")
        after_value = ev_report.get("goal_solver_after_recommended")
        if recommended_score is None:
            after_value = ev_report.get("goal_solver_baseline")
    else:
        recommended_action = {"type": forced_safe_action}
        recommended_score = None
        after_value = ev_report.get("goal_solver_baseline")
        safe_ranked_actions = [
            {
                "action": {"type": forced_safe_action},
                "score": None,
                "rank": 1,
                "is_recommended": True,
                "recommendation_reason": f"{forced_safe_action} forced by orchestrator guardrail",
            }
        ]

    for index, entry in enumerate(safe_ranked_actions, start=1):
        entry["rank"] = index
        entry["is_recommended"] = index == 1

    ev_report["ranked_actions"] = safe_ranked_actions
    ev_report["recommended_action"] = recommended_action
    ev_report["recommended_score"] = recommended_score
    ev_report["goal_solver_after_recommended"] = after_value
    ev_report["confidence_flag"] = "low"
    base_reason = _first_text(ev_report.get("confidence_reason"), "restricted by orchestrator")
    ev_report["confidence_reason"] = f"{base_reason}; safe actions only"

    if not isinstance(runtime_result, dict) and hasattr(runtime_result, "ev_report"):
        runtime_result.ev_report = ev_report
    elif isinstance(runtime_result, dict):
        runtime_result["ev_report"] = ev_report
    else:
        runtime_data["ev_report"] = ev_report
        runtime_result = runtime_data

    return runtime_result, blocked_action_types


def _build_runtime_restriction(
    *,
    trigger: TriggerSignal,
    workflow_type: WorkflowType,
    control_flags: dict[str, Any],
    runtime_result: Any,
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> tuple[RuntimeRestriction, Any]:
    restriction_reasons: list[str] = []
    candidate_poverty = bool(
        runtime_result is not None and getattr(runtime_result, "candidate_poverty", False)
    )
    if control_flags["cooldown_active"]:
        restriction_reasons.append("cooldown_active")
    if control_flags["manual_review_requested"]:
        restriction_reasons.append("manual_review_requested")
    if control_flags["manual_override_requested"]:
        restriction_reasons.append("manual_override_requested")
    if control_flags["high_risk_request"]:
        restriction_reasons.append("high_risk_request")
    if candidate_poverty:
        restriction_reasons.append("candidate_poverty")

    forced_safe_action = "freeze" if restriction_reasons else None
    requires_escalation = False
    if control_flags["manual_review_requested"]:
        requires_escalation = True
    if control_flags["manual_override_requested"]:
        requires_escalation = True
    if control_flags["cooldown_active"] and control_flags["high_risk_request"]:
        requires_escalation = True
    if workflow_type == WorkflowType.EVENT and control_flags["cooldown_active"]:
        requires_escalation = True

    if control_flags["cooldown_active"]:
        degraded_notes.append("cooldown_active=true")
    if control_flags["high_risk_request"]:
        degraded_notes.append("high_risk_request=true")
    if control_flags["manual_review_requested"]:
        escalation_reasons.append("manual_review_requested")
    if control_flags["manual_override_requested"]:
        escalation_reasons.append("manual_override_requested")
    if control_flags["cooldown_active"] and control_flags["high_risk_request"]:
        escalation_reasons.append("high_risk_request_during_cooldown")
    elif workflow_type == WorkflowType.EVENT and control_flags["cooldown_active"]:
        escalation_reasons.append("event_requires_manual_review_under_cooldown")

    blocked_actions: list[str] = []
    if runtime_result is not None and forced_safe_action is not None:
        runtime_result, blocked_actions = _restrict_runtime_result(runtime_result, forced_safe_action)

    return (
        RuntimeRestriction(
            cooldown_active=bool(control_flags["cooldown_active"]),
            manual_review_requested=bool(control_flags["manual_review_requested"]),
            high_risk_request=bool(control_flags["high_risk_request"]),
            allowed_actions=list(_SAFE_ACTION_TYPES if forced_safe_action is not None else []),
            blocked_actions=blocked_actions,
            restriction_reasons=restriction_reasons,
            requires_escalation=requires_escalation,
            forced_safe_action=forced_safe_action,
        ),
        runtime_result,
    )


def _apply_runtime_controls(
    *,
    trigger: TriggerSignal,
    runtime_result: Any,
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> None:
    if runtime_result is None or not getattr(runtime_result, "candidate_poverty", False):
        return
    degraded_notes.append("candidate_poverty=true")
    if trigger.workflow_type == WorkflowType.QUARTERLY:
        escalation_reasons.append("quarterly_candidate_poverty")
    elif trigger.behavior_event:
        escalation_reasons.append("behavior_event_with_candidate_poverty")


def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _build_audit_record(
    *,
    workflow_decision: WorkflowDecision,
    trigger: TriggerSignal,
    control_flags: dict[str, Any],
    runtime_restriction: RuntimeRestriction,
    run_id: str,
    bundle_id: str | None,
    snapshot_bundle: Any,
    snapshot_bundle_origin: str,
    calibration_result: Any,
    calibration_origin: str,
    calibration_data: dict[str, Any],
    solver_snapshot_id: str | None,
    goal_solver_output: Any,
    runtime_result: Any,
    card_build_input: DecisionCardBuildInput | None,
    status: WorkflowStatus,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> OrchestratorAuditRecord:
    goal_output_data = _as_dict(goal_solver_output)
    runtime_data = _as_dict(runtime_result)
    runtime_ev_report = _as_dict(runtime_data.get("ev_report"))
    return OrchestratorAuditRecord(
        requested_workflow_type=None
        if workflow_decision.requested_workflow_type is None
        else workflow_decision.requested_workflow_type.value,
        selected_workflow_type=workflow_decision.selected_workflow_type.value,
        selection_reason=workflow_decision.selection_reason,
        trigger_flags={
            "structural_event": trigger.structural_event,
            "behavior_event": trigger.behavior_event,
            "drawdown_event": trigger.drawdown_event,
            "satellite_event": trigger.satellite_event,
            "manual_review_requested": trigger.manual_review_requested,
            "manual_override_requested": trigger.manual_override_requested,
            "high_risk_request": trigger.high_risk_request,
            "force_full_review": trigger.force_full_review,
        },
        control_flags={
            "manual_review_requested": bool(control_flags["manual_review_requested"]),
            "manual_override_requested": bool(control_flags["manual_override_requested"]),
            "quarterly_review_requested": bool(control_flags["quarterly_review_requested"]),
            "force_full_recalc": bool(control_flags["force_full_recalc"]),
            "major_parameter_update": bool(control_flags["major_parameter_update"]),
            "high_risk_request": bool(control_flags["high_risk_request"]),
            "requested_action": control_flags["requested_action"],
            "cooldown_active": bool(control_flags["cooldown_active"]),
            "cooldown_until": control_flags["cooldown_until"],
            "override_count_90d": control_flags["override_count_90d"],
            "audit_mode": bool(control_flags["audit_mode"]),
            "enforce_provenance_checks": bool(control_flags["enforce_provenance_checks"]),
            "allow_degraded_continue": bool(control_flags["allow_degraded_continue"]),
        },
        version_refs={
            "run_id": run_id,
            "bundle_id": bundle_id,
            "calibration_id": calibration_data.get("calibration_id"),
            "solver_snapshot_id": solver_snapshot_id,
            "goal_solver_params_version": _first_text(
                goal_output_data.get("params_version"),
                _as_dict(calibration_data.get("goal_solver_params")).get("version"),
            ),
            "runtime_optimizer_params_version": _first_text(
                runtime_data.get("optimizer_params_version"),
                _as_dict(calibration_data.get("runtime_optimizer_params")).get("version"),
            ),
            "ev_params_version": _first_text(
                runtime_ev_report.get("params_version"),
                _as_dict(calibration_data.get("ev_params")).get("version"),
            ),
            "runtime_run_timestamp": runtime_data.get("run_timestamp"),
        },
        artifact_refs={
            "has_snapshot_bundle": snapshot_bundle is not None,
            "has_calibration_result": calibration_result is not None,
            "has_goal_solver_output": goal_solver_output is not None,
            "has_runtime_result": runtime_result is not None,
            "has_card_build_input": card_build_input is not None,
            "runtime_restriction_active": bool(runtime_restriction.restriction_reasons),
            "snapshot_bundle_origin": snapshot_bundle_origin,
            "calibration_origin": calibration_origin,
        },
        outcome={
            "status": status.value,
            "blocking_reasons": list(blocking_reasons),
            "degraded_notes": list(degraded_notes),
            "escalation_reasons": list(escalation_reasons),
            "allowed_actions": list(runtime_restriction.allowed_actions),
            "blocked_actions": list(runtime_restriction.blocked_actions),
            "forced_safe_action": runtime_restriction.forced_safe_action,
        },
    )


def _build_execution_plan_summary(execution_plan: Any) -> dict[str, Any]:
    if execution_plan is None:
        return {}
    if hasattr(execution_plan, "summary"):
        return _as_dict(execution_plan.summary())
    data = _as_dict(execution_plan)
    items = list(data.get("items") or [])
    return {
        "plan_id": data.get("plan_id"),
        "plan_version": data.get("plan_version"),
        "source_run_id": data.get("source_run_id"),
        "source_allocation_id": data.get("source_allocation_id"),
        "status": data.get("status"),
        "item_count": len(items),
        "confirmation_required": bool(data.get("confirmation_required", True)),
        "warning_count": len(list(data.get("warnings") or [])),
        "approved_at": data.get("approved_at"),
        "superseded_by_plan_id": data.get("superseded_by_plan_id"),
    }


def _execution_plan_item_index_from_payload(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    data = _as_dict(payload)
    items = list(data.get("items") or [])
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        entry = _as_dict(item)
        bucket = _first_text(entry.get("asset_bucket")) or ""
        if bucket:
            index[bucket] = entry
    return index


def _primary_product_id_from_payload(item: dict[str, Any]) -> str | None:
    direct = _first_text(_as_dict(item).get("primary_product_id"))
    if direct:
        return direct
    product = _as_dict(_as_dict(item).get("primary_product"))
    nested = _first_text(product.get("product_id"))
    return nested


def _compare_execution_plan_payloads(
    active_payload: dict[str, Any] | None,
    pending_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not active_payload or not pending_payload:
        return None
    active_items = _execution_plan_item_index_from_payload(active_payload)
    pending_items = _execution_plan_item_index_from_payload(pending_payload)
    bucket_changes: list[dict[str, Any]] = []
    product_switches: list[dict[str, Any]] = []
    max_weight_delta = 0.0
    for bucket in sorted(set(active_items) | set(pending_items)):
        a = active_items.get(bucket, {})
        p = pending_items.get(bucket, {})
        aw = round(float(_as_dict(a).get("target_weight", 0.0) or 0.0), 4)
        pw = round(float(_as_dict(p).get("target_weight", 0.0) or 0.0), 4)
        delta = round(pw - aw, 4)
        a_pid = _primary_product_id_from_payload(a)
        p_pid = _primary_product_id_from_payload(p)
        product_changed = a_pid != p_pid and bool(a_pid or p_pid)
        if abs(delta) <= 1e-6 and not product_changed:
            continue
        max_weight_delta = max(max_weight_delta, abs(delta))
        change = {
            "asset_bucket": bucket,
            "active_target_weight": aw,
            "pending_target_weight": pw,
            "weight_delta": delta,
            "active_primary_product_id": a_pid,
            "pending_primary_product_id": p_pid,
            "product_changed": product_changed,
        }
        bucket_changes.append(change)
        if product_changed:
            product_switches.append(
                {
                    "asset_bucket": bucket,
                    "active_primary_product_id": a_pid,
                    "pending_primary_product_id": p_pid,
                }
            )

    bucket_set_changed = any(
        (item["active_target_weight"] <= 1e-6) != (item["pending_target_weight"] <= 1e-6)
        for item in bucket_changes
    )
    changed_bucket_count = len(bucket_changes)
    product_switch_count = len(product_switches)
    if changed_bucket_count == 0 and product_switch_count == 0:
        change_level = "none"
        recommendation = "keep_active"
        summary = ["pending plan matches current active plan"]
    else:
        if bucket_set_changed or max_weight_delta >= 0.10 or changed_bucket_count >= 3:
            change_level = "major"
            recommendation = "replace_active"
        else:
            change_level = "minor"
            recommendation = "review_replace"
        summary = [f"{changed_bucket_count} bucket changes detected"]
        if product_switch_count:
            summary.append(f"{product_switch_count} primary product switches detected")
        if max_weight_delta > 0.0:
            summary.append(f"largest weight delta={max_weight_delta:.2%}")

    return {
        "change_level": change_level,
        "recommendation": recommendation,
        "changed_bucket_count": changed_bucket_count,
        "product_switch_count": product_switch_count,
        "max_weight_delta": round(max_weight_delta, 4),
        "bucket_changes": bucket_changes,
        "product_switches": product_switches,
        "summary": summary,
    }


def _extract_execution_plan_restrictions(envelope: dict[str, Any]) -> list[str]:
    direct = envelope.get("execution_plan_restrictions")
    if isinstance(direct, list):
        return [str(item).strip() for item in direct if str(item).strip()]
    provenance = _as_dict(envelope.get("input_provenance"))
    items = list(provenance.get("items") or [])
    if not items:
        for group_name in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
            items.extend(list(provenance.get(group_name) or []))
    for item in items:
        if _first_text(_as_dict(item).get("field")) != "account.restrictions":
            continue
        value = _as_dict(item).get("value")
        if isinstance(value, list):
            return [str(entry).strip() for entry in value if str(entry).strip()]
        if value is None:
            return []
        rendered = str(value).strip()
        return [rendered] if rendered else []
    return []


def _extract_execution_plan_valuation_context(
    envelope: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    market_raw = _as_dict(envelope.get("market_raw"))
    valuation_inputs = _as_dict(
        market_raw.get("product_valuation_inputs")
        or market_raw.get("valuation_inputs")
        or {}
    )
    valuation_result = _as_dict(
        market_raw.get("product_valuation_result")
        or market_raw.get("valuation_result")
        or {}
    )
    return (
        valuation_inputs or None,
        valuation_result or None,
    )


def _extract_execution_plan_policy_news_signals(
    envelope: dict[str, Any],
) -> list[dict[str, Any]] | None:
    direct = envelope.get("policy_news_signals")
    if isinstance(direct, list) and direct:
        return [_as_dict(item) for item in direct if _as_dict(item)]
    market_raw = _as_dict(envelope.get("market_raw"))
    payload = market_raw.get("policy_news_signals")
    if isinstance(payload, list) and payload:
        return [_as_dict(item) for item in payload if _as_dict(item)]
    return None


def _extract_execution_plan_product_universe_context(
    envelope: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    market_raw = _as_dict(envelope.get("market_raw"))
    universe_inputs = _as_dict(
        market_raw.get("product_universe_inputs")
        or market_raw.get("runtime_product_universe_inputs")
        or {}
    )
    universe_result = _as_dict(
        market_raw.get("product_universe_result")
        or market_raw.get("runtime_product_universe_result")
        or market_raw.get("product_universe_snapshot")
        or {}
    )
    return (
        universe_inputs or None,
        universe_result or None,
    )


def _extract_execution_plan_runtime_candidates(
    envelope: dict[str, Any],
) -> list[ProductCandidate] | None:
    market_raw = _as_dict(envelope.get("market_raw"))
    universe_result = _as_dict(
        market_raw.get("product_universe_result")
        or market_raw.get("runtime_product_universe_result")
        or market_raw.get("product_universe_snapshot")
        or {}
    )
    candidates: list[ProductCandidate] = []
    for payload in list(universe_result.get("runtime_candidates") or []):
        if not isinstance(payload, dict):
            continue
        try:
            candidates.append(ProductCandidate(**dict(payload)))
        except TypeError:
            continue
    return candidates or None


def _extract_execution_plan_product_proxy_context(
    envelope: dict[str, Any],
) -> dict[str, Any] | None:
    market_raw = _as_dict(envelope.get("market_raw"))
    proxy_result = _as_dict(
        market_raw.get("product_proxy_result")
        or market_raw.get("proxy_result")
        or {}
    )
    return proxy_result or None


def _extract_probability_engine_factor_mapping_context(
    envelope: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    market_raw = _as_dict(envelope.get("market_raw"))
    probability_engine = _as_dict(market_raw.get("probability_engine"))
    factor_mapping_payload = _as_dict(
        probability_engine.get("factor_mapping")
        or market_raw.get("factor_mapping_result")
        or market_raw.get("probability_engine_factor_mapping")
        or {}
    )
    products: dict[str, dict[str, Any]] = {}
    raw_products = factor_mapping_payload.get("products")
    if isinstance(raw_products, dict):
        for product_id, raw_product in raw_products.items():
            product_payload = _as_dict(raw_product)
            if product_payload:
                products[str(product_id)] = product_payload
    elif isinstance(raw_products, list):
        for raw_product in raw_products:
            product_payload = _as_dict(raw_product)
            product_id = _first_text(product_payload.get("product_id"))
            if product_id:
                products[product_id] = product_payload
    for product_id, raw_product in _as_dict(factor_mapping_payload.get("products_by_id")).items():
        product_payload = _as_dict(raw_product)
        if product_payload:
            products[str(product_id)] = product_payload
    return products


def _extract_market_historical_dataset(envelope: dict[str, Any], snapshot_bundle: Any | None) -> dict[str, Any] | None:
    market_raw = _as_dict(envelope.get("market_raw"))
    historical_dataset = _as_dict(market_raw.get("historical_dataset"))
    if historical_dataset:
        return historical_dataset
    snapshot_market = _as_dict(_as_dict(snapshot_bundle).get("market"))
    historical_dataset = _as_dict(snapshot_market.get("historical_dataset"))
    return historical_dataset or None


def _extract_execution_plan_account_context(
    envelope: dict[str, Any],
) -> tuple[float | None, dict[str, float] | None, float | None, float | None, dict[str, float] | None]:
    account_raw = _as_dict(envelope.get("account_raw")) or _as_dict(envelope.get("live_portfolio"))
    baseline_input = _as_dict(envelope.get("goal_solver_input"))
    constraints = _as_dict(envelope.get("constraint_raw")) or _as_dict(baseline_input.get("constraints"))
    current_weights = _as_dict(account_raw.get("weights")) or None
    account_total_value = account_raw.get("total_value")
    available_cash = account_raw.get("available_cash")
    if available_cash is None and account_total_value is not None and current_weights:
        inferred_cash_weight = float(
            current_weights.get("cash_liquidity", current_weights.get("cash", 0.0)) or 0.0
        )
        if inferred_cash_weight > 0.0:
            available_cash = float(account_total_value) * inferred_cash_weight
    liquidity_reserve_min = constraints.get("liquidity_reserve_min")
    return (
        None if account_total_value is None else float(account_total_value),
        None
        if current_weights is None
        else {str(bucket): float(weight) for bucket, weight in current_weights.items()},
        None if available_cash is None else float(available_cash),
        None if liquidity_reserve_min is None else float(liquidity_reserve_min),
        None
        if not _as_dict(constraints.get("transaction_fee_rate"))
        else {
            str(bucket): float(rate)
            for bucket, rate in _as_dict(constraints.get("transaction_fee_rate")).items()
        },
    )


def _execution_policy(envelope: dict[str, Any]) -> ExecutionPolicy:
    explicit_policy = envelope.get("execution_policy")
    if explicit_policy is not None:
        return coerce_execution_policy(explicit_policy)
    explicit_formal = envelope.get("formal_path_required")
    if explicit_formal is None:
        return ExecutionPolicy.EXPLORATORY
    return (
        ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED
        if bool(explicit_formal)
        else ExecutionPolicy.EXPLORATORY
    )


def _formal_path_required(envelope: dict[str, Any]) -> bool:
    return _execution_policy(envelope) in {
        ExecutionPolicy.FORMAL_STRICT,
        ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED,
    }


def _collect_formal_path_preflight_issues(payloads: dict[str, Any], *, prefix: str) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    degraded: list[str] = []
    for name, raw_payload in payloads.items():
        payload = _as_dict(raw_payload)
        preflight = _as_dict(payload.get("formal_path_preflight"))
        status = _text(preflight.get("run_outcome_status"))
        if status == "blocked":
            predicates = list(preflight.get("blocking_predicates") or []) or ["formal_path_blocked"]
            blocking.extend(f"{prefix}[{name}]={predicate}" for predicate in predicates)
        elif status == "degraded":
            reasons = list(preflight.get("degradation_reasons") or []) or ["formal_path_degraded"]
            degraded.extend(f"{prefix}[{name}]={reason}" for reason in reasons)
    return blocking, degraded


def _collect_failure_artifacts(payloads: dict[str, Any]) -> list[FailureArtifact]:
    artifacts: list[FailureArtifact] = []
    for raw_payload in payloads.values():
        payload = _as_dict(raw_payload)
        artifact = FailureArtifact.from_any(payload.get("failure_artifact"))
        if artifact is not None:
            artifacts.append(artifact)
    return artifacts


def _primary_failure_artifact(*artifact_groups: list[FailureArtifact]) -> FailureArtifact | None:
    for group in artifact_groups:
        for artifact in group:
            if artifact is not None:
                return artifact
    return None


def _maybe_build_execution_plan(
    *,
    run_id: str,
    workflow_type: WorkflowType,
    status: WorkflowStatus,
    goal_solver_output: Any,
    envelope: dict[str, Any],
    formal_path_required: bool,
    execution_policy: ExecutionPolicy,
) -> Any | None:
    if status == WorkflowStatus.BLOCKED or workflow_type not in {
        WorkflowType.ONBOARDING,
        WorkflowType.QUARTERLY,
    }:
        return None
    goal_output = _as_dict(goal_solver_output)
    recommended = _as_dict(goal_output.get("recommended_allocation"))
    weights = _as_dict(recommended.get("weights"))
    allocation_name = _first_text(
        recommended.get("name"),
        _as_dict(goal_output.get("recommended_result")).get("allocation_name"),
    )
    if not weights or allocation_name is None:
        return None
    valuation_inputs, valuation_result = _extract_execution_plan_valuation_context(envelope)
    product_universe_inputs, product_universe_result = _extract_execution_plan_product_universe_context(envelope)
    runtime_candidates = _extract_execution_plan_runtime_candidates(envelope)
    product_proxy_result = _extract_execution_plan_product_proxy_context(envelope)
    policy_news_signals = _extract_execution_plan_policy_news_signals(envelope)
    account_total_value, current_weights, available_cash, liquidity_reserve_min, transaction_fee_rate = (
        _extract_execution_plan_account_context(envelope)
    )
    return build_execution_plan(
        source_run_id=run_id,
        source_allocation_id=allocation_name,
        bucket_targets={bucket: float(weight) for bucket, weight in weights.items()},
        restrictions=_extract_execution_plan_restrictions(envelope),
        catalog=runtime_candidates,
        runtime_candidates=runtime_candidates,
        product_universe_inputs=product_universe_inputs,
        product_universe_result=product_universe_result,
        valuation_inputs=valuation_inputs,
        valuation_result=valuation_result,
        policy_news_signals=policy_news_signals,
        product_proxy_result=product_proxy_result,
        formal_path_required=formal_path_required,
        execution_policy=execution_policy.value,
        account_total_value=account_total_value,
        current_weights=current_weights,
        available_cash=available_cash,
        liquidity_reserve_min=liquidity_reserve_min,
        transaction_fee_rate=transaction_fee_rate,
    )


def _build_solver_candidate_product_contexts(
    *,
    candidate_allocations: list[Any],
    envelope: dict[str, Any],
    snapshot_bundle: Any | None,
    formal_path_required: bool,
    execution_policy: ExecutionPolicy,
) -> dict[str, Any]:
    restrictions = _extract_execution_plan_restrictions(envelope)
    valuation_inputs, valuation_result = _extract_execution_plan_valuation_context(envelope)
    product_universe_inputs, product_universe_result = _extract_execution_plan_product_universe_context(envelope)
    runtime_candidates = _extract_execution_plan_runtime_candidates(envelope)
    product_proxy_result = _extract_execution_plan_product_proxy_context(envelope)
    policy_news_signals = _extract_execution_plan_policy_news_signals(envelope)
    historical_dataset = _extract_market_historical_dataset(envelope, snapshot_bundle)
    contexts: dict[str, Any] = {}
    for allocation in candidate_allocations:
        allocation_payload = _as_dict(allocation)
        allocation_name = _first_text(allocation_payload.get("name")) or ""
        weights = _as_dict(allocation_payload.get("weights"))
        if not allocation_name or not weights:
            continue
        contexts[allocation_name] = build_candidate_product_context(
            source_allocation_id=allocation_name,
            bucket_targets={bucket: float(weight) for bucket, weight in weights.items()},
            restrictions=restrictions,
            runtime_candidates=runtime_candidates,
            product_universe_inputs=product_universe_inputs,
            product_universe_result=product_universe_result,
            valuation_inputs=valuation_inputs,
            valuation_result=valuation_result,
            policy_news_signals=policy_news_signals,
            product_proxy_result=product_proxy_result,
            historical_dataset=historical_dataset,
            formal_path_required=formal_path_required,
            execution_policy=execution_policy.value,
        )
    return contexts


def _build_persistence_plan(
    *,
    run_id: str,
    requested_workflow: WorkflowType | None,
    workflow_type: WorkflowType,
    status: WorkflowStatus,
    bundle_id: str | None,
    calibration_id: str | None,
    solver_snapshot_id: str | None,
    snapshot_bundle: Any,
    calibration_result: Any,
    goal_solver_output: Any,
    runtime_result: Any,
    execution_plan: Any,
    decision_card: Any,
    workflow_decision: WorkflowDecision,
    runtime_restriction: RuntimeRestriction,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
    control_flags: dict[str, Any],
) -> OrchestratorPersistencePlan:
    execution_plan_payload = _payload(execution_plan)
    execution_plan_summary = _build_execution_plan_summary(execution_plan)
    return OrchestratorPersistencePlan(
        run_record={
            "run_id": run_id,
            "requested_workflow_type": None
            if requested_workflow is None
            else requested_workflow.value,
            "workflow_type": workflow_type.value,
            "status": status.value,
            "bundle_id": bundle_id,
            "calibration_id": calibration_id,
            "solver_snapshot_id": solver_snapshot_id,
            "workflow_decision": _payload(workflow_decision),
            "runtime_restriction": _payload(runtime_restriction),
            "blocking_reasons": list(blocking_reasons),
            "degraded_notes": list(degraded_notes),
            "escalation_reasons": list(escalation_reasons),
        },
        artifact_records={
            "snapshot_bundle": None
            if snapshot_bundle is None
            else {"bundle_id": bundle_id, "payload": _payload(snapshot_bundle)},
            "calibration_result": None
            if calibration_result is None
            else {"calibration_id": calibration_id, "payload": _payload(calibration_result)},
            "goal_solver_output": None
            if goal_solver_output is None
            else {"solver_snapshot_id": solver_snapshot_id, "payload": _payload(goal_solver_output)},
            "runtime_result": None
            if runtime_result is None
            else {"run_id": run_id, "payload": _payload(runtime_result)},
            "execution_plan": None
            if execution_plan is None
            else {
                "plan_id": execution_plan_summary.get("plan_id"),
                "plan_version": execution_plan_summary.get("plan_version"),
                "source_run_id": execution_plan_summary.get("source_run_id"),
                "source_allocation_id": execution_plan_summary.get("source_allocation_id"),
                "status": execution_plan_summary.get("status"),
                "approved_at": execution_plan_summary.get("approved_at"),
                "superseded_by_plan_id": execution_plan_summary.get("superseded_by_plan_id"),
                "payload": execution_plan_payload,
            },
            "decision_card": None
            if decision_card is None
            else {
                "run_id": run_id,
                "card_id": _as_dict(decision_card).get("card_id"),
                "payload": _payload(decision_card),
            },
        },
        execution_record={
            "user_executed": None,
            "user_override_requested": bool(control_flags["manual_override_requested"]),
            "override_reason": None,
            "manual_review_requested": bool(control_flags["manual_review_requested"]),
            "plan_id": execution_plan_summary.get("plan_id"),
            "plan_version": execution_plan_summary.get("plan_version"),
            "source_run_id": execution_plan_summary.get("source_run_id"),
            "status": execution_plan_summary.get("status"),
            "approved_at": execution_plan_summary.get("approved_at"),
        },
    )


def run_orchestrator(
    trigger: TriggerSignal | dict[str, Any],
    raw_inputs: dict[str, Any],
    prior_solver_output: Any | None = None,
    prior_solver_input: Any | None = None,
    prior_calibration: Any | None = None,
) -> OrchestratorResult:
    telemetry_started = perf_counter()
    market_enrichment_ms = 0.0
    solver_screen_ms = 0.0
    independent_simulation_ms = 0.0
    explanation_build_ms = 0.0
    history_fetch_ms = 0.0
    universe_build_ms: float | None = None
    valuation_build_ms: float | None = None
    envelope = dict(raw_inputs)
    execution_policy = _execution_policy(envelope)
    formal_path_required = _formal_path_required(envelope)
    snapshot_primary_formal_path = _snapshot_primary_formal_path(envelope)
    if envelope.get("market_raw") is None and not snapshot_primary_formal_path:
        market_enrichment_started = perf_counter()
        envelope["_auto_market_raw_injected"] = True
        envelope["market_raw"] = enrich_market_raw_with_runtime_product_inputs(
            {},
            as_of=str(envelope.get("as_of") or ""),
            formal_path_required=formal_path_required,
            execution_policy=execution_policy.value,
        )
        market_enrichment_ms = (perf_counter() - market_enrichment_started) * 1000.0
    elif isinstance(envelope.get("market_raw"), dict) and not snapshot_primary_formal_path:
        market_enrichment_started = perf_counter()
        envelope["market_raw"] = enrich_market_raw_with_runtime_product_inputs(
            envelope.get("market_raw"),
            as_of=str(envelope.get("as_of") or ""),
            formal_path_required=formal_path_required,
            execution_policy=execution_policy.value,
        )
        market_enrichment_ms = (perf_counter() - market_enrichment_started) * 1000.0
    requested_workflow = _requested_workflow_from_any(trigger)
    normalized_trigger = _trigger_from_any(trigger)
    resolution_blocking_reasons: list[str] = []
    snapshot_bundle, snapshot_bundle_origin = _resolve_snapshot_bundle(
        envelope,
        prior_solver_input,
        resolution_blocking_reasons,
    )
    calibration_result, calibration_origin = _resolve_calibration_result(
        envelope,
        normalized_trigger,
        snapshot_bundle,
        snapshot_bundle_origin,
        prior_calibration,
        prior_solver_input,
    )
    calibration_data = _as_dict(calibration_result)
    control_flags = _extract_control_flags(
        envelope,
        calibration_data,
        normalized_trigger,
    )
    workflow_decision = _select_workflow(
        requested_workflow=requested_workflow,
        trigger=normalized_trigger,
        envelope=envelope,
        prior_solver_output=envelope.get("goal_solver_output") or prior_solver_output,
        prior_solver_input=envelope.get("goal_solver_input") or prior_solver_input,
        control_flags=control_flags,
    )
    effective_trigger = TriggerSignal(
        workflow_type=workflow_decision.selected_workflow_type,
        run_id=normalized_trigger.run_id,
        structural_event=normalized_trigger.structural_event,
        behavior_event=normalized_trigger.behavior_event,
        drawdown_event=normalized_trigger.drawdown_event,
        satellite_event=normalized_trigger.satellite_event,
        manual_review_requested=normalized_trigger.manual_review_requested,
        manual_override_requested=normalized_trigger.manual_override_requested,
        high_risk_request=normalized_trigger.high_risk_request,
        force_full_review=normalized_trigger.force_full_review,
    )
    run_id = _build_run_id(
        normalized_trigger.run_id,
        workflow_decision.selected_workflow_type,
    )
    bundle_id, blocking_reasons, degraded_notes = _evaluate_preflight_controls(
        raw_bundle_id=envelope.get("bundle_id"),
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
    )
    blocking_reasons = list(resolution_blocking_reasons) + blocking_reasons
    if control_flags["enforce_provenance_checks"]:
        _append_bundle_provenance_checks(bundle_id, calibration_data, blocking_reasons)
    else:
        blocking_reasons = _relax_provenance_blocking_reasons(blocking_reasons)
    escalation_reasons: list[str] = []

    goal_solver_output = None
    goal_solver_input_used = envelope.get("goal_solver_input") or prior_solver_input
    runtime_result = None
    probability_engine_result = None
    probability_engine_input = None
    solver_snapshot_id = None
    has_prior_baseline = prior_solver_output is not None and prior_solver_input is not None

    if not blocking_reasons and effective_trigger.workflow_type in {
        WorkflowType.ONBOARDING,
        WorkflowType.QUARTERLY,
    }:
        allocation_input = envelope.get("allocation_engine_input")
        if allocation_input is None:
            blocking_reasons.append("allocation_engine_input is required")
        else:
            allocation_result = run_allocation_engine(allocation_input)
            if not allocation_result.candidate_allocations:
                blocking_reasons.append("allocation_engine returned no candidates")
            else:
                solver_input_source = envelope.get("goal_solver_input")
                if solver_input_source is None:
                    blocking_reasons.append("goal_solver_input is required")
                else:
                    solver_input = _replace_candidate_allocations(
                        _as_dict(solver_input_source),
                        allocation_result.candidate_allocations,
                        bundle_id,
                    )
                    solver_input = _apply_calibration_to_goal_solver_input(
                        solver_input,
                        calibration_data,
                    )
                    solver_input["candidate_product_contexts"] = _build_solver_candidate_product_contexts(
                        candidate_allocations=allocation_result.candidate_allocations,
                        envelope=envelope,
                        snapshot_bundle=snapshot_bundle,
                        formal_path_required=formal_path_required,
                        execution_policy=execution_policy,
                    )
                    candidate_context_blocking, candidate_context_degraded = _collect_formal_path_preflight_issues(
                        solver_input["candidate_product_contexts"],
                        prefix="candidate_product_context",
                    )
                    blocking_reasons.extend(
                        [reason for reason in candidate_context_blocking if reason not in blocking_reasons]
                    )
                    degraded_notes.extend(
                        [reason for reason in candidate_context_degraded if reason not in degraded_notes]
                    )
                    goal_solver_input_used = solver_input
                    if not candidate_context_blocking:
                        try:
                            solver_started = perf_counter()
                            goal_solver_output = run_goal_solver(solver_input)
                            solver_screen_ms = (perf_counter() - solver_started) * 1000.0
                        except ValueError as exc:
                            solver_screen_ms = (perf_counter() - solver_started) * 1000.0
                            blocking_reasons.append(str(exc))
                            goal_solver_output = None
                        if goal_solver_output is not None:
                            goal_solver_output = _enrich_goal_solver_output(
                                goal_solver_output,
                                solver_input,
                            )
                            probability_engine_input, _ = _build_probability_engine_run_input(
                                run_id=run_id,
                                envelope=envelope,
                                calibration_result=calibration_result,
                                goal_solver_input=solver_input,
                                goal_solver_output=goal_solver_output,
                            )
                            if probability_engine_input is not None:
                                probability_engine_result = run_probability_engine(probability_engine_input)
                            solver_snapshot_id = _obj(goal_solver_output).get("input_snapshot_id")
                            recommended_name = _first_text(
                                _as_dict(goal_solver_output).get("recommended_allocation_name"),
                                _as_dict(_as_dict(goal_solver_output).get("recommended_result")).get("allocation_name"),
                            )
                            candidate_contexts = _as_dict(solver_input).get("candidate_product_contexts") or {}
                            recommended_context = _as_dict(candidate_contexts.get(recommended_name)) if recommended_name else {}
                            coverage = _as_dict(
                                _as_dict(recommended_context.get("product_simulation_input")).get("coverage_summary")
                            )
                            independent_simulation_ms = (
                                solver_screen_ms
                                if float(coverage.get("independent_weight_adjusted_coverage") or 0.0) > 0.0
                                else 0.0
                            )
                    if effective_trigger.workflow_type == WorkflowType.QUARTERLY:
                        runtime_inputs, missing_runtime_inputs = _resolve_runtime_inputs(
                            envelope,
                            calibration_data,
                        )
                        if missing_runtime_inputs:
                            blocking_reasons.append(
                                "missing runtime inputs: " + ", ".join(missing_runtime_inputs)
                            )
                        elif goal_solver_output is None:
                            blocking_reasons.append("goal solver baseline unavailable for runtime optimization")
                        else:
                            runtime_result = run_runtime_optimizer(
                                solver_output=goal_solver_output,
                                solver_baseline_inp=solver_input,
                                live_portfolio=runtime_inputs["live_portfolio"],
                                market_state=runtime_inputs["market_state"],
                                behavior_state=runtime_inputs["behavior_state"],
                                constraint_state=runtime_inputs["constraint_state"],
                                ev_params=runtime_inputs["ev_params"],
                                optimizer_params=runtime_inputs["optimizer_params"],
                                mode=RuntimeOptimizerMode.QUARTERLY,
                            )

    if not blocking_reasons and effective_trigger.workflow_type in {
        WorkflowType.MONTHLY,
        WorkflowType.EVENT,
    }:
        goal_solver_output = envelope.get("goal_solver_output") or prior_solver_output
        solver_input = envelope.get("goal_solver_input") or prior_solver_input
        goal_solver_input_used = solver_input
        if goal_solver_output is None or solver_input is None:
            blocking_reasons.append("prior solver baseline is required")
        else:
            _validate_solver_baseline_pair(goal_solver_output, solver_input, blocking_reasons)
            if not blocking_reasons:
                runtime_inputs, missing_runtime_inputs = _resolve_runtime_inputs(
                    envelope,
                    calibration_data,
                )
                if missing_runtime_inputs:
                    blocking_reasons.append(
                        "missing runtime inputs: " + ", ".join(missing_runtime_inputs)
                    )
                else:
                    solver_snapshot_id = _obj(goal_solver_output).get("input_snapshot_id")
                    runtime_result = run_runtime_optimizer(
                        solver_output=goal_solver_output,
                        solver_baseline_inp=solver_input,
                        live_portfolio=runtime_inputs["live_portfolio"],
                        market_state=runtime_inputs["market_state"],
                        behavior_state=runtime_inputs["behavior_state"],
                        constraint_state=runtime_inputs["constraint_state"],
                        ev_params=runtime_inputs["ev_params"],
                        optimizer_params=runtime_inputs["optimizer_params"],
                        mode=(
                            RuntimeOptimizerMode.EVENT
                            if effective_trigger.workflow_type == WorkflowType.EVENT
                            else RuntimeOptimizerMode.MONTHLY
                        ),
                        structural_event=effective_trigger.structural_event,
                        behavior_event=effective_trigger.behavior_event,
                        drawdown_event=effective_trigger.drawdown_event,
                        satellite_event=effective_trigger.satellite_event,
                    )

    _apply_runtime_controls(
        trigger=effective_trigger,
        runtime_result=runtime_result,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    runtime_restriction, runtime_result = _build_runtime_restriction(
        trigger=effective_trigger,
        workflow_type=effective_trigger.workflow_type,
        control_flags=control_flags,
        runtime_result=runtime_result,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    control_directives = _control_directives_from_runtime_restriction(runtime_restriction)
    blocking_reasons = _unique_items(blocking_reasons)
    degraded_notes = _unique_items(degraded_notes)
    escalation_reasons = _unique_items(escalation_reasons)
    control_directives = _unique_items(control_directives)

    status = _status_from_flags(
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    execution_plan = _maybe_build_execution_plan(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        goal_solver_output=goal_solver_output,
        envelope=envelope,
        formal_path_required=formal_path_required,
        execution_policy=execution_policy,
    )
    if execution_plan is not None:
        execution_plan_preflight = _as_dict(_as_dict(execution_plan).get("formal_path_preflight"))
        if _text(execution_plan_preflight.get("run_outcome_status")) == "blocked":
            for predicate in list(execution_plan_preflight.get("blocking_predicates") or []) or [
                "execution_plan_formal_path_blocked"
            ]:
                if predicate not in blocking_reasons:
                    blocking_reasons.append(str(predicate))
        elif _text(execution_plan_preflight.get("run_outcome_status")) == "degraded":
            for reason in list(execution_plan_preflight.get("degradation_reasons") or []) or [
                "execution_plan_formal_path_degraded"
            ]:
                if reason not in degraded_notes:
                    degraded_notes.append(str(reason))
    blocking_reasons = _unique_items(blocking_reasons)
    degraded_notes = _unique_items(degraded_notes)
    status = _status_from_flags(
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    # Plan guidance from frontdesk context
    plan_context = _as_dict(envelope.get("frontdesk_execution_plan_context"))
    if effective_trigger.workflow_type == WorkflowType.QUARTERLY and execution_plan is not None:
        compare = _compare_execution_plan_payloads(
            _as_dict(plan_context.get("active")),
            _as_dict(_payload(execution_plan)),
        )
        if compare:
            control_directives.append(f"plan_change={compare.get('recommendation')}")
            control_directives.append(f"plan_change_level={compare.get('change_level')}")
    elif effective_trigger.workflow_type == WorkflowType.MONTHLY:
        comparison = _as_dict(plan_context.get("comparison"))
        recommendation = _first_text(comparison.get("recommendation"))
        if recommendation:
            control_directives.append(f"plan_change={recommendation}")
            change_level = _first_text(comparison.get("change_level"))
            if change_level:
                control_directives.append(f"plan_change_level={change_level}")
    control_directives = _unique_items(control_directives)

    # Prefer pending plan summary (if present) when monthly has no new plan
    execution_plan_summary = _build_execution_plan_summary(execution_plan)
    if (
        not execution_plan_summary
        and effective_trigger.workflow_type == WorkflowType.MONTHLY
        and plan_context.get("pending")
    ):
        execution_plan_summary = _build_execution_plan_summary(plan_context.get("pending"))
    runtime_market = _as_dict(envelope.get("market_raw"))
    product_universe_result = _as_dict(
        runtime_market.get("product_universe_result") or runtime_market.get("runtime_product_universe_result")
    )
    valuation_result = _as_dict(runtime_market.get("product_valuation_result") or runtime_market.get("valuation_result"))
    historical_dataset = _as_dict(runtime_market.get("historical_dataset"))
    if universe_build_ms is None:
        if snapshot_primary_formal_path and product_universe_result:
            universe_build_ms = 0.0
        elif product_universe_result:
            universe_build_ms = market_enrichment_ms
    if valuation_build_ms is None:
        if snapshot_primary_formal_path and valuation_result:
            valuation_build_ms = 0.0
        elif valuation_result:
            valuation_build_ms = market_enrichment_ms
    if historical_dataset:
        history_fetch_ms = 0.0 if snapshot_primary_formal_path else market_enrichment_ms
    gate1_input_provenance = _build_input_provenance(
        envelope,
        effective_trigger.workflow_type,
        has_prior_baseline=has_prior_baseline,
    )
    gate1_formal_evidence_degradation_reasons = _gate1_formal_evidence_degradation_reasons(
        input_provenance=gate1_input_provenance,
        snapshot_primary_formal_path=snapshot_primary_formal_path,
        snapshot_bundle=snapshot_bundle,
        market_raw=envelope.get("market_raw"),
    )
    gate1_simulation_mode_degradation_reasons = _gate1_simulation_mode_degradation_reasons(
        calibration_result=calibration_result,
        execution_policy=execution_policy,
        probability_engine_result=probability_engine_result,
    )
    gate1_degraded_notes = _unique_items(degraded_notes + gate1_formal_evidence_degradation_reasons)
    gate1_degraded_notes = _unique_items(gate1_degraded_notes + gate1_simulation_mode_degradation_reasons)
    gate1_run_outcome_status = _gate1_run_outcome_status(
        status=status,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
        formal_evidence_degradation_reasons=(
            gate1_formal_evidence_degradation_reasons + gate1_simulation_mode_degradation_reasons
        ),
    )
    gate1_coverage_summary = _gate1_coverage_summary(goal_solver_output)
    candidate_context_failure_artifacts = _collect_failure_artifacts(
        _as_dict(goal_solver_input_used).get("candidate_product_contexts") or {}
    )
    execution_plan_failure_artifacts = (
        []
        if execution_plan is None
        else [artifact for artifact in [FailureArtifact.from_any(_as_dict(execution_plan).get("failure_artifact"))] if artifact is not None]
    )
    market_raw_failure_artifacts = (
        []
        if not isinstance(envelope.get("market_raw"), dict)
        else [
            artifact
            for artifact in (
                FailureArtifact.from_any(_as_dict(envelope["market_raw"]).get("product_universe_failure_artifact")),
                FailureArtifact.from_any(_as_dict(envelope["market_raw"]).get("product_valuation_failure_artifact")),
            )
            if artifact is not None
        ]
    )
    primary_failure_artifact = _primary_failure_artifact(
        candidate_context_failure_artifacts,
        execution_plan_failure_artifacts,
        market_raw_failure_artifacts,
    )
    gate1_resolved_result_category = _gate1_resolved_result_category(
        run_outcome_status=gate1_run_outcome_status,
        goal_solver_output=goal_solver_output,
        coverage_summary=gate1_coverage_summary,
    )
    gate1_disclosure_decision = _gate1_disclosure_decision(
        resolved_result_category=gate1_resolved_result_category,
        run_outcome_status=gate1_run_outcome_status,
        coverage_summary=gate1_coverage_summary,
        calibration_result=calibration_result,
        degraded_notes=gate1_degraded_notes,
        blocking_reasons=blocking_reasons,
        formal_evidence_degradation_reasons=(
            gate1_formal_evidence_degradation_reasons + gate1_simulation_mode_degradation_reasons
        ),
    )
    gate1_evidence_bundle = _gate1_evidence_bundle(
        run_id=run_id,
        bundle_id=bundle_id,
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_input=goal_solver_input_used,
        goal_solver_output=goal_solver_output,
        calibration_result=calibration_result,
        run_outcome_status=gate1_run_outcome_status,
        resolved_result_category=gate1_resolved_result_category,
        coverage_summary=gate1_coverage_summary,
        disclosure_decision=gate1_disclosure_decision,
        execution_policy=execution_policy,
        failure_artifact=primary_failure_artifact,
        blocking_reasons=blocking_reasons,
        degraded_notes=gate1_degraded_notes,
        snapshot_bundle=snapshot_bundle,
        runtime_result=runtime_result,
        probability_engine_result=probability_engine_result,
    )
    baseline_evidence_bundle = raw_inputs.get("evidence_invariance_baseline") or raw_inputs.get("baseline_evidence_bundle")
    evidence_invariance_report = (
        {}
        if baseline_evidence_bundle in (None, {})
        else build_evidence_invariance_report(
            baseline=baseline_evidence_bundle,
            optimized=gate1_evidence_bundle,
            baseline_run_ref=str(_as_dict(baseline_evidence_bundle).get("request_id") or "baseline"),
            optimized_run_ref=run_id,
            artifact_refs={
                "bundle_id": str(bundle_id or ""),
                "snapshot_bundle_origin": snapshot_bundle_origin,
                "calibration_origin": calibration_origin,
            },
        ).to_dict()
    )
    bridged_probability_surface = _bridged_probability_surface(
        probability_engine_result=probability_engine_result,
        run_outcome_status=gate1_run_outcome_status.value,
        resolved_result_category=gate1_resolved_result_category,
        disclosure_decision=gate1_disclosure_decision.to_dict(),
        evidence_bundle=gate1_evidence_bundle.to_dict(),
    )
    canonical_run_outcome_status = (
        bridged_probability_surface["run_outcome_status"]
        if "run_outcome_status" in bridged_probability_surface
        else gate1_run_outcome_status.value
    )
    canonical_resolved_result_category = (
        bridged_probability_surface["resolved_result_category"]
        if "resolved_result_category" in bridged_probability_surface
        else gate1_resolved_result_category
    )
    canonical_disclosure_decision = dict(
        bridged_probability_surface["disclosure_decision"]
        if "disclosure_decision" in bridged_probability_surface
        else gate1_disclosure_decision.to_dict()
    )
    canonical_evidence_bundle = dict(
        bridged_probability_surface["evidence_bundle"]
        if "evidence_bundle" in bridged_probability_surface
        else gate1_evidence_bundle.to_dict()
    )
    canonical_probability_truth_view = _probability_truth_view(
        probability_engine_result=probability_engine_result,
        run_outcome_status=canonical_run_outcome_status,
        resolved_result_category=canonical_resolved_result_category,
        disclosure_decision=canonical_disclosure_decision,
        evidence_bundle=canonical_evidence_bundle,
    )
    card_build_input = _build_card_input(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        goal_solver_input=goal_solver_input_used,
        runtime_result=runtime_result,
        probability_engine_result=probability_engine_result,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        execution_plan_summary=execution_plan_summary,
        audit_record=None,
        run_outcome_status=canonical_run_outcome_status,
        resolved_result_category=canonical_resolved_result_category,
        probability_truth_view=canonical_probability_truth_view,
        disclosure_decision=canonical_disclosure_decision,
        evidence_bundle=canonical_evidence_bundle,
        input_provenance=gate1_input_provenance,
        blocking_reasons=blocking_reasons,
        degraded_notes=gate1_degraded_notes,
        escalation_reasons=escalation_reasons,
        control_directives=control_directives,
    )
    audit_record = _build_audit_record(
        workflow_decision=workflow_decision,
        trigger=effective_trigger,
        control_flags=control_flags,
        runtime_restriction=runtime_restriction,
        run_id=run_id,
        bundle_id=bundle_id,
        snapshot_bundle=snapshot_bundle,
        snapshot_bundle_origin=snapshot_bundle_origin,
        calibration_result=calibration_result,
        calibration_origin=calibration_origin,
        calibration_data=calibration_data,
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        card_build_input=card_build_input,
        status=status,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    card_build_input.audit_record = audit_record
    audit_record.artifact_refs["has_execution_plan"] = execution_plan is not None
    audit_record.artifact_refs["has_evidence_invariance_report"] = bool(evidence_invariance_report)
    explanation_started = perf_counter()
    decision_card = build_decision_card(card_build_input)
    explanation_build_ms = (perf_counter() - explanation_started) * 1000.0
    audit_record.artifact_refs["has_decision_card"] = decision_card is not None
    persistence_plan = _build_persistence_plan(
        run_id=run_id,
        requested_workflow=requested_workflow,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        execution_plan=execution_plan,
        decision_card=decision_card,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
        control_flags=control_flags,
    )
    audit_record.artifact_refs["has_persistence_plan"] = persistence_plan is not None
    runtime_telemetry = {
        "universe_build_ms": None if universe_build_ms is None else round(float(universe_build_ms), 3),
        "valuation_build_ms": None if valuation_build_ms is None else round(float(valuation_build_ms), 3),
        "history_fetch_ms": round(float(history_fetch_ms), 3),
        "solver_screen_ms": round(float(solver_screen_ms), 3),
        "independent_simulation_ms": round(float(independent_simulation_ms), 3),
        "explanation_build_ms": round(float(explanation_build_ms), 3),
        "total_orchestrator_ms": round((perf_counter() - telemetry_started) * 1000.0, 3),
    }
    runtime_telemetry.update(
        _probability_runtime_telemetry(
            probability_engine_input=probability_engine_input,
            probability_engine_result=probability_engine_result,
        )
    )
    audit_record.artifact_refs["has_runtime_telemetry"] = True
    audit_record.artifact_refs["runtime_telemetry"] = runtime_telemetry
    return OrchestratorResult(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        run_outcome_status=canonical_run_outcome_status,
        resolved_result_category=canonical_resolved_result_category,
        probability_truth_view=canonical_probability_truth_view,
        disclosure_decision=canonical_disclosure_decision,
        evidence_bundle=canonical_evidence_bundle,
        evidence_invariance_report=evidence_invariance_report,
        runtime_telemetry=runtime_telemetry,
        requested_workflow_type=requested_workflow,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        probability_engine_result=probability_engine_result,
        execution_plan=execution_plan,
        card_build_input=card_build_input,
        decision_card=decision_card,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        audit_record=audit_record,
        persistence_plan=persistence_plan,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
