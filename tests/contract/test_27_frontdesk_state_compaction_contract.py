from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "frontdesk_compaction_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金12000，黄金6000",
        restrictions=["不买个股", "不碰科技", "不碰高风险产品"],
    )


def _observed_portfolio(*, snapshot_id: str) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "source_kind": "manual_json",
        "data_status": "observed",
        "completeness_status": "complete",
        "as_of": "2026-04-06T12:00:00Z",
        "total_value": 18_000.0,
        "available_cash": 12_000.0,
        "weights": {
            "equity_cn": 0.35,
            "bond_cn": 0.40,
            "gold": 0.20,
            "satellite": 0.05,
        },
        "holdings": [
            {"asset_bucket": "equity_cn", "product_id": "fund_equity_cn", "weight": 0.35},
            {"asset_bucket": "bond_cn", "product_id": "fund_bond_cn", "weight": 0.40},
            {"asset_bucket": "gold", "product_id": "etf_gold", "weight": 0.20},
            {"asset_bucket": "satellite", "product_id": "fund_satellite", "weight": 0.05},
        ],
        "missing_fields": [],
        "source_ref": "manual:inline",
    }


def _heavy_runtime_candidate(index: int) -> dict[str, object]:
    product_id = f"ts_product_{index:04d}"
    large_note = f"candidate-{index}-" + ("X" * 600)
    return {
        "candidate": {
            "product_id": product_id,
            "name": f"候选产品{index}",
            "wrapper_type": "fund",
            "asset_bucket": "equity_cn" if index % 2 == 0 else "satellite",
            "risk_labels": ["medium"] if index % 2 == 0 else ["high_risk_product"],
            "themes": ["broad_market"] if index % 3 else ["technology"],
            "notes": [large_note, large_note],
        },
        "registry_index": index,
        "filter_stage": "runtime_pool",
        "valuation_audit": {
            "status": "observed",
            "percentile": round((index % 30) / 100, 4),
            "notes": [large_note],
        },
        "policy_news_audit": {
            "status": "observed",
            "matched_signal_ids": [f"sig-{index}-{offset}" for offset in range(5)],
            "notes": [large_note],
        },
    }


def _heavy_execution_item(index: int) -> dict[str, object]:
    large_reason = f"reason-{index}-" + ("Y" * 400)
    primary_product = {
        "product_id": f"primary_{index}",
        "name": f"主产品{index}",
        "wrapper_type": "fund",
        "asset_bucket": "equity_cn",
    }
    alternate_products = [
        {
            "product_id": f"alt_{index}_{offset}",
            "name": f"备选{index}_{offset}",
            "wrapper_type": "fund",
            "asset_bucket": "equity_cn",
            "notes": [large_reason],
        }
        for offset in range(24)
    ]
    return {
        "asset_bucket": "equity_cn" if index == 0 else "bond_cn" if index == 1 else "gold",
        "target_weight": 0.3,
        "primary_product_id": primary_product["product_id"],
        "alternate_product_ids": [item["product_id"] for item in alternate_products],
        "primary_product": primary_product,
        "alternate_products": alternate_products,
        "rationale": [large_reason, large_reason],
        "risk_labels": ["medium"],
        "target_amount": 5_000.0,
        "trade_direction": "buy",
        "initial_trade_amount": 2_000.0,
        "deferred_trade_amount": 3_000.0,
        "trigger_conditions": [large_reason],
        "valuation_audit": {"status": "observed", "notes": [large_reason]},
        "policy_news_audit": {"status": "unavailable", "notes": [large_reason]},
    }


