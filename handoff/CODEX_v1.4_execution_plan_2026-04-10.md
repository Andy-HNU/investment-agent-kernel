# v1.4 Daily Product Probability Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1.4 daily product-level probability engine with Scheme B as the formal primary model, Scheme C as the challenger, strict daily-only formal execution, and v1.3-compatible disclosure/evidence surfaces.

**Architecture:** Add a new `src/probability_engine/` subsystem for contracts, factor mapping, state calibration, daily path generation, challenger/stress recipes, and disclosure assembly. Keep `orchestrator`, `frontdesk`, `decision_card`, and `goal_solver` as consumers of `ProbabilityEngineRunResult`; do not let them recreate probability semantics locally.

**Tech Stack:** Python 3.12, dataclasses, pytest contract/integration/smoke suites, existing `tinyshare` data providers, existing `v1.3` formal disclosure/evidence bridge surfaces.

---

## File Structure

### New files

- `src/probability_engine/__init__.py`
  - Export stable public entrypoints for the new subsystem.
- `src/probability_engine/contracts.py`
  - Frozen dataclasses and enum-order helpers for `DailyProbabilityEngineInput`, `ProbabilityEngineRunResult`, `FailureArtifact`, schedules, path stats, and disclosure payloads.
- `src/probability_engine/factor_library.py`
  - Factor dictionary, factor series loading, and factor metadata refs.
- `src/probability_engine/factor_mapping.py`
  - Four-stage mapping: prior, holdings look-through, returns regression, shrinkage fusion.
- `src/probability_engine/regime.py`
  - Regime state artifact adapters and transition sampling.
- `src/probability_engine/volatility.py`
  - Factor/product GARCH state updates and Student-t innovation helpers.
- `src/probability_engine/dependence.py`
  - `DependenceProvider` interface plus `FactorLevelDccProvider`.
- `src/probability_engine/jumps.py`
  - Systemic/idiosyncratic jump calibration consumption and per-step application.
- `src/probability_engine/portfolio_policy.py`
  - Daily contribution, withdrawal, rebalance, and cost sequencing.
- `src/probability_engine/recipes.py`
  - Frozen recipe registry for primary/challenger/stress.
- `src/probability_engine/path_generator.py`
  - Scheme B daily `t -> t+1` product-level path engine.
- `src/probability_engine/challengers.py`
  - Scheme C regime-conditioned block bootstrap challenger.
- `src/probability_engine/disclosure_bridge.py`
  - Map internal engine outputs to v1.3-compatible `run_outcome_status`, `resolved_result_category`, `DisclosureDecision`, `EvidenceBundle`, and `product_probability_method`.
- `src/probability_engine/engine.py`
  - Orchestrating façade: mapping → calibration → primary/challenger/stress → disclosure.

### Existing files to modify

- `src/calibration/types.py`
  - Add typed artifacts for factor/regime/jump calibration refs consumed by v1.4.
- `src/calibration/engine.py`
  - Produce the calibrated artifacts required by `probability_engine` instead of owning end-user probability semantics.
- `src/orchestrator/types.py`
  - Replace raw probability payload assumptions with `ProbabilityEngineRunResult`-compatible fields.
- `src/orchestrator/engine.py`
  - Build `DailyProbabilityEngineInput`, call the new engine, and bridge its output into the existing formal surface.
- `src/goal_solver/types.py`
  - Consume `ProbabilityEngineRunResult` summaries instead of running local monthly/bucket fallbacks.
- `src/goal_solver/engine.py`
  - Remove remaining formal truth dependencies on monthly or bucket-level distributions.
- `src/decision_card/types.py`
  - Accept v1.4 output envelope and formal failure artifacts.
- `src/decision_card/builder.py`
  - Render primary/challenger/stress model summaries and strict formal probability fields.
- `src/frontdesk/service.py`
  - Construct v1.4 execution inputs from external formal snapshots and runtime data.
- `src/frontdesk/cli.py`
  - Surface v1.4 model identity, challenger/stress gaps, and formal failure envelopes.

