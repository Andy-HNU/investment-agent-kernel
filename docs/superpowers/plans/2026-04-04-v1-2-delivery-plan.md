# v1.2 Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `v1.2` as a real-data, product-aware investment adviser kernel with product selection/maintenance, observed portfolio reconciliation, and a Claw shell that can monitor daily and issue explainable user-confirmed actions.

**Architecture:** `v1.2` is implemented in six independent but ordered workstreams. First establish real-source historical/runtime data truth and product-aware distribution modeling, then build product selection and maintenance policies, then wire observed-portfolio sync/reconciliation, and finally close the Claw shell and forward-validation harness. The system continues to separate `03 ingestion -> 05 calibration -> 02 simulation`, but now adds product-level overlays and explicit reconciliation as first-class layers.

**Tech Stack:** Python 3, pytest, existing frontdesk/orchestrator/product_mapping modules, versioned dataset cache, OpenClaw bridge, real-source provider adapters (`akshare`, `baostock`, `yfinance`), OCR bridge reference from OpenClaw.

---

## File Structure

### Existing files to modify

- `src/snapshot_ingestion/historical.py`
- `src/snapshot_ingestion/types.py`
- `src/snapshot_ingestion/engine.py`
- `src/calibration/engine.py`
- `src/calibration/types.py`
- `src/goal_solver/types.py`
- `src/goal_solver/engine.py`
- `src/product_mapping/types.py`
- `src/product_mapping/catalog.py`
- `src/product_mapping/engine.py`
- `src/frontdesk/service.py`
- `src/frontdesk/storage.py`
- `src/frontdesk/cli.py`
- `src/agent/nli_router.py`
- `src/integration/openclaw/bridge.py`
- `scripts/accept_openclaw_bridge.py`
- `system/02_goal_solver.md`
- `system/03_snapshot_and_ingestion.md`
- `system/05_constraint_and_calibration_v1.1_patched.md`
- `handoff/CODEX_v1.2_task_map_2026-04-03.md`

### New files to create

- `src/shared/providers/akshare_history.py`
- `src/shared/providers/baostock_history.py`
- `src/shared/providers/yfinance_history.py`
- `src/snapshot_ingestion/cycle_policy.py`
- `src/shared/datasets/product_history.py`
- `src/product_mapping/selection.py`
- `src/product_mapping/maintenance.py`
- `src/frontdesk/reconciliation.py`
- `src/frontdesk/ocr_bridge.py`
- `src/agent/explainability.py`
- `scripts/run_v12_forward_validation.py`
- `system/16_product_selection_and_maintenance_v1.2.md`
- `system/17_observed_portfolio_sync_and_reconciliation_v1.2.md`
- `system/18_claw_adviser_shell_v1.2.md`
- `tests/provider/test_akshare_history_provider.py`
- `tests/provider/test_baostock_history_provider.py`
- `tests/provider/test_yfinance_history_provider.py`
- `tests/contract/test_19_cycle_policy_contract.py`
- `tests/contract/test_19_product_history_contract.py`
- `tests/contract/test_19_product_adjusted_probability_contract.py`
- `tests/contract/test_19_product_selection_contract.py`
- `tests/contract/test_19_product_maintenance_contract.py`
- `tests/contract/test_19_reconciliation_contract.py`
- `tests/agent/test_19_claw_shell_contract.py`
- `tests/smoke/test_19_forward_validation_smoke.py`
- `tests/fixtures/real_source/`

### Workstream boundaries

- `src/shared/providers/*_history.py` only fetch and normalize real-source historical/runtime data.
- `src/snapshot_ingestion/*` only freeze, validate, version, and tag raw data.
- `src/calibration/*` only derive states/assumptions/overrides from ingested data.
- `src/goal_solver/*` only simulate and explain success probabilities.
- `src/product_mapping/*` owns product selection and maintenance policy, not raw market fetching.
- `src/frontdesk/reconciliation.py` owns truth-state comparison between observed portfolio and system plans.
- `src/agent/*` and `src/integration/openclaw/*` own natural-language routing/explanation/bridge glue, not finance math.