def _heavy_onboarding_payload(account_profile_id: str) -> dict[str, object]:
    runtime_candidates = [_heavy_runtime_candidate(index) for index in range(64)]
    execution_plan = {
        "plan_id": f"plan_{account_profile_id}",
        "plan_version": 1,
        "source_run_id": f"frontdesk_{account_profile_id}_onboarding",
        "source_allocation_id": "liquidity_buffered__moderate__05",
        "status": "draft",
        "confirmation_required": True,
        "registry_candidate_count": 128,
        "runtime_candidate_count": len(runtime_candidates),
        "runtime_candidates": runtime_candidates,
        "product_proxy_specs": [
            {
                "product_id": f"proxy_{index}",
                "proxy_kind": "wrapper_proxy",
                "proxy_ref": f"proxy://{index}",
                "confidence": 0.6,
                "confidence_data_status": "manual_annotation",
                "confidence_disclosure": "heuristic",
                "source_ref": f"proxy://{index}",
                "data_status": "manual_annotation",
                "as_of": "2026-04-06",
            }
            for index in range(32)
        ],
        "items": [_heavy_execution_item(index) for index in range(3)],
        "candidate_filter_breakdown": {
            "runtime_candidate_count": len(runtime_candidates),
            "dropped_reasons": {"theme:technology": 12},
            "stages": [{"stage_name": "theme", "input_count": 64, "output_count": 52}],
        },
        "product_universe_audit_summary": {
            "requested": True,
            "source_status": "observed",
            "data_status": "observed",
        },
        "valuation_audit_summary": {
            "requested": True,
            "source_status": "observed",
            "data_status": "computed_from_observed",
            "rule_max_pe": 40,
            "rule_max_percentile": 0.3,
        },
        "policy_news_audit_summary": {
            "source_status": "unavailable",
            "matched_signal_count": 0,
        },
        "execution_realism_summary": {
            "executable": True,
            "cash_reserve_target_amount": 1_800.0,
        },
        "maintenance_policy_summary": {
            "initial_deploy_fraction": 0.4,
        },
    }
    product_universe_result = {
        "requested": True,
        "source_status": "observed",
        "data_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": "tinyshare://fund_basic,stock_basic",
        "item_count": 128,
        "runtime_candidate_count": len(runtime_candidates),
        "items": [
            {
                "product_id": candidate["candidate"]["product_id"],
                "name": candidate["candidate"]["name"],
                "wrapper_type": candidate["candidate"]["wrapper_type"],
                "asset_bucket": candidate["candidate"]["asset_bucket"],
            }
            for candidate in runtime_candidates
        ],
        "runtime_candidates": runtime_candidates,
        "products": {
            candidate["candidate"]["product_id"]: candidate["candidate"] for candidate in runtime_candidates
        },
        "audit_window": {
            "start_date": "2024-04-06",
            "end_date": "2026-04-06",
            "trading_days": 490,
            "observed_days": 490,
            "inferred_days": 0,
        },
    }
    valuation_result = {
        "requested": True,
        "source_status": "observed",
        "data_status": "computed_from_observed",
        "source_name": "tinyshare_daily_basic",
        "source_ref": "tinyshare://daily_basic",
        "rule_max_pe": 40,
        "rule_max_percentile": 0.3,
        "products": {
            candidate["candidate"]["product_id"]: {
                "product_id": candidate["candidate"]["product_id"],
                "pe_ratio": 22.0,
                "percentile": 0.22,
                "notes": ["valuation-pass", "Z" * 500],
            }
            for candidate in runtime_candidates[:48]
        },
        "audit_window": {
            "start_date": "2024-04-06",
            "end_date": "2026-04-06",
            "trading_days": 490,
            "observed_days": 490,
            "inferred_days": 0,
        },
    }
    historical_dataset = {
        "source_name": "tinyshare_market_history",
        "source_ref": "tinyshare://market_history",
        "coverage_status": "fresh",
        "data_status": "computed_from_observed",
        "audit_window": {
            "start_date": "2024-04-06",
            "end_date": "2026-04-06",
            "trading_days": 490,
            "observed_days": 490,
            "inferred_days": 0,
        },
        "return_series": {
            f"symbol_{index:03d}": [0.001 * ((index % 5) - 2) for _ in range(240)] for index in range(24)
        },
    }
    return {
        "run_id": f"frontdesk_{account_profile_id}_onboarding_20260406T120000Z",
        "workflow_type": "onboarding",
        "status": "completed",
        "goal_solver_output": {"generated_at": "2026-04-06T12:00:00Z"},
        "decision_card": {
            "card_id": f"card_{account_profile_id}",
            "card_type": "goal_baseline",
            "summary": "heavy onboarding payload",
            "recommended_action": "review",
            "execution_plan_summary": {
                "plan_id": execution_plan["plan_id"],
                "runtime_candidate_count": execution_plan["runtime_candidate_count"],
                "registry_candidate_count": execution_plan["registry_candidate_count"],
                "valuation_audit_summary": execution_plan["valuation_audit_summary"],
                "policy_news_audit_summary": execution_plan["policy_news_audit_summary"],
            },
        },
        "card_build_input": {
            "goal_solver_input": {"account_profile_id": account_profile_id},
            "execution_plan_summary": execution_plan,
        },
        "refresh_summary": {"workflow_type": "onboarding"},
        "input_source_summary": {"externally_fetched": 1},
        "formal_path_visibility": {"status": "ok", "execution_eligible": True},
        "evidence_invariance_report": {
            "baseline_run_ref": f"frontdesk_{account_profile_id}_baseline",
            "optimized_run_ref": f"frontdesk_{account_profile_id}_onboarding_20260406T120000Z",
            "semantic_refs": {
                "resolved_result_category": "formal_estimated_result",
                "run_outcome_status": "completed",
            },
            "artifact_refs": {"storage_ref": f"sqlite://{account_profile_id}"},
            "invariant_fields": ["resolved_result_category", "run_outcome_status"],
            "exact_match_fields": ["resolved_result_category", "run_outcome_status"],
            "tolerated_numeric_diffs": {},
            "drift_fields": [],
            "verdict": "invariant",
        },
        "audit_records": [],
        "persistence_plan": {
            "artifact_records": {
                "execution_plan": {
                    "plan_id": execution_plan["plan_id"],
                    "plan_version": 1,
                    "source_run_id": execution_plan["source_run_id"],
                    "source_allocation_id": execution_plan["source_allocation_id"],
                    "status": "draft",
                    "payload": execution_plan,
                },
                "snapshot_bundle": {
                    "bundle_id": f"bundle_{account_profile_id}",
                    "payload": {
                        "bundle_id": f"bundle_{account_profile_id}",
                        "market": {
                            "product_universe_result": product_universe_result,
                            "product_valuation_result": valuation_result,
                            "historical_dataset": historical_dataset,
                        },
                    },
                },
                "decision_card": {
                    "run_id": f"frontdesk_{account_profile_id}_onboarding_20260406T120000Z",
                    "payload": {"recommended_action": "review"},
                },
            }
        },
        "execution_plan": execution_plan,
        "snapshot_bundle": {
            "bundle_id": f"bundle_{account_profile_id}",
            "market": {
                "product_universe_result": product_universe_result,
                "product_valuation_result": valuation_result,
                "historical_dataset": historical_dataset,
            },
        },
    }