### New tests

- `tests/contract/test_37_v14_probability_engine_contract.py`
  - Contracts for input/output/envelope/dataclass schema.
- `tests/contract/test_38_v14_factor_mapping_contract.py`
  - Mapping confidence, shrinkage, and source ordering.
- `tests/contract/test_39_v14_daily_state_update_contract.py`
  - Frozen `t -> t+1` sequencing and `S_t+1` conditioning rules.
- `tests/contract/test_40_v14_disclosure_bridge_contract.py`
  - `formal_strict_result -> formal_independent_result` bridge, enum ordering, failure envelope behavior.
- `tests/contract/test_41_v14_challenger_stress_contract.py`
  - Challenger/stress role separation and range widening.
- `tests/integration/test_v14_probability_engine_integration.py`
  - Orchestrator/frontdesk/decision-card integration.
- `tests/smoke/test_v14_formal_daily_probability_smoke.py`
  - End-to-end daily product formal path.

### New fixtures

- `tests/fixtures/v14/factor_library_snapshot.json`
- `tests/fixtures/v14/regime_state_snapshot.json`
- `tests/fixtures/v14/jump_state_snapshot.json`
- `tests/fixtures/v14/product_mapping_bundle.json`
- `tests/fixtures/v14/formal_daily_engine_input.json`
- `tests/fixtures/v14/challenger_history_blocks.json`

---

### Task 1: Freeze v1.4 Contracts and Enum Semantics

**Files:**
- Create: `src/probability_engine/__init__.py`
- Create: `src/probability_engine/contracts.py`
- Modify: `src/orchestrator/types.py`
- Modify: `src/decision_card/types.py`
- Test: `tests/contract/test_37_v14_probability_engine_contract.py`

- [ ] **Step 1: Write the failing contract test for the new envelope and enum ordering**

```python
from probability_engine.contracts import (
    DailyProbabilityEngineInput,
    FailureArtifact,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    factor_mapping_confidence_at_least,
    distribution_readiness_at_least,
    calibration_quality_at_least,
)


def test_probability_engine_run_result_failure_requires_null_category():
    result = ProbabilityEngineRunResult(
        run_outcome_status="failure",
        resolved_result_category="null",
        output=None,
        failure_artifact=FailureArtifact(
            failure_stage="preflight",
            failure_code="missing_daily_path",
            message="daily product path unavailable",
            diagnostic_refs=["diag://missing_daily_path"],
            trustworthy_partial_diagnostics=False,
        ),
    )
    assert result.output is None
    assert result.failure_artifact is not None


def test_enum_order_helpers_are_ordinal_not_string_based():
    assert factor_mapping_confidence_at_least("high", "medium") is True
    assert distribution_readiness_at_least("partial", "ready") is False
    assert calibration_quality_at_least("acceptable", "weak") is True
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_37_v14_probability_engine_contract.py -q
```

Expected:

```text
FAILED tests/contract/test_37_v14_probability_engine_contract.py::test_probability_engine_run_result_failure_requires_null_category
ImportError: cannot import name 'ProbabilityEngineRunResult'
```

- [ ] **Step 3: Create the v1.4 contracts module with frozen dataclasses and enum helpers**