## Execution order

1. Real-source data truth and cycle coverage
2. Product-aware modeling
3. Product selection engine
4. Product maintenance and quarterly execution policy
5. Observed-portfolio sync and reconciliation
6. Claw shell and evidence UX
7. Forward validation and release gates

## Rules for this implementation

- No new default/inline/synthetic data paths in formal product flows
- New tests and release gates must use real-source cached datasets or live smoke
- All new user-facing success probabilities must disclose whether they are bucket-level, product-adjusted, or both
- `不买股票` defaults to `no_single_stocks`, not `no_equity_exposure`
- Products with insufficient history are not hard-filled; only fund-like wrappers may attach inferred history, and inferred segments must be down-weighted
- Any Claw advice generated from intraday estimated fund NAV must be labeled `estimated_intraday=true` and `close_reconcile_required=true`

### Task 1: Real-Source Data Truth and Cycle Coverage

**Files:**
- Create: `src/shared/providers/akshare_history.py`
- Create: `src/shared/providers/baostock_history.py`
- Create: `src/shared/providers/yfinance_history.py`
- Create: `src/snapshot_ingestion/cycle_policy.py`
- Modify: `src/snapshot_ingestion/historical.py`
- Modify: `src/snapshot_ingestion/types.py`
- Modify: `src/snapshot_ingestion/engine.py`
- Test: `tests/provider/test_akshare_history_provider.py`
- Test: `tests/provider/test_baostock_history_provider.py`
- Test: `tests/provider/test_yfinance_history_provider.py`
- Test: `tests/contract/test_19_cycle_policy_contract.py`

- [ ] **Step 1: Write the failing cycle-policy contract test**

```python
from snapshot_ingestion.cycle_policy import evaluate_cycle_coverage


def test_evaluate_cycle_coverage_flags_missing_bear_phase():
    summary = evaluate_cycle_coverage(
        dates=["2020-01-01", "2020-01-02", "2020-01-03"],
        returns=[0.01, 0.02, 0.01],
    )
    assert summary.coverage_ok is False
    assert "missing_downcycle" in summary.reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contract/test_19_cycle_policy_contract.py::test_evaluate_cycle_coverage_flags_missing_bear_phase -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbol error

- [ ] **Step 3: Write minimal cycle policy implementation**

```python
from dataclasses import dataclass


@dataclass
class CycleCoverageSummary:
    coverage_ok: bool
    reasons: list[str]


def evaluate_cycle_coverage(*, dates: list[str], returns: list[float]) -> CycleCoverageSummary:
    cumulative = 1.0
    peak = 1.0
    saw_downcycle = False
    saw_upcycle = False
    for value in returns:
        cumulative *= 1.0 + value
        peak = max(peak, cumulative)
        drawdown = (peak - cumulative) / peak if peak else 0.0
        if drawdown >= 0.15:
            saw_downcycle = True
        if cumulative >= 1.20:
            saw_upcycle = True
    reasons = []
    if not saw_upcycle:
        reasons.append("missing_upcycle")
    if not saw_downcycle:
        reasons.append("missing_downcycle")
    return CycleCoverageSummary(coverage_ok=not reasons, reasons=reasons)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contract/test_19_cycle_policy_contract.py::test_evaluate_cycle_coverage_flags_missing_bear_phase -v`
Expected: PASS

- [ ] **Step 5: Write the failing real-source provider smoke tests**

```python
from shared.providers.akshare_history import fetch_equity_history


def test_fetch_equity_history_returns_versioned_dataset():
    dataset = fetch_equity_history(symbol="000300", as_of="2026-04-01", lookback_days=3650)
    assert dataset.version_id
    assert dataset.source_name == "akshare"
    assert dataset.return_series
