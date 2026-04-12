# Intra-Bucket Construction And Portfolio Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-product intra-bucket construction, user-requested bucket counts, user-specified portfolio evaluation, and per-product / per-group explanation outputs without changing the `v1.4` path-generation engine semantics.

**Architecture:** Keep the `v1.4` probability engine as the single source of truth for path generation. Add a new construction layer in `product_mapping` that resolves bucket counts and product subsets, then add an evaluation/explanation layer that can run on both system-generated and user-entered portfolios. Wire the new contracts through orchestrator, frontdesk, and decision-card surfaces.

**Tech Stack:** Python 3, existing dataclass contracts, `pytest`, frontdesk/orchestrator/product-mapping modules

---

## File Structure

**Create**
- `src/product_mapping/cardinality.py`
  Count resolution helpers for automatic and user-requested bucket counts.
- `src/product_mapping/relationships.py`
  Intra-bucket prior relation model and compatibility scoring.
- `src/product_mapping/construction.py`
  Subset construction helpers for `equity_cn`, `satellite`, and coarse `bond_cn`.
- `src/product_mapping/explanations.py`
  Per-product, per-group, and bucket-construction explanation builders.
- `tests/contract/test_43_intra_bucket_construction_contract.py`
  Contract coverage for count resolution and subset selection.
- `tests/contract/test_44_user_portfolio_evaluation_contract.py`
  Contract coverage for user-entered portfolios and unknown products.
- `tests/contract/test_45_product_explanation_surface_contract.py`
  Contract coverage for product/group explanation outputs.

**Modify**
- `src/product_mapping/types.py`
- `src/product_mapping/engine.py`
- `src/product_mapping/__init__.py`
- `src/orchestrator/engine.py`
- `src/frontdesk/service.py`
- `src/decision_card/builder.py`
- `tests/contract/test_09_decision_card_contract.py`
- `tests/contract/test_12_frontdesk_regression.py`
- `tests/contract/test_37_v14_probability_engine_contract.py`
- `tests/contract/test_42_v14_formal_daily_wiring_contract.py`
- `tests/integration/test_v14_probability_engine_integration.py`

## Task 1: Add Contracts For Count Resolution And Explanation Surfaces

**Files:**
- Create: `src/product_mapping/cardinality.py`
- Create: `src/product_mapping/explanations.py`
- Modify: `src/product_mapping/types.py`
- Modify: `src/product_mapping/__init__.py`
- Test: `tests/contract/test_43_intra_bucket_construction_contract.py`
- Test: `tests/contract/test_45_product_explanation_surface_contract.py`

- [ ] **Step 1: Write the failing contract tests**

Add tests that assert:

```python
def test_bucket_count_resolution_prefers_explicit_user_request():
    resolution = resolve_bucket_count(
        bucket="satellite",
        bucket_weight=0.20,
        horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        explicit_request=BucketCardinalityPreference(
            bucket="satellite",
            mode="target_count",
            target_count=5,
            min_count=None,
            max_count=None,
            source="user_requested",
        ),
        persisted_preference=None,
    )
    assert resolution.requested_count == 5
    assert resolution.resolved_count == 5
    assert resolution.source == "explicit_user"
```

```python
def test_product_explanation_requires_full_scenario_ladder():
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(scenario_kind="historical_replay", annualized_range=(0.01, 0.02), terminal_value_range=(1.0, 2.0), pressure_score=None, pressure_level=None),
            ProductScenarioMetrics(scenario_kind="current_market", annualized_range=(0.01, 0.02), terminal_value_range=(1.0, 2.0), pressure_score=8.0, pressure_level="L0_宽松"),
            ProductScenarioMetrics(scenario_kind="deteriorated_mild", annualized_range=(0.01, 0.02), terminal_value_range=(1.0, 2.0), pressure_score=21.0, pressure_level="L0_宽松"),
            ProductScenarioMetrics(scenario_kind="deteriorated_moderate", annualized_range=(0.01, 0.02), terminal_value_range=(1.0, 2.0), pressure_score=37.0, pressure_level="L1_中性偏紧"),
            ProductScenarioMetrics(scenario_kind="deteriorated_severe", annualized_range=(0.01, 0.02), terminal_value_range=(1.0, 2.0), pressure_score=60.0, pressure_level="L2_风险偏高"),
        ],
        success_delta_if_removed=0.1,
        terminal_mean_delta_if_removed=1000.0,
        drawdown_delta_if_removed=0.01,
        median_return_delta_if_removed=0.005,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=["high_expected_return"],
        suggested_action="keep",
    )
    assert {item.scenario_kind for item in explanation.scenario_metrics} == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_45_product_explanation_surface_contract.py -q
```