@pytest.mark.contract
def test_frontdesk_persistence_compacts_heavy_onboarding_payloads(tmp_path):
    from frontdesk.service import load_frontdesk_snapshot
    from frontdesk.storage import FrontdeskStore

    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="frontdesk_compaction_storage")
    payload = _heavy_onboarding_payload(profile.account_profile_id)
    store = FrontdeskStore(db_path)
    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=payload,
        input_provenance={"externally_fetched": [{"field": "market_raw", "value": {"source": "tinyshare"}}]},
        created_at="2026-04-06T12:00:00Z",
    )

    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)
    assert snapshot is not None
    latest_run_payload = snapshot["latest_run"]["result_payload"]
    latest_baseline_payload = snapshot["latest_baseline"]["result_payload"]

    assert "snapshot_bundle" not in latest_run_payload
    assert "snapshot_bundle" not in latest_baseline_payload
    assert "execution_plan" not in latest_run_payload
    assert "persistence_plan" not in latest_run_payload
    assert len(json.dumps(latest_run_payload, ensure_ascii=False)) < 200_000
    assert len(json.dumps(latest_baseline_payload, ensure_ascii=False)) < 200_000
    assert latest_run_payload["evidence_invariance_report"]["verdict"] == "invariant"
    assert snapshot["pending_execution_plan"]["runtime_candidate_count"] == 64


@pytest.mark.contract
def test_frontdesk_sync_observed_portfolio_returns_compact_result(tmp_path):
    from frontdesk.service import sync_observed_portfolio
    from frontdesk.storage import FrontdeskStore

    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="frontdesk_compaction_sync")
    payload = _heavy_onboarding_payload(profile.account_profile_id)
    store = FrontdeskStore(db_path)
    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=payload,
        input_provenance={"externally_fetched": [{"field": "market_raw", "value": {"source": "tinyshare"}}]},
        created_at="2026-04-06T12:00:00Z",
    )

    sync_result = sync_observed_portfolio(
        account_profile_id=profile.account_profile_id,
        observed_portfolio=_observed_portfolio(snapshot_id="compact_sync_20260406"),
        db_path=db_path,
    )

    assert sync_result["workflow"] == "sync_portfolio"
    assert sync_result["observed_portfolio"]["snapshot_id"] == "compact_sync_20260406"
    assert sync_result["user_state"]["observed_portfolio"]["snapshot_id"] == "compact_sync_20260406"
    assert "snapshot" not in sync_result
    assert len(json.dumps(sync_result, ensure_ascii=False)) < 250_000