```python
from __future__ import annotations

from dataclasses import dataclass, field

FACTOR_MAPPING_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
DISTRIBUTION_READINESS_ORDER = {"not_ready": 0, "partial": 1, "ready": 2}
CALIBRATION_QUALITY_ORDER = {"failed": 0, "weak": 1, "acceptable": 2, "strong": 3}


def _at_least(value: str, minimum: str, ordering: dict[str, int]) -> bool:
    return ordering[value] >= ordering[minimum]


def factor_mapping_confidence_at_least(value: str, minimum: str) -> bool:
    return _at_least(value, minimum, FACTOR_MAPPING_CONFIDENCE_ORDER)


def distribution_readiness_at_least(value: str, minimum: str) -> bool:
    return _at_least(value, minimum, DISTRIBUTION_READINESS_ORDER)


def calibration_quality_at_least(value: str, minimum: str) -> bool:
    return _at_least(value, minimum, CALIBRATION_QUALITY_ORDER)


@dataclass
class FailureArtifact:
    failure_stage: str
    failure_code: str
    message: str
    diagnostic_refs: list[str]
    trustworthy_partial_diagnostics: bool


@dataclass
class ProbabilityEngineOutput:
    primary_result: object
    challenger_results: list[object]
    stress_results: list[object]
    model_disagreement: dict[str, object]
    probability_disclosure_payload: object
    evidence_refs: list[str]


@dataclass
class ProbabilityEngineRunResult:
    run_outcome_status: str
    resolved_result_category: str
    output: ProbabilityEngineOutput | None
    failure_artifact: FailureArtifact | None

    def __post_init__(self) -> None:
        if self.output is None and self.failure_artifact is None:
            raise ValueError("either output or failure_artifact is required")
        if self.output is not None and self.failure_artifact is not None:
            raise ValueError("output and failure_artifact are mutually exclusive")
        if self.output is None and self.resolved_result_category != "null":
            raise ValueError("failure path requires resolved_result_category='null'")
```

- [ ] **Step 4: Wire the new contract types into orchestrator and decision-card type surfaces**

```python
# src/orchestrator/types.py
from probability_engine.contracts import ProbabilityEngineRunResult

@dataclass
class OrchestratorResult:
    ...
    probability_engine_result: ProbabilityEngineRunResult | None = None
```

```python
# src/decision_card/types.py
@dataclass
class DecisionCardBuildInput:
    ...
    probability_engine_result: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 5: Re-run the contract test and fix any dataclass serialization gaps**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_37_v14_probability_engine_contract.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 1**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/probability_engine/__init__.py src/probability_engine/contracts.py src/orchestrator/types.py src/decision_card/types.py tests/contract/test_37_v14_probability_engine_contract.py
git commit -m "feat: add v1.4 probability engine contracts"
```

---

### Task 2: Build Factor Library and Four-Stage Product Mapping

**Files:**
- Create: `src/probability_engine/factor_library.py`
- Create: `src/probability_engine/factor_mapping.py`
- Create: `tests/fixtures/v14/factor_library_snapshot.json`
- Create: `tests/fixtures/v14/product_mapping_bundle.json`
- Test: `tests/contract/test_38_v14_factor_mapping_contract.py`

- [ ] **Step 1: Write the failing factor-mapping test for prior/holdings/returns/shrinkage**

```python
from probability_engine.factor_mapping import build_factor_mapping


def test_factor_mapping_prefers_holdings_and_returns_when_evidence_is_strong(v14_factor_library, v14_product_bundle):
    mapping = build_factor_mapping(
        products=v14_product_bundle.products,
        factor_library=v14_factor_library,
        as_of="2026-04-10",
    )
    nasdaq = next(item for item in mapping if item.product_id == "etf_us_nasdaq")
    assert nasdaq.factor_mapping_source == "blended"
    assert nasdaq.mapping_confidence in {"medium", "high"}
    assert nasdaq.factor_betas["US_EQ_GROWTH"] > 0.8


def test_short_history_product_zeroes_returns_weight(v14_factor_library, v14_product_bundle):
    mapping = build_factor_mapping(
        products=v14_product_bundle.products,
        factor_library=v14_factor_library,
        as_of="2026-04-10",
    )
    new_theme = next(item for item in mapping if item.product_id == "fund_new_theme")
    evidence = {entry["source"]: entry["weight"] for entry in new_theme.factor_mapping_evidence}
    assert evidence["returns"] == 0.0
```