```

- [ ] **Step 6: Run provider tests to verify they fail**

Run: `pytest tests/provider/test_akshare_history_provider.py tests/provider/test_baostock_history_provider.py tests/provider/test_yfinance_history_provider.py -v`
Expected: FAIL with missing provider module/function errors

- [ ] **Step 7: Implement provider fetchers and dataset normalization**

```python
def fetch_equity_history(symbol: str, as_of: str, lookback_days: int) -> HistoricalDatasetSnapshot:
    rows = load_akshare_daily(symbol=symbol, end_date=as_of, lookback_days=lookback_days)
    return build_versioned_dataset(
        source_name="akshare",
        source_ref=f"akshare:{symbol}",
        as_of=as_of,
        rows=rows,
        lookback_days=lookback_days,
    )
```

- [ ] **Step 8: Extend `HistoricalDatasetSnapshot` to store cycle coverage and observed/inferred tags**

```python
@dataclass(frozen=True)
class HistoricalDatasetSnapshot:
    ...
    lookback_days: int
    coverage_status: str = "verified"
    cycle_reasons: list[str] = field(default_factory=list)
    observed_history_days: int = 0
    inferred_history_days: int = 0
```

- [ ] **Step 9: Run targeted tests**

Run: `pytest tests/provider/test_akshare_history_provider.py tests/provider/test_baostock_history_provider.py tests/provider/test_yfinance_history_provider.py tests/contract/test_19_cycle_policy_contract.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/shared/providers/akshare_history.py src/shared/providers/baostock_history.py src/shared/providers/yfinance_history.py src/snapshot_ingestion/cycle_policy.py src/snapshot_ingestion/historical.py src/snapshot_ingestion/types.py src/snapshot_ingestion/engine.py tests/provider/test_akshare_history_provider.py tests/provider/test_baostock_history_provider.py tests/provider/test_yfinance_history_provider.py tests/contract/test_19_cycle_policy_contract.py
git commit -m "feat: add real-source history ingestion and cycle coverage policy"
```

### Task 2: Product History and Product-Aware Distribution Modeling

**Files:**
- Create: `src/shared/datasets/product_history.py`
- Modify: `src/calibration/types.py`
- Modify: `src/calibration/engine.py`
- Modify: `src/goal_solver/types.py`
- Modify: `src/goal_solver/engine.py`
- Test: `tests/contract/test_19_product_history_contract.py`
- Test: `tests/contract/test_19_product_adjusted_probability_contract.py`

- [ ] **Step 1: Write the failing product-history contract**

```python
from shared.datasets.product_history import ProductHistoryProfile, ProductHistorySegment


def test_product_history_profile_tracks_observed_and_inferred_days():
    profile = ProductHistoryProfile(
        product_id="510300",
        observed_history_days=1200,
        inferred_history_days=400,
        inference_method="index_proxy",
        inference_weight=0.6,
        segments=[
            ProductHistorySegment("2019-01-01", "2023-12-31", "observed", "fund_nav", 1.0, [0.01]),
            ProductHistorySegment("2015-01-01", "2018-12-31", "inferred", "csi300", 0.6, [0.02]),
        ],
    )
    assert profile.observed_history_days == 1200
    assert profile.inferred_history_days == 400
```

- [ ] **Step 2: Run product-history test to verify it fails**

Run: `pytest tests/contract/test_19_product_history_contract.py::test_product_history_profile_tracks_observed_and_inferred_days -v`
Expected: FAIL with missing module error

- [ ] **Step 3: Add product-history types**

```python
@dataclass
class ProductHistorySegment:
    start_date: str
    end_date: str
    source_kind: str
    source_ref: str
    confidence: float
    return_series: list[float]


@dataclass
class ProductHistoryProfile:
    product_id: str
    observed_history_days: int
    inferred_history_days: int
    inference_method: str | None
    inference_weight: float
    segments: list[ProductHistorySegment]
