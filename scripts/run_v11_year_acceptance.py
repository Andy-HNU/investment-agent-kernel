from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from frontdesk.service import (
    approve_frontdesk_execution_plan,
    load_frontdesk_snapshot,
    record_frontdesk_execution_feedback,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from shared.onboarding import UserOnboardingProfile


def _base_profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="v11_year_user",
        display_name="Andy",
        current_total_assets=120_000.0,
        monthly_contribution=6_000.0,
        goal_amount=450_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="55%沪深300 25%债券 15%黄金 5%卫星",
        restrictions=[],
        current_weights={
            "equity_cn": 0.55,
            "bond_cn": 0.25,
            "gold": 0.15,
            "satellite": 0.05,
        },
    )


def _provider_config() -> dict[str, Any]:
    return {
        "adapter": "inline_snapshot",
        "provider_name": "year_acceptance_inline_history",
        "as_of": "2026-01-05T00:00:00Z",
        "fetched_at": "2026-01-05T00:05:00Z",
        "payload": {
            "market_raw": {
                "raw_volatility": {
                    "equity_cn": 0.18,
                    "bond_cn": 0.04,
                    "gold": 0.11,
                    "satellite": 0.21,
                },
                "liquidity_scores": {
                    "equity_cn": 0.90,
                    "bond_cn": 0.96,
                    "gold": 0.84,
                    "satellite": 0.62,
                },
                "valuation_z_scores": {
                    "equity_cn": -0.1,
                    "bond_cn": 0.0,
                    "gold": -0.2,
                    "satellite": 1.1,
                },
                "expected_returns": {
                    "equity_cn": 0.09,
                    "bond_cn": 0.032,
                    "gold": 0.045,
                    "satellite": 0.11,
                },
                "historical_return_panel": {
                    "dataset_id": "year_acceptance_panel",
                    "version_id": "year_acceptance_panel:v1",
                    "as_of": "2026-01-05",
                    "source_name": "year_acceptance_fixture",
                    "lookback_months": 36,
                    "return_series": {
                        "equity_cn": [0.012, 0.021, -0.015, 0.029, 0.008, 0.018],
                        "bond_cn": [0.002, 0.003, 0.001, 0.004, 0.002, 0.003],
                        "gold": [0.006, -0.002, 0.004, 0.003, 0.005, -0.001],
                        "satellite": [0.015, 0.028, -0.021, 0.032, 0.012, 0.026],
                    },
                    "notes": ["v1.1 yearly acceptance historical panel"],
                },
                "regime_feature_snapshot": {
                    "snapshot_id": "year_acceptance_regime",
                    "as_of": "2026-01-05T00:00:00Z",
                    "feature_values": {
                        "inflation": 0.58,
                        "growth": 0.46,
                        "liquidity": 0.39,
                    },
                    "inferred_regime": "neutral_tightening",
                    "notes": ["year acceptance regime proxy"],
                },
                "jump_event_history": {
                    "history_id": "year_acceptance_jump_history",
                    "as_of": "2026-01-05T00:00:00Z",
                    "events": [
                        {
                            "event_id": "year-evt-1",
                            "bucket": "equity_cn",
                            "event_type": "policy_shock",
                            "magnitude": -0.07,
                            "event_date": "2025-09-15",
                        }
                    ],
                    "notes": ["year acceptance jump history"],
                },
                "bucket_proxy_mapping": {
                    "mapping_id": "year_acceptance_proxy",
                    "as_of": "2026-01-05T00:00:00Z",
                    "bucket_to_proxy": {
                        "equity_cn": "000300.SH",
                        "bond_cn": "CBA00001.CS",
                        "gold": "AU9999.SGE",
                        "satellite": "399006.SZ",
                    },
                    "notes": ["year acceptance proxies"],
                },
            }
        },
    }


def _profile_patch(profile: UserOnboardingProfile, **updates: Any) -> dict[str, Any]:
    patched = deepcopy(profile.to_dict())
    patched.update(deepcopy(updates))
    return patched


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    comparison = dict(payload.get("execution_plan_comparison") or {})
    return {
        "status": payload.get("status"),
        "workflow_type": payload.get("workflow_type"),
        "run_id": payload.get("run_id"),
        "simulation_mode_used": payload.get("simulation_mode_used"),
        "implied_required_annual_return": payload.get("implied_required_annual_return"),
        "external_snapshot_status": payload.get("external_snapshot_status"),
        "refresh_summary": {
            "provider_name": ((payload.get("refresh_summary") or {}).get("provider_name")),
            "freshness_state": ((payload.get("refresh_summary") or {}).get("freshness_state")),
        },
        "execution_plan_comparison": {
            "recommendation": comparison.get("recommendation"),
            "change_level": comparison.get("change_level"),
            "max_weight_delta": comparison.get("max_weight_delta"),
            "changed_bucket_count": comparison.get("changed_bucket_count"),
            "product_switch_count": comparison.get("product_switch_count"),
        },
        "key_metrics": deepcopy(payload.get("key_metrics") or {}),
    }


def _approve_pending(account_profile_id: str, payload: dict[str, Any], *, db_path: Path, approved_at: str) -> dict[str, Any]:
    pending = dict(payload.get("pending_execution_plan") or {})
    if not pending:
        return {"status": "skipped", "reason": "no_pending_plan"}
    return approve_frontdesk_execution_plan(
        account_profile_id=account_profile_id,
        plan_id=str(pending["plan_id"]),
        plan_version=int(pending["plan_version"]),
        approved_at=approved_at,
        db_path=db_path,
    )