- [ ] **Step 2: Run the mapping test to confirm the feature is missing**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_38_v14_factor_mapping_contract.py -q
```

Expected:

```text
FAILED ... ImportError: cannot import name 'build_factor_mapping'
```

- [ ] **Step 3: Add the factor library snapshot loader and fixed factor dictionary**

```python
FACTOR_NAMES = [
    "CN_EQ_BROAD",
    "CN_EQ_GROWTH",
    "CN_EQ_VALUE",
    "US_EQ_BROAD",
    "US_EQ_GROWTH",
    "HK_EQ_BROAD",
    "CN_RATE_DURATION",
    "CN_CREDIT_SPREAD",
    "GOLD_GLOBAL",
    "USD_CNH",
]


@dataclass
class FactorLibrarySnapshot:
    as_of: str
    factor_names: list[str]
    factor_return_series: dict[str, list[float]]
    source_ref: str
```

- [ ] **Step 4: Implement the four-stage mapping with shrinkage thresholds from the spec**

```python
def build_factor_mapping(products, factor_library, as_of):
    results = []
    for product in products:
        prior_beta = _build_prior_beta(product)
        holdings_beta, holdings_weight = _build_holdings_beta(product)
        returns_beta, returns_weight = _build_returns_beta(product, factor_library)
        raw_beta = _weighted_merge(prior_beta, holdings_beta, returns_beta, holdings_weight, returns_weight)
        anchor_beta = _cluster_anchor_beta(product)
        lambda_i = _mapping_shrinkage_lambda(product, holdings_weight, returns_weight)
        final_beta = _apply_shrinkage(raw_beta, anchor_beta, lambda_i)
        results.append(_build_product_marginal_spec(product, final_beta, prior_beta, holdings_beta, returns_beta, holdings_weight, returns_weight))
    return results
```

- [ ] **Step 5: Add fixture-backed contract tests for short-history and holdings-coverage rules**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_38_v14_factor_mapping_contract.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 2**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/probability_engine/factor_library.py src/probability_engine/factor_mapping.py tests/fixtures/v14/factor_library_snapshot.json tests/fixtures/v14/product_mapping_bundle.json tests/contract/test_38_v14_factor_mapping_contract.py
git commit -m "feat: add v1.4 factor mapping pipeline"
```

---

### Task 3: Implement Calibrated Daily State Artifacts

**Files:**
- Create: `src/probability_engine/regime.py`
- Create: `src/probability_engine/volatility.py`
- Create: `src/probability_engine/dependence.py`
- Create: `src/probability_engine/jumps.py`
- Modify: `src/calibration/types.py`
- Modify: `src/calibration/engine.py`
- Create: `tests/fixtures/v14/regime_state_snapshot.json`
- Create: `tests/fixtures/v14/jump_state_snapshot.json`
- Test: `tests/contract/test_39_v14_daily_state_update_contract.py`

- [ ] **Step 1: Write the failing test for the frozen `t -> t+1` state order**

```python
from probability_engine.volatility import update_garch_state
from probability_engine.dependence import FactorLevelDccProvider


def test_daily_state_update_uses_pre_jump_residuals_only():
    h_next = update_garch_state(
        previous_variance=0.0004,
        pre_jump_residual=-0.01,
        omega=0.00002,
        alpha=0.08,
        beta=0.90,
    )
    assert round(h_next, 8) == round(0.00002 + 0.08 * 0.0001 + 0.90 * 0.0004, 8)


def test_dcc_update_returns_next_correlation_only_for_next_step():
    provider = FactorLevelDccProvider(alpha=0.04, beta=0.93)
    state = provider.initialize(["CN_EQ_BROAD", "GOLD_GLOBAL"], {"long_run_correlation": [[1.0, 0.2], [0.2, 1.0]]})
    next_state = provider.update([1.2, -0.4], state)
    assert provider.current_correlation(next_state)[0][0] == 1.0
```

- [ ] **Step 2: Run the test to confirm state helpers do not exist yet**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py -q
```

Expected:

```text
FAILED ... ImportError
```

- [ ] **Step 3: Implement regime, GARCH, DCC, and jump artifact consumers**

```python
def update_garch_state(previous_variance: float, pre_jump_residual: float, omega: float, alpha: float, beta: float) -> float:
    return omega + alpha * (pre_jump_residual ** 2) + beta * previous_variance