Expected:
- FAIL with missing imports / missing dataclasses / missing resolver functions

- [ ] **Step 3: Add the new contracts**

Implement:
- `BucketCardinalityPreference`
- `BucketCountResolution`
- `ProductScenarioMetrics`
- `ProductExplanation`
- `ProductGroupExplanation`
- `BucketConstructionExplanation`

and export helper entry points:

```python
from .cardinality import resolve_bucket_count
from .explanations import validate_product_scenario_metrics
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_45_product_explanation_surface_contract.py -q
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/product_mapping/types.py src/product_mapping/cardinality.py src/product_mapping/explanations.py src/product_mapping/__init__.py tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_45_product_explanation_surface_contract.py
git commit -m "feat: add intra-bucket construction contracts"
```

## Task 2: Replace Single-Product Bucket Selection With Count-Aware Subset Construction

**Files:**
- Create: `src/product_mapping/relationships.py`
- Create: `src/product_mapping/construction.py`
- Modify: `src/product_mapping/engine.py`
- Test: `tests/contract/test_43_intra_bucket_construction_contract.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Write the failing construction tests**

Add tests that assert:

```python
def test_equity_bucket_can_return_two_products_when_requested():
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={"equity_cn": 0.40, "bond_cn": 0.20, "gold": 0.10, "satellite": 0.20, "cash_liquidity": 0.10},
        bucket_count_preferences=[
            BucketCardinalityPreference(bucket="equity_cn", mode="target_count", target_count=2, min_count=None, max_count=None, source="user_requested"),
        ],
    )
    equity_items = [item for item in plan.items if item.asset_bucket == "equity_cn"]
    assert len(equity_items) == 2
```

```python
def test_satellite_bucket_can_build_requested_five_member_structure_or_flag_unmet_reason():
    plan = build_execution_plan(
        source_run_id="test",
        source_allocation_id="alloc",
        bucket_targets={"satellite": 0.20, "cash_liquidity": 0.80},
        bucket_count_preferences=[
            BucketCardinalityPreference(bucket="satellite", mode="target_count", target_count=5, min_count=None, max_count=None, source="user_requested"),
        ],
    )
    satellite_items = [item for item in plan.items if item.asset_bucket == "satellite"]
    assert len(satellite_items) in {5, 4, 3, 2, 1}
    assert plan.bucket_construction_explanations["satellite"].requested_count == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py -q
```

Expected:
- FAIL because `build_execution_plan()` still emits one item per bucket

- [ ] **Step 3: Implement count-aware construction helpers**

Implement in focused helpers:

```python
def build_bucket_subset(
    *,
    bucket: str,
    bucket_weight: float,
    requested_resolution: BucketCountResolution,
    candidates: list[RuntimeProductCandidate],
) -> list[RuntimeProductCandidate]:
    ...
```

```python
def score_candidate_subset(
    *,
    bucket: str,
    members: list[RuntimeProductCandidate],
) -> float:
    ...
```

Rules to enforce:
- `gold` and `cash_liquidity` remain single-product
- `bond_cn` coarse two-product max in automatic mode
- `equity_cn` and `satellite` may return multiple primary members
- user request may exceed automatic recommendation counts
- minimum position thresholds may trigger unmet-reason diagnostics

- [ ] **Step 4: Refactor `build_execution_plan()` to emit multiple items per bucket**

Adjust `build_execution_plan()` so that:
- it resolves count policy first
- it builds subsets per bucket
- it emits multiple `ExecutionPlanItem` rows for buckets with multiple selected products
- it persists `bucket_construction_explanations`

Do not change the probability engine in this task.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py tests/integration/test_v14_probability_engine_integration.py -k "bucket or requested_count" -q
```

Expected:
- PASS

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/product_mapping/relationships.py src/product_mapping/construction.py src/product_mapping/engine.py tests/contract/test_43_intra_bucket_construction_contract.py tests/integration/test_v14_probability_engine_integration.py
git commit -m "feat: add count-aware intra-bucket construction"
```

## Task 3: Add User-Specified Portfolio Evaluation And Unknown-Product Resolution State

**Files:**
- Modify: `src/orchestrator/engine.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/product_mapping/types.py`
- Test: `tests/contract/test_44_user_portfolio_evaluation_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing evaluation-mode tests**

