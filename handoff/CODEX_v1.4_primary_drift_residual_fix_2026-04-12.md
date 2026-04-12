# CODEX v1.4 Primary Drift And Residual Variance Fix

Date: 2026-04-12
Scope: v1.4 daily product probability engine
Status: design approved in chat, written for implementation control

## Goal

Repair the `primary_daily_factor_garch_dcc_jump_regime_v1` path so that:

- primary uses a positive long-run return baseline instead of zero/negative drift,
- regime mean adjustments act as deltas around that baseline,
- product idiosyncratic volatility is based on residual variance rather than total product variance,
- stress remains a downside overlay on the corrected primary baseline instead of a separate negative-drift world.

## Problem Statement

The current `primary` path produces results that are materially inconsistent with the repaired `challenger` path:

- primary success probability is approximately `0`,
- challenger success probability is approximately `0.96875`,
- the same user profile, cashflows, product set, horizon, and success gate are used.

The dominant cause is not target difficulty or missing cashflow wiring. The dominant cause is that the primary engine currently builds factor returns as:

`factor residuals + regime mean shift`

where regime mean shift is:

- `normal = 0.0`
- `risk_off = -0.0005`
- `stress = -0.0012`

This means the model lacks a positive expected return baseline and behaves like a zero/negative drift risk process.

The secondary cause is that product idiosyncratic GARCH state currently uses total product variance instead of factor-residual variance, so factor risk and product residual risk can be double-counted.

## Repair Principles

1. Do not change the formal success gate in this patch.
2. Do not change challenger semantics except where stress depends on shared contracts.
3. Do not change contribution, withdrawal, or rebalancing semantics in this patch.
4. Fix the source of pessimism in the primary path instead of weakening the acceptance criteria.

## Design

### 1. Add explicit factor drift baseline

`FactorDynamicsSpec` must gain an explicit positive expected return layer.

New fields:

- `expected_return_by_factor: dict[str, float]`
- `expected_return_basis: str`

Semantics:

- Values are annualized factor expected returns.
- `expected_return_basis` documents how the numbers were built, for example:
  - `observed_plus_market_shrinkage`
  - `market_assumption_fallback`

The primary path generator must convert these annualized values into daily drift before sampling daily factor returns.

### 2. Reinterpret regime mean as delta, not total mean

Current regime mean adjustment is treated as the full mean. This patch freezes new semantics:

`factor_return_t+1 = base_drift_daily + regime_mean_delta + factor_residual_t+1`

where:

- `base_drift_daily` comes from `expected_return_by_factor`
- `regime_mean_delta` is a small additive adjustment around baseline
- `factor_residual_t+1` remains the GARCH/DCC/Student-t innovation term

`normal` should no longer imply zero total drift. It should imply baseline drift plus a near-zero delta.

### 3. Build factor drift from observed data with shrinkage

Calibration must compute annualized factor drift using a stable rule:

1. Compute observed annualized mean return from factor history when enough history exists.
2. Compute market-assumption anchor from the product universe / market assumptions layer.
3. Blend them using shrinkage based on sample quality.

The required output is not a perfect factor risk premium model. The goal of this patch is to restore a credible positive long-run center in primary paths.

Minimum acceptable logic:

- if observed factor history is sufficient, blend observed mean with market anchor
- if insufficient, use market anchor directly
- clamp obviously pathological outputs

### 4. Residualize product idiosyncratic variance

Current product GARCH variance is initialized from total product variance. This patch changes it to:

`idio_variance = Var(product_return - factor_explained_return)`

where:

- `factor_explained_return` is computed from observed factor series and product factor betas
- `idio_variance` becomes the long-run variance for product idiosyncratic GARCH

This prevents factor risk from being counted both in the factor component and the product residual component.

### 5. Keep stress as a relative overlay

Stress must inherit the corrected primary baseline and then worsen it.

Stress may still:

- lower `tail_df`
- increase volatility multipliers
- increase risk-off / stress persistence
- increase jump probabilities and dispersion
- apply more negative regime deltas

Stress may not:

- erase the existence of base drift,
- redefine the primary world into a zero/negative long-run return process from first principles.

## Expected Behavioral Change

After this patch:

- `primary` should no longer collapse to a near-zero success probability in benign observed/helper formal scenarios where challenger remains strongly positive.
- `primary` and `challenger` may still differ, but they should no longer disagree by nearly the full probability mass.
- `stress` should remain more pessimistic than `primary`, but should do so as an overlay on the same corrected baseline.

## Files In Scope

- `src/probability_engine/volatility.py`
- `src/calibration/engine.py`
- `src/orchestrator/engine.py`
- `src/probability_engine/path_generator.py`
- `src/probability_engine/challengers.py`
- `tests/contract/test_39_v14_daily_state_update_contract.py`
- `tests/contract/test_41_v14_challenger_stress_contract.py`
- `tests/integration/test_v14_probability_engine_integration.py`

## Verification Requirements

The patch is not complete until all of the following are true:

1. New tests prove `primary` uses positive factor drift in benign inputs.
2. New tests prove product idiosyncratic long-run variance is derived from residual variance, not total variance.
3. New tests prove `stress_success_probability <= primary_success_probability`.
4. The existing formal daily wiring and integration tests continue to pass.
5. Re-running the known user profile no longer produces `primary = 0` while `challenger ~= 0.97`.

## Non-Goals

- No redesign of success event semantics.
- No challenger regime rewrite in this patch.
- No new model family.
- No UI copy changes beyond naturally updated numeric outputs.