class FactorLevelDccProvider:
    def __init__(self, alpha: float, beta: float) -> None:
        self.alpha = alpha
        self.beta = beta

    def initialize(self, factor_names, state):
        return {"factor_names": factor_names, "q": state["long_run_correlation"], "q_bar": state["long_run_correlation"]}

    def update(self, standardized_factor_residual, prev_state):
        z = np.asarray(standardized_factor_residual, dtype=float)
        q_prev = np.asarray(prev_state["q"], dtype=float)
        q_bar = np.asarray(prev_state["q_bar"], dtype=float)
        q_next = (1 - self.alpha - self.beta) * q_bar + self.alpha * np.outer(z, z) + self.beta * q_prev
        return {"factor_names": prev_state["factor_names"], "q": q_next.tolist(), "q_bar": prev_state["q_bar"]}
```

- [ ] **Step 4: Extend calibration to emit v1.4-ready factor/regime/jump artifacts**

```python
# src/calibration/engine.py
def build_probability_engine_artifacts(...):
    return {
        "factor_dynamics": factor_dynamics_spec,
        "regime_state": regime_state_spec,
        "jump_state": jump_state_spec,
        "artifacts_ready": True,
    }
```

- [ ] **Step 5: Run the state-order contract and update fixtures until it passes**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 3**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/probability_engine/regime.py src/probability_engine/volatility.py src/probability_engine/dependence.py src/probability_engine/jumps.py src/calibration/types.py src/calibration/engine.py tests/fixtures/v14/regime_state_snapshot.json tests/fixtures/v14/jump_state_snapshot.json tests/contract/test_39_v14_daily_state_update_contract.py
git commit -m "feat: add v1.4 calibrated daily state artifacts"
```

---

### Task 4: Implement Scheme B Primary Daily Path Engine

**Files:**
- Create: `src/probability_engine/portfolio_policy.py`
- Create: `src/probability_engine/path_generator.py`
- Create: `src/probability_engine/recipes.py`
- Create: `src/probability_engine/engine.py`
- Create: `tests/fixtures/v14/formal_daily_engine_input.json`
- Test: `tests/contract/test_40_v14_disclosure_bridge_contract.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Write the failing primary path integration test**

```python
from probability_engine.engine import run_probability_engine


def test_primary_recipe_returns_formal_output_for_full_daily_input(v14_formal_daily_input):
    result = run_probability_engine(v14_formal_daily_input)
    assert result.run_outcome_status in {"success", "degraded"}
    assert result.output is not None
    assert result.output.primary_result.recipe_name == "primary_daily_factor_garch_dcc_jump_regime_v1"
```

- [ ] **Step 2: Run the integration test to confirm the engine façade is missing**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/integration/test_v14_probability_engine_integration.py::test_primary_recipe_returns_formal_output_for_full_daily_input -q
```

Expected:

```text
FAILED ... ImportError: cannot import name 'run_probability_engine'
```

- [ ] **Step 3: Implement recipe registry and daily portfolio policy sequencing**

```python
PRIMARY_RECIPE_V14 = SimulationRecipe(
    recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
    role="primary",
    innovation_layer="student_t",
    volatility_layer="factor_and_product_garch",
    dependency_layer="factor_level_dcc",
    jump_layer="systemic_plus_idio",
    regime_layer="markov_regime",
    estimation_basis="daily_product_formal",
    dependency_scope="factor",
    path_count=4000,
)


def apply_daily_cashflows_and_rebalance(portfolio_state, contribution, withdrawal, policy):
    post_return = portfolio_state.after_returns()
    post_contribution = post_return.apply_contribution(contribution)
    post_withdrawal = post_contribution.apply_withdrawal(withdrawal)
    return post_withdrawal.rebalance(policy)
```

- [ ] **Step 4: Implement `t -> t+1` product-level path generation with pre-jump state order**