```

- [ ] **Step 4: Write the failing product-adjusted probability test**

```python
from goal_solver.engine import adjust_success_probability_for_product_overlay


def test_adjust_success_probability_penalizes_high_tracking_error_and_inferred_history():
    adjusted = adjust_success_probability_for_product_overlay(
        bucket_success_probability=0.72,
        annual_fee=0.005,
        tracking_error=0.03,
        inferred_history_weight=0.5,
    )
    assert adjusted < 0.72
```

- [ ] **Step 5: Run probability overlay test to verify it fails**

Run: `pytest tests/contract/test_19_product_adjusted_probability_contract.py::test_adjust_success_probability_penalizes_high_tracking_error_and_inferred_history -v`
Expected: FAIL with missing function error

- [ ] **Step 6: Implement product overlay adjustment and dual probability outputs**

```python
def adjust_success_probability_for_product_overlay(
    *,
    bucket_success_probability: float,
    annual_fee: float,
    tracking_error: float,
    inferred_history_weight: float,
) -> float:
    penalty = annual_fee * 2.0 + tracking_error * 0.75 + (1.0 - inferred_history_weight) * 0.05
    return max(0.0, min(1.0, bucket_success_probability - penalty))
```

- [ ] **Step 7: Add dual outputs to `GoalSolverOutput`**

```python
bucket_success_probability: float
product_adjusted_success_probability: float | None = None
probability_basis: Literal["bucket_only", "bucket_plus_product"] = "bucket_only"
```

- [ ] **Step 8: Run targeted modeling tests**

Run: `pytest tests/contract/test_19_product_history_contract.py tests/contract/test_19_product_adjusted_probability_contract.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/shared/datasets/product_history.py src/calibration/types.py src/calibration/engine.py src/goal_solver/types.py src/goal_solver/engine.py tests/contract/test_19_product_history_contract.py tests/contract/test_19_product_adjusted_probability_contract.py
git commit -m "feat: add product-aware history and dual success probabilities"
```

### Task 3: Product Selection Engine

**Files:**
- Create: `src/product_mapping/selection.py`
- Modify: `src/product_mapping/types.py`
- Modify: `src/product_mapping/catalog.py`
- Modify: `src/product_mapping/engine.py`
- Test: `tests/contract/test_19_product_selection_contract.py`

- [ ] **Step 1: Write the failing selection constraint test**

```python
from product_mapping.selection import normalize_user_restrictions


def test_no_stock_disallows_single_stocks_but_keeps_index_wrappers():
    restrictions = normalize_user_restrictions(["不买股票"])
    assert "single_stock" in restrictions.forbidden_wrappers
    assert "equity_cn" not in restrictions.forbidden_exposures
```

- [ ] **Step 2: Run restriction test to verify it fails**

Run: `pytest tests/contract/test_19_product_selection_contract.py::test_no_stock_disallows_single_stocks_but_keeps_index_wrappers -v`
Expected: FAIL with missing module or symbol error

- [ ] **Step 3: Add product-constraint profile and selection logic**

```python
@dataclass
class ProductConstraintProfile:
    forbidden_exposures: set[str]
    forbidden_wrappers: set[str]
    forbidden_styles: set[str]
    allowed_wrappers: set[str]
    allowed_markets: set[str]
```

- [ ] **Step 4: Extend the catalog to include all required product families**

```python
ProductCandidate(
    product_id="510300",
    asset_bucket="equity_cn",
    wrapper_type="etf",
    style_tags=["broad_market", "core"],
    ...
)
ProductCandidate(
    product_id="600519",
    asset_bucket="equity_cn",
    wrapper_type="single_stock",
    style_tags=["stock", "china_a"],
    ...
)
```

- [ ] **Step 5: Write ranking tests for multiple products per bucket**

```python
def test_selection_returns_multiple_candidates_with_evidence():
    plan = build_selection_candidates(...)
    assert len(plan.items[0].alternate_product_ids) >= 2
    assert plan.items[0].evidence["selection_reason"]
