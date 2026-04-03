#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from frontdesk.service import _attach_real_source_market_history
from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from snapshot_ingestion.real_source_market import build_real_source_market_snapshot


def _anchor_iso(anchor_date: str) -> str:
    rendered = anchor_date.strip()
    if len(rendered) == 10:
        return f"{rendered}T00:00:00Z"
    return rendered


def _parse_date(value: str) -> date:
    rendered = value.strip()
    if rendered.endswith("Z"):
        rendered = rendered[:-1]
    return datetime.fromisoformat(rendered[:10]).date()


def _add_months(base: date, months: int) -> date:
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = min(
        base.day,
        [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
    )
    return date(year, month, day)


def _serialize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return dict(result)


def _slice_future_returns(
    dataset_payload: dict[str, Any],
    *,
    start_exclusive: date,
    end_inclusive: date,
) -> tuple[list[str], dict[str, list[float]]]:
    series_dates = [str(item) for item in list(dataset_payload.get("series_dates") or [])]
    if not series_dates:
        return [], {}
    selected_indexes = [
        idx
        for idx, item in enumerate(series_dates)
        if start_exclusive < _parse_date(item) <= end_inclusive
    ]
    if not selected_indexes:
        return [], {}
    sliced_dates = [series_dates[idx] for idx in selected_indexes]
    sliced_returns = {
        str(bucket): [float(list(series or [])[idx]) for idx in selected_indexes]
        for bucket, series in dict(dataset_payload.get("return_series") or {}).items()
    }
    return sliced_dates, sliced_returns


def _normalize_weights(weights: dict[str, Any]) -> dict[str, float]:
    normalized = {str(bucket): float(value or 0.0) for bucket, value in dict(weights or {}).items()}
    total = sum(max(value, 0.0) for value in normalized.values())
    if total <= 0.0:
        return normalized
    return {bucket: max(value, 0.0) / total for bucket, value in normalized.items()}


def _replay_realized_terminal_value(
    *,
    initial_assets: float,
    monthly_contribution: float,
    weights: dict[str, float],
    series_dates: list[str],
    return_series: dict[str, list[float]],
    anchor: date,
) -> float:
    normalized_weights = _normalize_weights(weights)
    terminal_value = float(initial_assets)
    current_period = (anchor.year, anchor.month)
    for idx, rendered_date in enumerate(series_dates):
        as_of = _parse_date(rendered_date)
        next_period = (as_of.year, as_of.month)
        if next_period != current_period:
            terminal_value += float(monthly_contribution)
            current_period = next_period
        daily_return = 0.0
        for bucket, weight in normalized_weights.items():
            bucket_returns = list(return_series.get(bucket) or [])
            if idx < len(bucket_returns):
                daily_return += weight * float(bucket_returns[idx])
        terminal_value *= 1.0 + daily_return
    return terminal_value


def run_anchor_validation(
    *,
    anchor_date: str,
    horizon_months: int,
    current_total_assets: float = 50_000.0,
    monthly_contribution: float = 5_000.0,
    goal_amount: float = 200_000.0,
    risk_preference: str = "中等",
    max_drawdown_tolerance: float = 0.1,
    current_holdings: str = "60%沪深300 25%债券 15%黄金",
    restrictions: list[str] | None = None,
) -> dict[str, Any]:
    restrictions = list(restrictions or ["不买股票"])
    anchor_iso = _anchor_iso(anchor_date)
    anchor_dt = _parse_date(anchor_iso)
    horizon_end = _add_months(anchor_dt, int(horizon_months))

    profile = UserOnboardingProfile(
        account_profile_id=f"forward_validation_{anchor_dt.isoformat()}",
        display_name="ForwardValidation",
        current_total_assets=float(current_total_assets),
        monthly_contribution=float(monthly_contribution),
        goal_amount=float(goal_amount),
        goal_horizon_months=int(horizon_months),
        risk_preference=risk_preference,
        max_drawdown_tolerance=float(max_drawdown_tolerance),
        current_holdings=current_holdings,
        restrictions=restrictions,
    )

    onboarding = build_user_onboarding_inputs(profile, as_of=anchor_iso)
    raw_inputs = deepcopy(onboarding.raw_inputs)
    input_provenance = deepcopy(onboarding.input_provenance)
    raw_inputs["as_of"] = anchor_iso
    raw_inputs, input_provenance = _attach_real_source_market_history(
        raw_inputs=raw_inputs,
        input_provenance=input_provenance,
    )
    result = _serialize_result(
        run_orchestrator(
            trigger={
                "workflow_type": "onboarding",
                "run_id": f"forward_validation_{anchor_dt.strftime('%Y%m%d')}",
            },
            raw_inputs=raw_inputs,
        )
    )
    goal_output = dict(result.get("goal_solver_output") or {})
    recommended = dict(goal_output.get("recommended_result") or {})
    weights = dict(recommended.get("weights") or {})

    future_snapshot = build_real_source_market_snapshot(as_of=f"{horizon_end.isoformat()}T00:00:00Z")
    future_dataset = dict(future_snapshot.historical_dataset_metadata or {})
    future_dates, future_returns = _slice_future_returns(
        future_dataset,
        start_exclusive=anchor_dt,
        end_inclusive=horizon_end,
    )
    if not future_dates:
        raise RuntimeError("forward validation future window returned no real-source observations")

    realized_terminal_value = _replay_realized_terminal_value(
        initial_assets=float(current_total_assets),
        monthly_contribution=float(monthly_contribution),
        weights=weights,
        series_dates=future_dates,
        return_series=future_returns,
        anchor=anchor_dt,
    )
    goal_achieved = bool(realized_terminal_value >= float(goal_amount))
    predicted_success_probability = float(recommended.get("success_probability") or 0.0)
    predicted_product_adjusted_probability = float(
        recommended.get("product_adjusted_success_probability", predicted_success_probability) or 0.0
    )
    outcome = 1.0 if goal_achieved else 0.0

    return {
        "anchor_date": anchor_dt.isoformat(),
        "horizon_months": int(horizon_months),
        "goal_amount": float(goal_amount),
        "simulation_mode_used": goal_output.get("simulation_mode_used"),
        "predicted_success_probability": predicted_success_probability,
        "predicted_product_adjusted_success_probability": predicted_product_adjusted_probability,
        "realized_terminal_value": realized_terminal_value,
        "goal_achieved": goal_achieved,
        "future_observed_days": len(future_dates),
        "historical_dataset_version": dict(raw_inputs.get("historical_dataset_metadata") or {}).get("version_id"),
        "future_dataset_version": future_dataset.get("version_id"),
        "recommended_allocation_name": recommended.get("allocation_name"),
        "brier_score_bucket": (predicted_success_probability - outcome) ** 2,
        "brier_score_product_adjusted": (predicted_product_adjusted_probability - outcome) ** 2,
    }


def run_rolling_validation(
    *,
    anchor_dates: list[str],
    horizon_months: int,
    current_total_assets: float = 50_000.0,
    monthly_contribution: float = 5_000.0,
    goal_amount: float = 200_000.0,
    risk_preference: str = "中等",
    max_drawdown_tolerance: float = 0.1,
    current_holdings: str = "60%沪深300 25%债券 15%黄金",
    restrictions: list[str] | None = None,
) -> dict[str, Any]:
    anchor_results = [
        run_anchor_validation(
            anchor_date=anchor_date,
            horizon_months=horizon_months,
            current_total_assets=current_total_assets,
            monthly_contribution=monthly_contribution,
            goal_amount=goal_amount,
            risk_preference=risk_preference,
            max_drawdown_tolerance=max_drawdown_tolerance,
            current_holdings=current_holdings,
            restrictions=restrictions,
        )
        for anchor_date in anchor_dates
    ]
    if not anchor_results:
        return {
            "anchor_count": 0,
            "hit_rate": 0.0,
            "avg_predicted_success_probability": 0.0,
            "avg_product_adjusted_success_probability": 0.0,
            "avg_brier_score_bucket": 0.0,
            "avg_brier_score_product_adjusted": 0.0,
            "results": [],
        }
    count = float(len(anchor_results))
    hit_rate = sum(1.0 for item in anchor_results if bool(item.get("goal_achieved"))) / count
    avg_predicted = sum(float(item.get("predicted_success_probability") or 0.0) for item in anchor_results) / count
    avg_product = sum(
        float(item.get("predicted_product_adjusted_success_probability") or 0.0)
        for item in anchor_results
    ) / count
    avg_brier = sum(float(item.get("brier_score_bucket") or 0.0) for item in anchor_results) / count
    avg_brier_product = sum(
        float(item.get("brier_score_product_adjusted") or 0.0)
        for item in anchor_results
    ) / count
    return {
        "anchor_count": int(count),
        "hit_rate": hit_rate,
        "avg_predicted_success_probability": avg_predicted,
        "avg_product_adjusted_success_probability": avg_product,
        "avg_brier_score_bucket": avg_brier,
        "avg_brier_score_product_adjusted": avg_brier_product,
        "results": anchor_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v1.2 forward validation against real-source history")
    parser.add_argument("--anchor-date", default="2021-01-01")
    parser.add_argument("--anchor-dates", default="")
    parser.add_argument("--horizon-months", type=int, default=60)
    parser.add_argument("--goal-amount", type=float, default=200000.0)
    parser.add_argument("--current-total-assets", type=float, default=50000.0)
    parser.add_argument("--monthly-contribution", type=float, default=5000.0)
    args = parser.parse_args(argv)
    anchor_dates = [item.strip() for item in str(args.anchor_dates or "").split(",") if item.strip()]
    if anchor_dates:
        result = run_rolling_validation(
            anchor_dates=anchor_dates,
            horizon_months=args.horizon_months,
            current_total_assets=args.current_total_assets,
            monthly_contribution=args.monthly_contribution,
            goal_amount=args.goal_amount,
        )
    else:
        result = run_anchor_validation(
            anchor_date=args.anchor_date,
            horizon_months=args.horizon_months,
            current_total_assets=args.current_total_assets,
            monthly_contribution=args.monthly_contribution,
            goal_amount=args.goal_amount,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
