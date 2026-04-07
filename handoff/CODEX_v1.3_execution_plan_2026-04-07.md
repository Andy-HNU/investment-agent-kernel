# CODEX v1.3 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the `v1.3` credibility upgrade from the approved task map, in gate order, until the formal compute path, disclosure policy, probability engine, and runtime validation are all wired into production code and tests.

**Architecture:** Land `Gate 1` first as shared contracts and end-to-end surfaced fields, then harden `Gate 2` to remove formal fallback and emit structured failure artifacts, then upgrade `Package 3` modeling/disclosure, and finally optimize `Package 4` runtime reuse and invariance checks. New semantics must be encoded in shared types and emitted consistently through goal solver, product mapping, orchestrator, decision card, frontdesk storage, CLI, and OpenClaw-facing outputs.

**Tech Stack:** Python 3.10+, dataclasses, pytest contracts/smoke/integration, SQLite-backed frontdesk state, tinyshare/Tushare runtime data.

---

## Task 1: Gate 1 Core Contracts

**Files:**
- Modify: `src/shared/audit.py`
- Modify: `src/shared/__init__.py`
- Modify: `src/goal_solver/types.py`
- Modify: `src/decision_card/types.py`
- Test: `tests/contract/test_28_v13_gate1_contract.py`

Implement shared types/enums for:
- `RunOutcomeStatus`
- `CoverageSummary` normalization
- `DisclosureDecision`
- `EvidenceBundle`
- `SuccessEventSpec`
- `FormalEstimatedResultSpec`
- `ConfidenceDerivationPolicy`
- `SecondaryCompanionArtifact`

Gate 1 rules to encode:
- formal run categories exclude `exploratory_result`
- `formal_path_status` is compatibility-only alias of `run_outcome_status`
- all coverage fields use `0.0-1.0`
- `product_probability_method` is normalized, not free text

## Task 2: Gate 1 Pipeline Surfacing

**Files:**
- Modify: `src/orchestrator/types.py`
- Modify: `src/orchestrator/engine.py`
- Modify: `src/goal_solver/engine.py`
- Modify: `src/decision_card/builder.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/frontdesk/storage.py`
- Modify: `src/frontdesk/cli.py`
- Test: `tests/contract/test_29_v13_gate1_surface_contract.py`
- Test: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

Wire Gate 1 contracts into the live pipeline:
- resolve `run_outcome_status` and `resolved_result_category`
- emit `DisclosureDecision`
- persist `EvidenceBundle`
- surface normalized fields in decision card, frontdesk payloads, and CLI
- preserve legacy aliases only where required

## Task 3: Gate 2 Formal Path Hardening

**Files:**
- Modify: `src/frontdesk/service.py`
- Modify: `src/product_mapping/runtime_inputs.py`
- Modify: `src/product_mapping/engine.py`
- Modify: `src/goal_solver/engine.py`
- Modify: `src/shared/providers/tinyshare.py`
- Test: `tests/contract/test_30_v13_gate2_formal_path_contract.py`
- Test: `tests/contract/test_18_formal_path_contract.py`
- Test: `tests/contract/test_20_tinyshare_runtime_contract.py`

Remove formal-path fallback and add structured failure:
- no synthetic fallback allocation in formal path
- no builtin catalog fallback for formal runtime universe
- no silent `product_independent -> product_proxy` fallback
- no silent advanced-mode -> static Gaussian fallback
- add `FailureArtifact`
- add preflight validation and closed `failed_stage` vocabulary

## Task 4: Package 3 Mode Eligibility And Product Probability Contracts

**Files:**
- Modify: `src/calibration/types.py`
- Modify: `src/calibration/engine.py`
- Modify: `src/goal_solver/types.py`
- Modify: `src/goal_solver/engine.py`
- Modify: `src/product_mapping/types.py`
- Modify: `src/product_mapping/engine.py`
- Test: `tests/contract/test_31_v13_mode_eligibility_contract.py`
- Test: `tests/contract/test_23_product_simulation_contract.py`