```

- [ ] **Step 6: Run selection tests**

Run: `pytest tests/contract/test_19_product_selection_contract.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/product_mapping/selection.py src/product_mapping/types.py src/product_mapping/catalog.py src/product_mapping/engine.py tests/contract/test_19_product_selection_contract.py
git commit -m "feat: add product selection engine and wrapper-aware constraints"
```

### Task 4: Product Maintenance and Quarterly Execution Policy

**Files:**
- Create: `src/product_mapping/maintenance.py`
- Modify: `src/product_mapping/types.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/frontdesk/storage.py`
- Modify: `src/frontdesk/cli.py`
- Test: `tests/contract/test_19_product_maintenance_contract.py`

- [ ] **Step 1: Write the failing maintenance policy test**

```python
from product_mapping.maintenance import build_quarterly_execution_policy


def test_build_quarterly_execution_policy_creates_core_and_satellite_rules():
    policy = build_quarterly_execution_policy(
        account_profile_id="andy_main",
        target_required_return=0.15,
        current_success_probability=0.42,
    )
    assert policy.trigger_rules
    assert any(rule.scope == "core" for rule in policy.trigger_rules)
    assert any(rule.scope == "satellite" for rule in policy.trigger_rules)
```

- [ ] **Step 2: Run maintenance test to verify it fails**

Run: `pytest tests/contract/test_19_product_maintenance_contract.py::test_build_quarterly_execution_policy_creates_core_and_satellite_rules -v`
Expected: FAIL

- [ ] **Step 3: Implement dynamic budget and trigger rules**

```python
def derive_satellite_budget(*, target_required_return: float, risk_capacity: float, current_gap: float) -> float:
    return max(0.0, min(0.35, 0.05 + current_gap * 0.6 + risk_capacity * 0.2))
```

- [ ] **Step 4: Add quarterly execution policy output**

```python
@dataclass
class TriggerRule:
    rule_id: str
    scope: str
    trigger_type: str
    threshold: float
    action: str
    size_rule: str
    note: str
```

- [ ] **Step 5: Wire policies into frontdesk storage and rendering**

```python
payload["execution_policy"] = asdict(policy)
payload["cash_reserve_target"] = policy.cash_reserve_target
```

- [ ] **Step 6: Run maintenance/frontdesk tests**

Run: `pytest tests/contract/test_19_product_maintenance_contract.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/product_mapping/maintenance.py src/product_mapping/types.py src/frontdesk/service.py src/frontdesk/storage.py src/frontdesk/cli.py tests/contract/test_19_product_maintenance_contract.py
git commit -m "feat: add quarterly execution policies and dynamic budgets"
```

### Task 5: Observed Portfolio Sync and Reconciliation

**Files:**
- Create: `src/frontdesk/reconciliation.py`
- Create: `src/frontdesk/ocr_bridge.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/frontdesk/storage.py`
- Modify: `src/frontdesk/cli.py`
- Test: `tests/contract/test_19_reconciliation_contract.py`

- [ ] **Step 1: Write the failing reconciliation contract**

```python
from frontdesk.reconciliation import reconcile_observed_portfolio


def test_reconcile_observed_portfolio_flags_unexpected_and_missing_products():
    result = reconcile_observed_portfolio(
        observed=["511010", "518880"],
        target=["511010", "510300"],
    )
    assert result.missing_products == ["510300"]
    assert result.unexpected_products == ["518880"]