```python
def simulate_primary_paths(input_data, calibrated_state, recipe):
    paths = []
    for _ in range(recipe.path_count):
        state = _initialize_path_state(input_data, calibrated_state)
        for _day in range(input_data.path_horizon_days):
            state = _advance_one_day(state, calibrated_state, recipe)
        paths.append(state.summary())
    return _summarize_paths(paths)
```

- [ ] **Step 5: Wire the engine façade and produce `ProbabilityEngineRunResult`**

```python
def run_probability_engine(sim_input):
    calibrated = calibrate_probability_state(sim_input)
    primary = run_recipe(calibrated, PRIMARY_RECIPE_V14)
    return ProbabilityEngineRunResult(
        run_outcome_status="success",
        resolved_result_category="formal_strict_result",
        output=ProbabilityEngineOutput(
            primary_result=primary,
            challenger_results=[],
            stress_results=[],
            model_disagreement={},
            probability_disclosure_payload=_base_disclosure_payload(primary),
            evidence_refs=calibrated.evidence_refs,
        ),
        failure_artifact=None,
    )
```

- [ ] **Step 6: Run the integration test until the primary engine produces a typed output**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/integration/test_v14_probability_engine_integration.py::test_primary_recipe_returns_formal_output_for_full_daily_input -q
```

Expected:

```text
1 passed
```

- [ ] **Step 7: Commit Task 4**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/probability_engine/portfolio_policy.py src/probability_engine/path_generator.py src/probability_engine/recipes.py src/probability_engine/engine.py tests/fixtures/v14/formal_daily_engine_input.json tests/integration/test_v14_probability_engine_integration.py
git commit -m "feat: add v1.4 primary daily path engine"
```

---

### Task 5: Add Scheme C Challenger, Stress Recipe, and Disclosure Widening

**Files:**
- Create: `src/probability_engine/challengers.py`
- Create: `src/probability_engine/disclosure_bridge.py`
- Test: `tests/contract/test_41_v14_challenger_stress_contract.py`

- [ ] **Step 1: Write the failing contract test for challenger/stress separation**

```python
from probability_engine.disclosure_bridge import assemble_probability_run_result


def test_challenger_and_stress_widen_range_without_overwriting_primary(v14_primary_result, v14_challenger_result, v14_stress_result):
    run_result = assemble_probability_run_result(
        primary=v14_primary_result,
        challengers=[v14_challenger_result],
        stresses=[v14_stress_result],
        success_event_spec=v14_primary_result.success_event_spec,
    )
    payload = run_result.output.probability_disclosure_payload
    assert payload.published_point == v14_primary_result.success_probability
    assert payload.gap_total >= payload.challenger_gap
    assert run_result.output.challenger_results[0].role == "challenger"
    assert run_result.output.stress_results[0].role == "stress"
```

- [ ] **Step 2: Run the challenger/stress contract to confirm the bridge is missing**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_41_v14_challenger_stress_contract.py -q
```

Expected:

```text
FAILED ... ImportError
```

- [ ] **Step 3: Implement Scheme C regime-conditioned block bootstrap**

```python
def run_challenger_bootstrap(history_matrix, regime_labels, current_regime, block_size, path_count, horizon_days):
    paths = []
    for _ in range(path_count):
        path = _bootstrap_regime_conditioned_blocks(history_matrix, regime_labels, current_regime, block_size, horizon_days)
        paths.append(path)
    return summarize_bootstrap_paths(paths)
```

- [ ] **Step 4: Implement the fixed widening/confidence rules from chapters 6, 23, and 25**

```python
def assemble_probability_run_result(primary, challengers, stresses, success_event_spec):
    p_primary = primary.success_probability
    p_chal_best = max((item.success_probability for item in challengers), key=lambda value: abs(value - p_primary), default=p_primary)
    p_stress = min((item.success_probability for item in stresses), default=p_primary)
    gap_chal = abs(p_primary - p_chal_best)
    gap_stress = max(0.0, p_primary - p_stress)
    gap_total = max(gap_chal, gap_stress)
    published_range = _widen_wilson_interval(primary.success_probability_range, gap_total)
    return _build_run_result(primary, challengers, stresses, published_range, gap_total, success_event_spec)