Implement:
- `SimulationModeEligibility`
- `ModeResolutionDecision`
- `DistributionModelState` eligibility metadata
- normalized `product_probability_method`
- explicit `estimation_basis`
- `formal_estimated_result` as a first-class result class, not a fallback bucket

## Task 5: Package 3 Probability / Return Disclosure Upgrade

**Files:**
- Modify: `src/goal_solver/types.py`
- Modify: `src/goal_solver/engine.py`
- Modify: `src/decision_card/builder.py`
- Modify: `src/frontdesk/cli.py`
- Test: `tests/contract/test_32_v13_probability_disclosure_contract.py`
- Test: `tests/contract/test_26_probability_explanation_v2_contract.py`

Implement:
- `SuccessEventSpec` propagation through solver and explanations
- `ExpectedReturnDecomposition` with `decomposition_basis`, `additivity_convention`, and residual
- range/point disclosure gating from `DisclosureDecision`
- confidence derivation from closed inputs only

## Task 6: Package 3 Calibration Engine

**Files:**
- Modify: `src/calibration/engine.py`
- Modify: `src/calibration/types.py`
- Modify: `src/frontdesk/storage.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_33_v13_calibration_contract.py`

Implement:
- `CalibrationSummary`
- bucketed reliability outputs
- regime-sliced calibration
- confidence downgrade and range widening from weak calibration
- `diagnostic_only` downgrade when calibration evidence is insufficient

## Task 7: Package 4 Runtime Reuse And Evidence Invariance

**Files:**
- Modify: `src/frontdesk/storage.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/orchestrator/engine.py`
- Modify: `src/shared/providers/tinyshare.py`
- Test: `tests/contract/test_34_v13_evidence_invariance_contract.py`
- Test: `tests/contract/test_27_frontdesk_state_compaction_contract.py`

Implement:
- snapshot reuse with versioned signatures
- `EvidenceInvarianceReport`
- semantic refs vs artifact refs
- runtime telemetry fields
- A/B/C/D style reuse without changing semantic outputs

## Task 8: Package 4 Claw Regression Surface

**Files:**
- Modify: `src/decision_card/builder.py`
- Modify: `src/frontdesk/cli.py`
- Modify: `integration/openclaw/contracts/bridge_contract.md`
- Test: `tests/integration/test_openclaw_bridge.py`
- Test: `tests/smoke/test_frontdesk_cli_smoke.py`
- Test: `tests/smoke/test_21_openclaw_layer3_bridge_smoke.py`

Finalize Claw-facing contract:
- emit `run_outcome_status`
- emit `resolved_result_category`
- emit normalized `product_probability_method`
- expose gate/package-required evidence fields
- prevent companion/exploratory artifacts from being treated as formal truth

## Task 9: End-to-End Verification

**Files:**
- Modify if needed: whichever files fail verification
- Test: targeted contract suites
- Test: smoke and integration suites

Run:
- `python3 -m pytest tests/contract/test_28_v13_gate1_contract.py tests/contract/test_29_v13_gate1_surface_contract.py tests/contract/test_30_v13_gate2_formal_path_contract.py tests/contract/test_31_v13_mode_eligibility_contract.py tests/contract/test_32_v13_probability_disclosure_contract.py tests/contract/test_33_v13_calibration_contract.py tests/contract/test_34_v13_evidence_invariance_contract.py -q`
- `python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py tests/contract/test_18_formal_path_contract.py tests/contract/test_20_tinyshare_runtime_contract.py tests/contract/test_23_product_simulation_contract.py tests/contract/test_26_probability_explanation_v2_contract.py tests/smoke/test_frontdesk_cli_smoke.py tests/smoke/test_21_openclaw_layer3_bridge_smoke.py tests/integration/test_openclaw_bridge.py -q`
- `python3 -m pytest -q`
- `git diff --check`

Success requires:
- all new contract tests green
- no legacy alias drift
- no formal-path fallback remaining in strict execution path
- no dirty worktree