Add tests that assert:

```python
def test_user_portfolio_is_evaluated_as_entered_without_rewrite():
    result = run_frontdesk_onboarding(
        profile_with_user_portfolio(
            user_portfolio=[
                {"product_id": "cn_equity_dividend_etf", "target_weight": 0.25},
                {"product_id": "cn_equity_csi300_etf", "target_weight": 0.25},
                {"product_id": "cn_gold_etf", "target_weight": 0.10},
                {"product_id": "cn_cash_money_fund", "target_weight": 0.40},
            ]
        ),
        ...
    )
    assert result["evaluation_mode"] == "user_specified_portfolio"
    assert result["pending_execution_plan"]["items"][0]["primary_product_id"] in {
        "cn_equity_dividend_etf",
        "cn_equity_csi300_etf",
        "cn_gold_etf",
        "cn_cash_money_fund",
    }
```

```python
def test_unrecognized_product_blocks_strict_formal_until_user_resolves():
    result = run_frontdesk_onboarding(
        profile_with_user_portfolio(
            user_portfolio=[{"product_id": "mystery_fund_x", "target_weight": 1.0}]
        ),
        ...
    )
    assert result["unknown_product_resolution"]["state"] == "unrecognized_requires_user_action"
    assert result["resolved_result_category"] != "formal_independent_result"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_44_user_portfolio_evaluation_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- FAIL because no user-specified portfolio intake path exists yet

- [ ] **Step 3: Implement user portfolio intake**

Add a new input path that accepts explicit product lists and weights.

Recommended behavior:

```python
if user_portfolio is not None:
    evaluation_mode = "user_specified_portfolio"
    requested_structure = build_execution_plan_from_user_portfolio(...)
else:
    evaluation_mode = "system_recommended_portfolio"
```

The user path must:
- preserve the entered structure
- route unknown products into explicit resolution state
- keep formal output blocked until unknown products are resolved or explicitly degraded

- [ ] **Step 4: Implement unknown-product state machine**

Add persisted state fields and resolution values:
- `recognized`
- `unrecognized_requires_user_action`
- `user_selected_proxy`
- `user_excluded_product`
- `estimated_non_formal_allowed`
- `resolved_formal_ready`

Wire these through frontdesk persistence and orchestrator gating.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_44_user_portfolio_evaluation_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- PASS

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/orchestrator/engine.py src/frontdesk/service.py src/product_mapping/types.py tests/contract/test_44_user_portfolio_evaluation_contract.py tests/contract/test_12_frontdesk_regression.py
git commit -m "feat: add user portfolio evaluation flow"
```

## Task 4: Add Per-Product And Per-Group Explanation Calculations

**Files:**
- Modify: `src/product_mapping/explanations.py`
- Modify: `src/orchestrator/engine.py`
- Modify: `src/frontdesk/service.py`
- Test: `tests/contract/test_45_product_explanation_surface_contract.py`
- Test: `tests/contract/test_42_v14_formal_daily_wiring_contract.py`

- [ ] **Step 1: Write the failing explanation tests**

Add tests that assert:

```python
def test_product_explanation_emits_marginal_contribution_and_full_scenario_ladder():
    result = run_frontdesk_onboarding(...)
    explanations = result["product_explanations"]
    first = explanations[0]
    assert first["success_delta_if_removed"] is not None
    assert {m["scenario_kind"] for m in first["scenario_metrics"]} == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }
```

```python
def test_group_explanation_emits_duplicate_exposure_group():
    result = run_frontdesk_onboarding(...)
    groups = result["product_group_explanations"]
    assert any(group["group_type"] == "duplicate_exposure_group" for group in groups)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_45_product_explanation_surface_contract.py tests/contract/test_42_v14_formal_daily_wiring_contract.py -q
```

Expected:
- FAIL because explanation surfaces do not exist yet

- [ ] **Step 3: Implement product leave-one-out and group leave-out calculations**

Implement helpers that:
- remove one product or one group
- redistribute weight pro rata across remaining products
- rerun explanation-level summary on the same scenario ladder

Recommended helper boundaries:

```python
def build_product_explanations(...): ...
def build_group_explanations(...): ...
def evaluate_leave_out_structure(...): ...
```

Do not modify the core `v1.4` path-generation logic here. Reuse existing output summaries.