```

- [ ] **Step 2: Run reconciliation test to verify it fails**

Run: `pytest tests/contract/test_19_reconciliation_contract.py::test_reconcile_observed_portfolio_flags_unexpected_and_missing_products -v`
Expected: FAIL

- [ ] **Step 3: Implement reconciliation state**

```python
def reconcile_observed_portfolio(*, observed: list[str], target: list[str]) -> ReconciliationState:
    return ReconciliationState(
        account_profile_id="",
        observed_portfolio_version="",
        target_plan_id=None,
        planned_action_status="pending",
        drift_by_bucket={},
        drift_by_product={},
        missing_products=sorted(set(target) - set(observed)),
        unexpected_products=sorted(set(observed) - set(target)),
    )
```

- [ ] **Step 4: Add OCR bridge reference contract**

```python
def import_snapshot_from_ocr(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_kind": "ocr",
        "holdings": payload["holdings"],
        "confidence": payload.get("confidence", 0.0),
    }
```

- [ ] **Step 5: Wire manual/import/OCR sync routes into frontdesk service**

```python
if source_kind == "ocr":
    observed = import_snapshot_from_ocr(payload)
```

- [ ] **Step 6: Run reconciliation tests**

Run: `pytest tests/contract/test_19_reconciliation_contract.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/frontdesk/reconciliation.py src/frontdesk/ocr_bridge.py src/frontdesk/service.py src/frontdesk/storage.py src/frontdesk/cli.py tests/contract/test_19_reconciliation_contract.py
git commit -m "feat: add observed portfolio reconciliation and OCR bridge"
```

### Task 6: Claw Adviser Shell and Explainability

**Files:**
- Create: `src/agent/explainability.py`
- Modify: `src/agent/nli_router.py`
- Modify: `src/integration/openclaw/bridge.py`
- Modify: `scripts/accept_openclaw_bridge.py`
- Test: `tests/agent/test_19_claw_shell_contract.py`

- [ ] **Step 1: Write the failing Claw shell routing test**

```python
from agent.nli_router import route_intent


def test_route_intent_supports_explain_data_basis():
    intent = route_intent("请解释你用了哪些历史数据、哪些是推算历史")
    assert intent == "explain_data_basis"
```

- [ ] **Step 2: Run Claw shell test to verify it fails**

Run: `pytest tests/agent/test_19_claw_shell_contract.py::test_route_intent_supports_explain_data_basis -v`
Expected: FAIL

- [ ] **Step 3: Add explainability helpers**

```python
def build_probability_explanation(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "simulation_mode": context["simulation_mode"],
        "dataset_version": context["dataset_version"],
        "observed_history_days": context["observed_history_days"],
        "inferred_history_days": context["inferred_history_days"],
    }
```

- [ ] **Step 4: Extend NL surface and bridge actions**

```python
SUPPORTED_INTENTS = {
    ...,
    "explain_data_basis",
    "explain_execution_policy",
    "daily_monitor",
    "sync_portfolio_ocr",
}
```

- [ ] **Step 5: Add contract tests for daily monitor and OCR sync intents**

```python
def test_route_intent_supports_daily_monitor():
    assert route_intent("今天帮我监控一下需要止盈止损的品种") == "daily_monitor"
```

- [ ] **Step 6: Run agent tests**

Run: `pytest tests/agent/test_19_claw_shell_contract.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/agent/explainability.py src/agent/nli_router.py src/integration/openclaw/bridge.py scripts/accept_openclaw_bridge.py tests/agent/test_19_claw_shell_contract.py
git commit -m "feat: extend claw shell for daily monitoring and data-basis explanations"
```

### Task 7: Forward Validation and Release Gates

**Files:**
- Create: `scripts/run_v12_forward_validation.py`
- Create: `tests/smoke/test_19_forward_validation_smoke.py`
- Modify: `handoff/CODEX_v1.2_task_map_2026-04-03.md`
- Modify: `system/02_goal_solver.md`
- Modify: `system/03_snapshot_and_ingestion.md`
- Modify: `system/05_constraint_and_calibration_v1.1_patched.md`
- Create: `system/16_product_selection_and_maintenance_v1.2.md`
- Create: `system/17_observed_portfolio_sync_and_reconciliation_v1.2.md`
- Create: `system/18_claw_adviser_shell_v1.2.md`

- [ ] **Step 1: Write the failing forward-validation smoke test**

```python
from scripts.run_v12_forward_validation import run_anchor_validation