```

- [ ] **Step 5: Run the challenger/stress contract**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_41_v14_challenger_stress_contract.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit Task 5**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/probability_engine/challengers.py src/probability_engine/disclosure_bridge.py tests/contract/test_41_v14_challenger_stress_contract.py
git commit -m "feat: add v1.4 challenger and stress disclosure bridge"
```

---

### Task 6: Integrate v1.4 into Orchestrator, Frontdesk, Goal Solver, and Decision Card

**Files:**
- Modify: `src/orchestrator/engine.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/frontdesk/cli.py`
- Modify: `src/goal_solver/engine.py`
- Modify: `src/goal_solver/types.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_40_v14_disclosure_bridge_contract.py`
- Test: `tests/smoke/test_v14_formal_daily_probability_smoke.py`

- [ ] **Step 1: Write the failing smoke test for a v1.4 daily formal path from frontdesk**

```python
def test_v14_frontdesk_formal_daily_path_smoke(tmp_path):
    result = run_frontdesk_onboarding_with_v14_daily_engine(tmp_path)
    assert result["run_outcome_status"] in {"success", "degraded"}
    assert result["resolved_result_category"] in {"formal_independent_result", "formal_estimated_result", "degraded_formal_result"}
    assert result["monthly_fallback_used"] is False
    assert result["bucket_fallback_used"] is False
```

- [ ] **Step 2: Run the smoke test to capture current integration failures**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/smoke/test_v14_formal_daily_probability_smoke.py -q
```

Expected:

```text
FAILED ... KeyError or missing v1.4 fields
```

- [ ] **Step 3: Build `DailyProbabilityEngineInput` in orchestrator/frontdesk and call the engine**

```python
# src/orchestrator/engine.py
probability_input = build_daily_probability_engine_input(
    onboarding_profile=profile,
    external_snapshot=external_snapshot,
    runtime_market_data=runtime_market_data,
)
probability_result = run_probability_engine(probability_input)
```

- [ ] **Step 4: Bridge v1.4 output into v1.3-compatible formal surfaces**

```python
orchestrator_result.run_outcome_status = probability_result.run_outcome_status
orchestrator_result.resolved_result_category = bridge_result_category(probability_result.resolved_result_category)
orchestrator_result.disclosure_decision = probability_result.output.probability_disclosure_payload.to_dict() if probability_result.output else {}
orchestrator_result.evidence_bundle = build_probability_evidence_bundle(probability_result)
```

- [ ] **Step 5: Remove remaining formal truth dependencies on monthly/bucket fallbacks**

```python
# src/goal_solver/engine.py
if probability_engine_result is None:
    raise ValueError("v1.4 formal path requires ProbabilityEngineRunResult")
if probability_engine_result.output is None:
    return _degraded_or_failure_surface(...)
```

- [ ] **Step 6: Re-run the smoke test and the disclosure bridge contract**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_40_v14_disclosure_bridge_contract.py tests/smoke/test_v14_formal_daily_probability_smoke.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit Task 6**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/orchestrator/engine.py src/frontdesk/service.py src/frontdesk/cli.py src/goal_solver/engine.py src/goal_solver/types.py src/decision_card/builder.py tests/contract/test_40_v14_disclosure_bridge_contract.py tests/smoke/test_v14_formal_daily_probability_smoke.py
git commit -m "feat: integrate v1.4 engine into formal workflow"
```

---

### Task 7: Lock Regression, Performance Gates, and Claw Surfaces

**Files:**
- Create: `tests/fixtures/v14/challenger_history_blocks.json`
- Modify: `tests/integration/test_openclaw_bridge.py`
- Modify: `tests/smoke/test_frontdesk_cli_smoke.py`
- Create: `tests/contract/test_42_v14_performance_gate_contract.py`
- Modify: `handoff/CODEX_v1.4_daily_product_probability_engine_design_2026-04-09.md` (only if schema names drift during implementation)

- [ ] **Step 1: Write the failing performance/invariance contract**