def _record_feedback(
    account_profile_id: str,
    payload: dict[str, Any],
    *,
    db_path: Path,
    user_executed: bool,
    actual_action: str,
    note: str,
    executed_at: str,
) -> dict[str, Any]:
    return record_frontdesk_execution_feedback(
        account_profile_id=account_profile_id,
        source_run_id=str(payload["run_id"]),
        db_path=db_path,
        user_executed=user_executed,
        actual_action=actual_action,
        executed_at=executed_at,
        note=note,
    )


def run_year_acceptance(*, db_path: Path) -> dict[str, Any]:
    profile = _base_profile()
    account_profile_id = profile.account_profile_id
    results: dict[str, Any] = {}

    onboarding = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        as_of="2026-01-05T00:00:00Z",
        external_data_config=_provider_config(),
    )
    results["onboarding"] = onboarding

    approve_initial = _approve_pending(
        account_profile_id,
        onboarding,
        db_path=db_path,
        approved_at="2026-01-05T01:00:00Z",
    )
    results["approve_initial"] = approve_initial

    feedback_initial = _record_feedback(
        account_profile_id,
        onboarding,
        db_path=db_path,
        user_executed=True,
        actual_action="adopt_recommended_plan",
        note="初始方案已确认执行",
        executed_at="2026-01-05T01:10:00Z",
    )
    results["feedback_initial"] = feedback_initial

    month_1 = run_frontdesk_followup(
        account_profile_id=account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        as_of="2026-02-05T00:00:00Z",
        allow_historical_replay=True,
        profile=_profile_patch(
            profile,
            current_total_assets=126_000.0,
            current_holdings="58%沪深300 22%债券 15%黄金 5%卫星",
            current_weights={
                "equity_cn": 0.58,
                "bond_cn": 0.22,
                "gold": 0.15,
                "satellite": 0.05,
            },
        ),
    )
    results["month_1"] = month_1

    quarter_1 = run_frontdesk_followup(
        account_profile_id=account_profile_id,
        workflow_type="quarterly",
        db_path=db_path,
        as_of="2026-04-05T00:00:00Z",
        allow_historical_replay=True,
    )
    results["quarter_1"] = quarter_1

    feedback_q1 = _record_feedback(
        account_profile_id,
        quarter_1,
        db_path=db_path,
        user_executed=False,
        actual_action="observe",
        note="季度复盘先观察",
        executed_at="2026-04-05T08:00:00Z",
    )
    results["feedback_q1"] = feedback_q1

    event_drawdown = run_frontdesk_followup(
        account_profile_id=account_profile_id,
        workflow_type="event",
        db_path=db_path,
        as_of="2026-07-05T00:00:00Z",
        allow_historical_replay=True,
        event_request=True,
        event_context={
            "requested_action": "rebalance_full",
            "manual_review_requested": True,
            "high_risk_request": True,
        },
        profile=_profile_patch(
            profile,
            current_total_assets=112_000.0,
            current_holdings="70%沪深300 15%债券 10%黄金 5%卫星",
            current_weights={
                "equity_cn": 0.70,
                "bond_cn": 0.15,
                "gold": 0.10,
                "satellite": 0.05,
            },
        ),
    )
    results["event_drawdown"] = event_drawdown

    feedback_event = _record_feedback(
        account_profile_id,
        event_drawdown,
        db_path=db_path,
        user_executed=False,
        actual_action="freeze",
        note="回撤事件下先冻结，等待复核",
        executed_at="2026-07-05T08:30:00Z",
    )
    results["feedback_event"] = feedback_event

    quarter_2_restrict = run_frontdesk_followup(
        account_profile_id=account_profile_id,
        workflow_type="quarterly",
        db_path=db_path,
        as_of="2026-10-05T00:00:00Z",
        allow_historical_replay=True,
        profile=_profile_patch(
            profile,
            current_total_assets=158_000.0,
            current_holdings="70%债券 30%黄金",
            restrictions=["不碰股票"],
            current_weights={
                "bond_cn": 0.70,
                "gold": 0.30,
            },
        ),
    )
    results["quarter_2_restrict"] = quarter_2_restrict

    approve_restrict = _approve_pending(
        account_profile_id,
        quarter_2_restrict,
        db_path=db_path,
        approved_at="2026-10-05T01:00:00Z",
    )
    results["approve_restrict"] = approve_restrict

    feedback_restrict = _record_feedback(
        account_profile_id,
        quarter_2_restrict,
        db_path=db_path,
        user_executed=True,
        actual_action="replace_active",
        note="按新限制替换 active plan",
        executed_at="2026-10-05T01:20:00Z",
    )
    results["feedback_restrict"] = feedback_restrict

    month_12 = run_frontdesk_followup(
        account_profile_id=account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        as_of="2027-01-05T00:00:00Z",
        allow_historical_replay=True,
        profile=_profile_patch(
            profile,
            current_total_assets=182_000.0,
            current_holdings="75%债券 25%黄金",
            restrictions=["不碰股票"],
            current_weights={
                "bond_cn": 0.75,
                "gold": 0.25,
            },
        ),
    )
    results["month_12"] = month_12

    snapshot_final = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    results["snapshot_final"] = snapshot_final

    return {
        "summary": {name: _summarize(payload) for name, payload in results.items()},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v1.1 yearly frontdesk acceptance flow.")
    parser.add_argument(
        "--db",
        default="handoff/logs/v11_year_acceptance.sqlite",
        help="SQLite path for acceptance run",
    )
    parser.add_argument(
        "--output",
        default="handoff/logs/v11_year_acceptance_2026-04-03.json",
        help="JSON report path",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    output_path = Path(args.output)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    report = run_year_acceptance(db_path=db_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"output_path={output_path}")
    print(f"db_path={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