- [ ] **Step 4: Wire explanations into orchestrator/frontdesk output**

Ensure the top-level result contains:
- `bucket_construction_explanations`
- `product_explanations`
- `product_group_explanations`

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_45_product_explanation_surface_contract.py tests/contract/test_42_v14_formal_daily_wiring_contract.py -q
```

Expected:
- PASS

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/product_mapping/explanations.py src/orchestrator/engine.py src/frontdesk/service.py tests/contract/test_45_product_explanation_surface_contract.py tests/contract/test_42_v14_formal_daily_wiring_contract.py
git commit -m "feat: add product and group explanation surfaces"
```

## Task 5: Expose Requested vs Suggested Structures In Frontdesk And Decision Cards

**Files:**
- Modify: `src/frontdesk/service.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing UI-surface tests**

Add tests that assert:

```python
def test_frontdesk_shows_requested_and_suggested_structures_side_by_side():
    result = run_frontdesk_onboarding(profile_with_count_request(...), ...)
    assert result["requested_structure_result"] is not None
    assert result["system_suggested_alternative"] is not None
```

```python
def test_decision_card_surfaces_bucket_construction_explanations():
    result = run_frontdesk_onboarding(...)
    card = result["decision_card"]
    assert card["bucket_construction_explanations"]["satellite"]["actual_count"] >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- FAIL because the new comparison surfaces are not wired yet

- [ ] **Step 3: Wire comparison and explanation payloads**

Expose in frontdesk and decision-card surfaces:
- requested structure result
- suggested alternative result
- bucket construction explanations
- product explanations
- group explanations
- unmet count reasons

Keep user language factual, not persuasive.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/frontdesk/service.py src/decision_card/builder.py tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py
git commit -m "feat: expose requested and suggested portfolio structures"
```

## Task 6: Run End-To-End Verification For Recommendation And Evaluation Modes

**Files:**
- Modify: `tests/integration/test_v14_probability_engine_integration.py`
- Modify: `tests/contract/test_37_v14_probability_engine_contract.py`
- Modify: `tests/contract/test_42_v14_formal_daily_wiring_contract.py`

- [ ] **Step 1: Add final integration tests**

Add integration coverage for:

```python
def test_recommendation_mode_can_emit_multi_product_equity_and_satellite_structure(): ...
def test_user_specified_portfolio_is_evaluated_without_rewrite(): ...
def test_unknown_product_enters_resolution_state_and_blocks_strict_formal(): ...
def test_product_explanation_and_group_explanation_surfaces_are_present(): ...
```

- [ ] **Step 2: Run final focused suite**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest \
  tests/contract/test_37_v14_probability_engine_contract.py \
  tests/contract/test_42_v14_formal_daily_wiring_contract.py \
  tests/contract/test_43_intra_bucket_construction_contract.py \
  tests/contract/test_44_user_portfolio_evaluation_contract.py \
  tests/contract/test_45_product_explanation_surface_contract.py \
  tests/contract/test_09_decision_card_contract.py \
  tests/contract/test_12_frontdesk_regression.py \
  tests/integration/test_v14_probability_engine_integration.py -q
```

Expected:
- PASS

- [ ] **Step 3: Run diff hygiene**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git diff --check
```

Expected:
- no output

- [ ] **Step 4: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add tests/contract/test_37_v14_probability_engine_contract.py tests/contract/test_42_v14_formal_daily_wiring_contract.py tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_44_user_portfolio_evaluation_contract.py tests/contract/test_45_product_explanation_surface_contract.py tests/integration/test_v14_probability_engine_integration.py
git commit -m "test: cover intra-bucket recommendation and evaluation mode"
```

## Self-Review

### Spec coverage

- Bucket cardinality policy: Task 1, Task 2
- Intra-bucket construction: Task 2
- User-specified portfolio evaluation: Task 3
- Unknown-product explicit state: Task 3
- Product explanation surface: Task 4
- Product-group leave-out analysis: Task 4
- Requested vs suggested structure UX: Task 5
- End-to-end verification: Task 6

### Placeholder scan

- No `TBD`, `TODO`, or deferred implementation placeholders remain in task steps.
- Every task names exact files and exact verification commands.

### Type consistency

- Count policy types are introduced first in Task 1 and reused in Task 2 and Task 5.
- Explanation types are introduced first in Task 1 and reused in Task 4 and Task 5.
- Unknown-product states are defined in Task 3 before being consumed in Task 5 and Task 6.