```python
def test_v14_formal_baseline_stays_daily_and_within_gate(v14_benchmark_input, benchmark):
    result = benchmark(lambda: run_probability_engine(v14_benchmark_input))
    assert result is not None
    assert v14_benchmark_input.path_horizon_days == 756
    assert benchmark.stats.stats.mean < 20.0
```

- [ ] **Step 2: Run the performance contract and capture baseline**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_42_v14_performance_gate_contract.py -q
```

Expected:

```text
FAILED ... benchmark fixture missing or gate not yet wired
```

- [ ] **Step 3: Add fixture-backed Claw-visible fields and performance telemetry**

```python
output.probability_disclosure_payload = ProbabilityDisclosurePayload(
    published_point=published_point,
    published_range=published_range,
    disclosure_level=disclosure_level,
    confidence_level=confidence_level,
    challenger_gap=gap_chal,
    stress_gap=gap_stress,
    gap_total=gap_total,
    widening_method="wilson_plus_gap_total",
)
runtime_telemetry = {
    "path_horizon_days": sim_input.path_horizon_days,
    "path_count_primary": primary_recipe.path_count,
    "path_count_challenger": challenger_recipe.path_count,
    "path_count_stress": stress_recipe.path_count,
}
```

- [ ] **Step 4: Update OpenClaw bridge and frontdesk smoke tests to assert v1.4 fields**

```python
assert payload["product_probability_method"] in {"product_independent_path", "product_estimated_path"}
assert payload["monthly_fallback_used"] is False
assert payload["bucket_fallback_used"] is False
assert "gap_total" in payload["probability_disclosure_payload"]
```

- [ ] **Step 5: Run the full v1.4-focused regression set**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest \
  tests/contract/test_37_v14_probability_engine_contract.py \
  tests/contract/test_38_v14_factor_mapping_contract.py \
  tests/contract/test_39_v14_daily_state_update_contract.py \
  tests/contract/test_40_v14_disclosure_bridge_contract.py \
  tests/contract/test_41_v14_challenger_stress_contract.py \
  tests/contract/test_42_v14_performance_gate_contract.py \
  tests/integration/test_v14_probability_engine_integration.py \
  tests/integration/test_openclaw_bridge.py \
  tests/smoke/test_v14_formal_daily_probability_smoke.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 6: Commit Task 7**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add tests/fixtures/v14/challenger_history_blocks.json tests/integration/test_openclaw_bridge.py tests/smoke/test_frontdesk_cli_smoke.py tests/contract/test_42_v14_performance_gate_contract.py
git commit -m "test: lock v1.4 regression and performance gates"
```

---

## Spec Coverage Check

- `v1.4` daily-only formal path: Task 1, Task 4, Task 6, Task 7
- Scheme B primary: Task 3, Task 4
- Scheme C challenger: Task 5
- Stress recipe: Task 5
- Factor mapping four-stage shrinkage: Task 2
- Frozen `t -> t+1` sequencing and `S_t+1` conditioning: Task 3, Task 4
- `SuccessEventSpec` / horizon source-of-truth / failure envelope: Task 1, Task 6
- v1.3-compatible disclosure/evidence surface: Task 1, Task 5, Task 6
- No monthly/bucket fallback in formal truth: Task 6, Task 7
- Claw-visible fields / evidence / performance gates: Task 7

## Self-Review

- No placeholder steps remain.
- Types referenced in later tasks are defined in earlier tasks:
  - `ProbabilityEngineRunResult` in Task 1
  - `ProductMarginalSpec` mapping output in Task 2
  - calibrated factor/regime/jump artifacts in Task 3
  - `run_probability_engine` in Task 4
  - disclosure bridge in Task 5
- The plan stays inside the existing repository boundaries and introduces a single new subsystem instead of scattering logic.

## Execution Handoff

Plan complete and saved to `handoff/CODEX_v1.4_execution_plan_2026-04-10.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Because you asked me to bring the team, I recommend **Subagent-Driven**. If you want, I’ll proceed on that basis.
