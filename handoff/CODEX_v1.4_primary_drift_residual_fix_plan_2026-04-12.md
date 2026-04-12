# v1.4 Primary Drift And Residual Variance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the v1.4 primary daily engine so its long-run return center is positive and product idiosyncratic variance is residualized, then keep stress as a downside overlay on that corrected baseline.

**Architecture:** Extend factor dynamics with explicit annual expected returns, convert regime mean shifts into additive deltas around a base drift, compute product idiosyncratic variance from factor residuals, and keep stress as a relative overlay on the corrected primary runtime input.

**Tech Stack:** Python, numpy, pytest, existing probability engine contracts

---

### Task 1: Extend factor dynamics contract with explicit expected return fields

**Files:**
- Modify: `src/probability_engine/volatility.py`
- Test: `tests/contract/test_39_v14_daily_state_update_contract.py`

- [ ] **Step 1: Write the failing contract test**

Add a test that constructs `FactorDynamicsSpec` with:

```python
spec = FactorDynamicsSpec(
    factor_names=["CN_EQ_BROAD"],
    factor_series_ref="observed://factor",
    innovation_family="student_t",
    tail_df=7.0,
    garch_params_by_factor={"CN_EQ_BROAD": {"omega": 1e-6, "alpha": 0.07, "beta": 0.90, "nu": 7.0, "long_run_variance": 1e-4}},
    dcc_params={"alpha": 0.04, "beta": 0.93},
    long_run_covariance={"CN_EQ_BROAD": {"CN_EQ_BROAD": 1e-4}},
    covariance_shrinkage=0.25,
    calibration_window_days=252,
    expected_return_by_factor={"CN_EQ_BROAD": 0.08},
    expected_return_basis="market_assumption_fallback",
)
assert spec.expected_return_by_factor["CN_EQ_BROAD"] == 0.08
assert spec.expected_return_basis == "market_assumption_fallback"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py -k factor_dynamics_expected_return -q
```

Expected: fail because the dataclass does not accept the new fields yet.

- [ ] **Step 3: Implement the contract change**

In `src/probability_engine/volatility.py`, add:

- `expected_return_by_factor: dict[str, float]`
- `expected_return_basis: str`

Normalize and validate them in `__post_init__`.

- [ ] **Step 4: Re-run the focused test**

Run the same pytest command and expect PASS.

- [ ] **Step 5: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add src/probability_engine/volatility.py tests/contract/test_39_v14_daily_state_update_contract.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "feat: add factor expected return contract"
```

### Task 2: Build factor drift in calibration

**Files:**
- Modify: `src/calibration/engine.py`
- Test: `tests/contract/test_39_v14_daily_state_update_contract.py`

- [ ] **Step 1: Write the failing calibration test**

Add a test that builds probability state artifacts from a benign market/factor history and asserts:

- `factor_dynamics.expected_return_by_factor` is non-empty
- at least the broad equity factor has positive annual expected return
- `expected_return_basis` is populated

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py -k factor_drift -q
```

Expected: fail because calibration does not emit factor drift fields yet.

- [ ] **Step 3: Implement calibration**

In `src/calibration/engine.py`:

- add a helper that annualizes observed factor mean returns when enough history exists,
- build a market-anchor expected return by factor,
- blend observed and anchor values with simple shrinkage,
- write the result into `FactorDynamicsSpec.expected_return_by_factor`,
- set `expected_return_basis` accordingly.

- [ ] **Step 4: Re-run the focused test**

Run the same pytest command and expect PASS.

- [ ] **Step 5: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add src/calibration/engine.py tests/contract/test_39_v14_daily_state_update_contract.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "feat: calibrate factor drift baseline"
```

### Task 3: Use base drift plus regime delta in the primary path generator

**Files:**
- Modify: `src/probability_engine/path_generator.py`
- Test: `tests/contract/test_39_v14_daily_state_update_contract.py`

- [ ] **Step 1: Write the failing behavior test**

Add a deterministic test that:

- creates one product with positive factor beta,
- creates factor dynamics with positive expected return and zero shocks,
- simulates a short path,
- asserts terminal value increases above initial value under zero contributions and zero withdrawals.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py -k primary_positive_drift -q
```

Expected: fail because the primary path still uses only residuals plus regime shift.

- [ ] **Step 3: Implement the path generator change**

In `src/probability_engine/path_generator.py`:

- compile daily factor base drift from `expected_return_by_factor`,
- keep regime value as a delta term,
- change factor return generation from:

```python
factor_returns = factor_residuals + mean_shift
```

to:

```python
factor_returns = factor_base_drift_daily + regime_mean_delta + factor_residuals
```

Apply the change in both vectorized and scalar path codepaths.

- [ ] **Step 4: Re-run the focused test**

Run the same pytest command and expect PASS.

- [ ] **Step 5: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add src/probability_engine/path_generator.py tests/contract/test_39_v14_daily_state_update_contract.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "fix: add factor drift to primary path generation"
```

### Task 4: Residualize product idiosyncratic variance

**Files:**
- Modify: `src/orchestrator/engine.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Write the failing test**

Add an integration test that constructs:

- one product with observed returns fully explained by factor beta,
- matching observed factor series,

and assert the product idiosyncratic long-run variance emitted into runtime input is near zero rather than equal to total product variance.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/integration/test_v14_probability_engine_integration.py -k residual_variance -q
```

Expected: fail because long-run variance currently uses total product variance.

- [ ] **Step 3: Implement residual variance**

In `src/orchestrator/engine.py`:

- compute factor-explained daily returns from product factor betas and observed factor series,
- compute residual returns,
- use residual variance for `garch_params["long_run_variance"]`,
- keep a floor to avoid exact zero variance explosions.

- [ ] **Step 4: Re-run the focused test**

Run the same pytest command and expect PASS.

- [ ] **Step 5: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add src/orchestrator/engine.py tests/integration/test_v14_probability_engine_integration.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "fix: residualize product idiosyncratic variance"
```

### Task 5: Keep stress as an overlay on the corrected primary baseline

**Files:**
- Modify: `src/probability_engine/challengers.py`
- Test: `tests/contract/test_41_v14_challenger_stress_contract.py`

- [ ] **Step 1: Write the failing stress relationship test**

Add a test that builds a benign runtime input and asserts:

- primary success probability is finite and positive,
- stress success probability is less than or equal to primary success probability,
- stress does not erase the existence of the base drift contract.

- [ ] **Step 2: Run the test to verify it fails or is incomplete**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_41_v14_challenger_stress_contract.py -k stress_overlay -q
```

Expected: fail or prove the current stress overlay assumptions are incomplete.

- [ ] **Step 3: Implement stress overlay alignment**

In `src/probability_engine/challengers.py`:

- preserve the new factor drift baseline in stressed runtime input,
- only worsen deltas, tail df, volatility, jump, and persistence,
- do not replace the corrected base drift with a separate negative-drift model.

- [ ] **Step 4: Re-run the focused test**

Run the same pytest command and expect PASS.

- [ ] **Step 5: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add src/probability_engine/challengers.py tests/contract/test_41_v14_challenger_stress_contract.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "fix: keep stress as overlay on corrected primary drift"
```

### Task 6: End-to-end verification on the known failing profile

**Files:**
- Modify: `tests/integration/test_v14_probability_engine_integration.py`
- Test: `tests/contract/test_39_v14_daily_state_update_contract.py`
- Test: `tests/contract/test_41_v14_challenger_stress_contract.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Write the failing regression**

Add an integration regression that uses the known user profile class:

- initial assets `18000`
- monthly contribution `2500`
- horizon `36 months`
- target `120000`

and assert:

- primary success probability is materially above zero in benign observed/helper snapshot input,
- challenger remains positive,
- stress remains less than or equal to primary.

- [ ] **Step 2: Run the test to verify it fails on the current code**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/integration/test_v14_probability_engine_integration.py -k benign_profile_regression -q
```

Expected: fail on the current broken primary behavior.

- [ ] **Step 3: Run focused verification**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_39_v14_daily_state_update_contract.py tests/contract/test_41_v14_challenger_stress_contract.py tests/integration/test_v14_probability_engine_integration.py -q
```

Expected: PASS.

- [ ] **Step 4: Run the key formal wiring/regression suites**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_42_v14_formal_daily_wiring_contract.py tests/contract/test_40_v14_disclosure_bridge_contract.py tests/integration/test_openclaw_bridge.py tests/smoke/test_v14_formal_daily_probability_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Check patch cleanliness**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git diff --check
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git -C /root/AndyFtp/investment_system_codex_ready_repo add tests/contract/test_39_v14_daily_state_update_contract.py tests/contract/test_41_v14_challenger_stress_contract.py tests/integration/test_v14_probability_engine_integration.py
git -C /root/AndyFtp/investment_system_codex_ready_repo commit -m "fix: restore credible v1.4 primary return baseline"
```