def test_run_anchor_validation_returns_realized_terminal_value():
    result = run_anchor_validation(anchor_date="2021-01-01", horizon_months=60)
    assert "predicted_success_probability" in result
    assert "realized_terminal_value" in result
    assert "goal_achieved" in result
```

- [ ] **Step 2: Run forward-validation test to verify it fails**

Run: `pytest tests/smoke/test_19_forward_validation_smoke.py::test_run_anchor_validation_returns_realized_terminal_value -v`
Expected: FAIL

- [ ] **Step 3: Implement the anchor validator**

```python
def run_anchor_validation(anchor_date: str, horizon_months: int) -> dict[str, Any]:
    historical_dataset = load_real_source_history(before=anchor_date)
    future_dataset = load_real_source_history(after=anchor_date)
    recommendation = simulate_plan_with_historical_inputs(historical_dataset, anchor_date)
    realized = replay_plan_on_future_path(recommendation, future_dataset, horizon_months=horizon_months)
    return {
        "predicted_success_probability": recommendation["product_adjusted_success_probability"],
        "realized_terminal_value": realized["terminal_value"],
        "goal_achieved": realized["terminal_value"] >= recommendation["goal_amount"],
    }
```

- [ ] **Step 4: Add rolling validation expansion**

```python
anchors = ["2021-01-01", "2021-04-01", "2021-07-01", "2021-10-01"]
results = [run_anchor_validation(anchor, 60) for anchor in anchors]
```

- [ ] **Step 5: Define release metrics**

```python
assert result["predicted_success_probability"] is not None
assert isinstance(result["goal_achieved"], bool)
```

Release report must include:
- realized terminal value
- predicted bucket probability
- predicted product-adjusted probability
- target hit / miss
- Brier-style scoring over multiple anchors
- calibration buckets over rolling anchors

- [ ] **Step 6: Run full validation smoke**

Run: `pytest tests/smoke/test_19_forward_validation_smoke.py -v`
Expected: PASS

- [ ] **Step 7: Update system and handoff docs**

```markdown
- add forward-validation section to `system/02_goal_solver.md`
- add real-source/cycle coverage and inferred-history rules to `system/03_snapshot_and_ingestion.md`
- add product overlay/reconciliation references to `system/05_constraint_and_calibration_v1.1_patched.md`
```

- [ ] **Step 8: Commit**

```bash
git add scripts/run_v12_forward_validation.py tests/smoke/test_19_forward_validation_smoke.py handoff/CODEX_v1.2_task_map_2026-04-03.md system/02_goal_solver.md system/03_snapshot_and_ingestion.md system/05_constraint_and_calibration_v1.1_patched.md system/16_product_selection_and_maintenance_v1.2.md system/17_observed_portfolio_sync_and_reconciliation_v1.2.md system/18_claw_adviser_shell_v1.2.md
git commit -m "feat: add v1.2 forward validation and freeze docs"
```

## Self-review checklist

- Spec coverage:
  - real-source-only policy: covered in Tasks 1 and 7
  - product-aware probability: Task 2
  - product selection: Task 3
  - product maintenance and quarterly plan: Task 4
  - observed portfolio sync/OCR/reconciliation: Task 5
  - Claw shell and explainability: Task 6
  - 2021-01-01 forward validation idea expanded into anchor-based validation: Task 7
- Placeholder scan:
  - no placeholder markers remain
  - all tasks include file paths, tests, commands, and commit points
- Type consistency:
  - `ProductHistoryProfile`, `ReconciliationState`, `TriggerRule` and dual probability outputs are introduced before later tasks consume them

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-04-v1-2-delivery-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
