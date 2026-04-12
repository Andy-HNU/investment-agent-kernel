from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _observed_snapshot_source(tmp_path: Path):
    from shared.onboarding import UserOnboardingProfile
    from tests.contract.test_12_frontdesk_regression import (
        _formal_market_raw_overrides,
        _observed_external_snapshot_source,
    )

    profile = UserOnboardingProfile(
        account_profile_id="bridge_seed",
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )
    return _observed_external_snapshot_source(
        tmp_path,
        profile,
        market_raw_overrides=_formal_market_raw_overrides(),
    )


def _override_primary_recipe_for_integration(monkeypatch, *, path_count: int = 32) -> None:
    from probability_engine import recipes as recipe_module

    override = replace(recipe_module.PRIMARY_RECIPE_V14, path_count=path_count)
    monkeypatch.setattr(recipe_module, "PRIMARY_RECIPE_V14", override)
    monkeypatch.setitem(recipe_module.RECIPE_REGISTRY, override.recipe_name, override)


@pytest.fixture(autouse=True)
def _fast_primary_recipe(monkeypatch):
    _override_primary_recipe_for_integration(monkeypatch)


def test_bridge_handles_onboarding_from_natural_language(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / 'frontdesk.sqlite'
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    task = (
        "please onboard user demo_user with current assets 18000, "
        "monthly 2500, goal 120000 in 36 months, risk moderate"
    )
    result = handle_task(task, db_path=str(db))
    assert result['intent']['name'] == 'onboarding'
    assert result['invocation']['account_profile_id'] == 'demo_user'
    assert result['result']['status'] in {'completed', 'degraded'}
    # Should persist state; follow-up monthly should now be allowed


def test_bridge_handles_status_query(tmp_path, monkeypatch):
    # First, onboard a user so status exists
    from integration.openclaw.bridge import handle_task
    db = tmp_path / 'frontdesk.sqlite'
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    handle_task("onboard user status_user assets 18000 monthly 2500 goal 120000 in 36 months risk moderate", db_path=str(db))

    result = handle_task("show status for user status_user", db_path=str(db))
    assert result['intent']['name'] == 'status'
    assert result['result']['user_state']['profile']['account_profile_id'] == 'status_user'


def test_bridge_onboarding_accepts_provider_config_env(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "provider_snapshot_local.json"
    monkeypatch.delenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", raising=False)
    monkeypatch.setenv(
        "OPENCLAW_BRIDGE_EXTERNAL_DATA_CONFIG",
        json.dumps(
            {
                "adapter": "local_json",
                "snapshot_path": str(fixture_path),
                "provider_name": "fixture_local_json",
            },
            ensure_ascii=False,
        ),
    )

    result = handle_task(
        "please onboard user bridge_provider_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    assert result["intent"]["name"] == "onboarding"
    assert result["result"]["status"] in {"completed", "degraded"}
    assert result["result"]["refresh_summary"]["provider_name"] == "fixture_local_json"
    assert result["result"]["external_snapshot_config"] is not None


def test_bridge_preserves_formal_path_visibility(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    result = handle_task(
        "please onboard user bridge_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    assert "formal_path_visibility" in result["result"]
    assert result["result"]["formal_path_visibility"]["status"] in {
        "completed",
        "formal",
        "degraded",
        "blocked",
        "fallback_used_but_not_formal",
    }


def test_bridge_surfaces_completed_strict_formal_result_from_observed_snapshot(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    result = handle_task(
        "please onboard user bridge_gaussian_guard_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    assert result["result"]["run_outcome_status"] == "completed"
    assert result["result"]["resolved_result_category"] == "formal_independent_result"
    assert result["result"]["probability_truth_view"]["run_outcome_status"] == "completed"
    assert result["result"]["probability_truth_view"]["resolved_result_category"] == "formal_independent_result"
    assert result["result"]["probability_truth_view"]["product_probability_method"] == "product_independent_path"
    assert result["result"]["probability_truth_view"]["formal_path_visibility"]["fallback_used"] is False
    assert result["result"]["probability_engine_result"]["resolved_result_category"] == "formal_strict_result"


def test_bridge_preserves_probability_explanation_payload(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    result = handle_task(
        "please onboard user bridge_probability_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    decision_card = result["result"]["decision_card"]
    probability_explanation = decision_card["probability_explanation"]
    assert "probability_explanation" in decision_card
    assert "frontier_analysis" in decision_card
    assert "product_evidence_panel" in decision_card
    assert (
        "success_probability" in decision_card["key_metrics"]
        or "success_probability_range" in decision_card["key_metrics"]
    )
    assert result["result"]["product_probability_method"] in {
        "product_independent_path",
        "product_estimated_path",
    }
    assert result["result"]["monthly_fallback_used"] is False
    assert result["result"]["bucket_fallback_used"] is False
    probability_payload = result["result"]["probability_disclosure_payload"]
    assert probability_payload["gap_total"] is not None


def test_bridge_surfaces_low_confidence_when_helper_formal_snapshot_disagrees_with_live_models(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task
    from shared.onboarding import UserOnboardingProfile
    from tests.support.formal_snapshot_helpers import write_formal_snapshot_source

    db = tmp_path / "frontdesk.sqlite"
    profile = UserOnboardingProfile(
        account_profile_id="bridge_helper_bounded_user",
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )
    snapshot_source = write_formal_snapshot_source(tmp_path, profile)
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(snapshot_source))

    result = handle_task(
        "please onboard user bridge_helper_bounded_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    probability_result = result["result"]["probability_engine_result"]
    probability_output = probability_result["output"]
    disagreement = probability_output["model_disagreement"]
    disclosure_payload = result["result"]["probability_disclosure_payload"]

    assert result["result"]["status"] in {"completed", "degraded"}
    assert result["result"]["resolved_result_category"] in {
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert probability_result["run_outcome_status"] in {"success", "degraded"}
    assert probability_result["resolved_result_category"] == "formal_strict_result"
    assert probability_output["challenger_results"], "expected live challenger_results to be populated"
    assert probability_output["stress_results"], "expected live stress_results to be populated"
    # The helper snapshot is deliberately synthetic: once live primary/challenger/stress
    # all run against it, the bridge should surface the disagreement rather than hide it.
    assert disagreement["gap_total"] is not None
    assert disagreement["gap_total"] >= 0.05
    assert disclosure_payload["gap_total"] == disagreement["gap_total"]
    assert disclosure_payload["confidence_level"] == "low"


def test_bridge_surfaces_live_probability_disclosure_gap_fields(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    result = handle_task(
        "please onboard user bridge_gap_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    probability_result = result["result"]["probability_engine_result"]
    probability_output = probability_result["output"]
    disclosure_payload = result["result"]["probability_disclosure_payload"]

    assert probability_output["challenger_results"], "expected live challenger_results to be populated"
    assert probability_output["stress_results"], "expected live stress_results to be populated"
    assert probability_output["model_disagreement"]["gap_total"] is not None
    assert probability_output["model_disagreement"]["gap_total"] == disclosure_payload["gap_total"]
    assert disclosure_payload["challenger_gap"] is not None
    assert disclosure_payload["stress_gap"] is not None
    assert disclosure_payload["gap_total"] is not None


def test_bridge_surfaces_runtime_telemetry_for_live_probability_paths(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(_observed_snapshot_source(tmp_path)))
    result = handle_task(
        "please onboard user bridge_runtime_gate_user with current assets 18000, monthly 2500, goal 120000 in 36 months, risk moderate",
        db_path=str(db),
    )

    runtime_telemetry = result["result"]["runtime_telemetry"]
    assert runtime_telemetry["path_horizon_days"] > 20
    assert runtime_telemetry["path_count_primary"] > 0
    assert runtime_telemetry["path_count_challenger"] > 0
    assert runtime_telemetry["path_count_stress"] > 0


def test_bridge_reuses_baseline_evidence_for_repeated_onboarding(tmp_path, monkeypatch):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    snapshot_source = _observed_snapshot_source(tmp_path)
    monkeypatch.setenv("OPENCLAW_BRIDGE_EXTERNAL_SNAPSHOT_SOURCE", str(snapshot_source))
    task = (
        "please onboard user bridge_reuse_user with current assets 18000, "
        "monthly 2500, goal 120000 in 36 months, risk moderate"
    )

    first = handle_task(task, db_path=str(db))
    second = handle_task(task, db_path=str(db))

    assert first["result"]["run_id"] != second["result"]["run_id"]
    assert second["result"]["reuse_context"]["reused"] is True
    assert second["result"]["reuse_context"]["source_run_id"] == first["result"]["run_id"]
    assert second["result"]["evidence_invariance_report"]["baseline_run_ref"] == first["result"]["run_id"]


def test_acceptance_cli_writes_logs(tmp_path, capsys):
    # Smoke test the CLI wrapper to ensure it writes a log file
    import sys
    import subprocess
    script = (REPO_ROOT / "scripts" / "openclaw_bridge_cli.py").resolve()
    db = tmp_path / 'frontdesk.sqlite'
    env = dict(**os.environ)
    env['OPENCLAW_BRIDGE_DB'] = str(db)
    proc = subprocess.run(
        [sys.executable, str(script), '--task', 'onboard user acc_cli assets 50000 monthly 5000 goal 200000 in 36 months'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    out = proc.stdout.strip()
    assert out
    # The script should print the path to a created log file
    log_path = Path(out.splitlines()[-1].split('=')[-1].strip())
    assert log_path.exists()
    logs = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert logs and isinstance(logs[0], dict)


def test_acceptance_harness_reads_task_file_and_writes_jsonl_logs(tmp_path):
    import subprocess
    import sys

    script = (REPO_ROOT / "scripts" / "accept_openclaw_bridge.py").resolve()
    db = tmp_path / "frontdesk.sqlite"
    tasks = tmp_path / "tasks.txt"
    tasks.write_text(
        "\n".join(
            [
                "onboard user acc_accept assets 18000 monthly 2500 goal 120000 in 36 months risk moderate",
                "show status for user acc_accept",
            ]
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--file",
            str(tasks),
            "--db",
            str(db),
            "--artifacts",
            str(artifacts),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    out = proc.stdout.strip()
    assert out.startswith("log_path=")
    log_path = Path(out.splitlines()[-1].split("=", 1)[-1].strip())
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 4
    assert lines[0]["task"].startswith("onboard user acc_accept")
    assert lines[1]["intent"]["name"] == "onboarding"
    assert lines[2]["task"].startswith("show status for user acc_accept")
    assert lines[3]["intent"]["name"] == "status"
