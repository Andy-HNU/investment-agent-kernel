# Target-Risk Frontier Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `v1.2` patch support for target-return-priority, drawdown-priority, and balanced-tradeoff scenarios with user-visible explanations and sanity guards.

**Architecture:** Extend the existing goal-solver candidate outputs into a formal frontier analysis layer, surface it in the decision card/frontdesk payloads, and wire the same analysis into Claw explainability and natural-language routes. Keep the patch additive and backward-compatible with existing `recommended` and `highest_probability` behaviors.

**Tech Stack:** Python, pytest, existing `goal_solver`, `decision_card`, `frontdesk`, and `integration/openclaw` modules

---

### Task 1: Add Kernel Frontier Types

**Files:**
- Modify: `src/goal_solver/types.py`
- Test: `tests/contract/test_02_goal_solver_contract.py`

- [ ] **Step 1: Write the failing test**

Add a contract test that builds a solver output and asserts a new `frontier_analysis` object can hold:
- `recommended`
- `highest_probability`
- `target_return_priority`
- `drawdown_priority`
- `balanced_tradeoff`

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py -q`
Expected: FAIL on missing `FrontierScenario` / `FrontierAnalysis` support.

- [ ] **Step 3: Write minimal implementation**

Add dataclasses/types for `FrontierScenario` and `FrontierAnalysis`, and hang `frontier_analysis: dict[str, Any] | None` off the goal solver output structure.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py -q`
Expected: PASS for the new frontier type coverage.

- [ ] **Step 5: Commit**

```bash
git add src/goal_solver/types.py tests/contract/test_02_goal_solver_contract.py
git commit -m "feat: add target-risk frontier types"
```

### Task 2: Build Frontier Analysis in Goal Solver

**Files:**
- Modify: `src/goal_solver/engine.py`
- Test: `tests/contract/test_02_goal_solver_contract.py`

- [ ] **Step 1: Write the failing tests**

Add tests covering:
- recommended and highest-probability scenarios
- target-return-priority scenario choosing the candidate closest to the required annual return
- drawdown-priority scenario choosing the candidate with the lowest drawdown among feasible options
- balanced-tradeoff scenario choosing a middle point
- missing scenarios returning `None` with blocker notes

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py -q`
Expected: FAIL on missing frontier builder behavior.

- [ ] **Step 3: Write minimal implementation**

Implement helper functions in `src/goal_solver/engine.py` that:
- compute frontier scenarios from `all_results`
- compare against `implied_required_annual_return`
- compare against risk summary `max_drawdown_90pct`
- attach `frontier_analysis` to goal solver output
- avoid hard-coding user-specific thresholds beyond existing constraints and current result metrics

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py -q`
Expected: PASS on frontier selection logic.

- [ ] **Step 5: Commit**

```bash
git add src/goal_solver/engine.py tests/contract/test_02_goal_solver_contract.py
git commit -m "feat: build target-risk frontier analysis"
```

### Task 3: Add Sanity Guards for Pseudo-Improvement Suggestions

**Files:**
- Modify: `src/frontdesk/service.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing tests**

Add regression cases where:
- `current_assets + deterministic contributions >= goal_amount`
- the system must not suggest “extend horizon” or “increase contributions” as meaningful improvement paths

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -q`
Expected: FAIL because current goal alternative generation still leaks pseudo-improvements.

- [ ] **Step 3: Write minimal implementation**

Add a guard in frontdesk/decision-card alternative generation that:
- detects deterministic contribution coverage
- suppresses pseudo-improvement alternatives
- emits a note indicating the target is already covered by principal plus deterministic contributions

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/frontdesk/service.py src/decision_card/builder.py tests/contract/test_12_frontdesk_regression.py
git commit -m "fix: block pseudo-improvement alternatives"
```

### Task 4: Surface Frontier Analysis in Decision Card

**Files:**
- Modify: `src/decision_card/types.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_09_decision_card_contract.py`

- [ ] **Step 1: Write the failing tests**

Add decision-card assertions for:
- `frontier_analysis`
- `why_not_target_return_priority`
- `why_not_drawdown_priority`
- explicit rendering of recommended vs highest probability
- consistent handling when recommended equals highest probability

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -q`
Expected: FAIL because these fields are not yet present.

- [ ] **Step 3: Write minimal implementation**

Update builder/types to:
- map frontier scenarios into card payload
- expose labels and percentages for each scenario
- explain scenario equality/differences in plain language

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/decision_card/types.py src/decision_card/builder.py tests/contract/test_09_decision_card_contract.py
git commit -m "feat: surface target-risk frontier in decision cards"
```

### Task 5: Expose Frontier Analysis Through Frontdesk

**Files:**
- Modify: `src/frontdesk/service.py`
- Modify: `src/frontdesk/cli.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing tests**

Add frontdesk tests that assert onboarding/show-user/status payloads include frontier fields and scenario summaries.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -q`
Expected: FAIL on missing frontier data in frontdesk responses.

- [ ] **Step 3: Write minimal implementation**

Thread `frontier_analysis` into the service payload and CLI rendering.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/frontdesk/service.py src/frontdesk/cli.py tests/contract/test_12_frontdesk_regression.py
git commit -m "feat: expose frontier analysis through frontdesk"
```

### Task 6: Extend Claw Explainability and Routing

**Files:**
- Modify: `src/agent/explainability.py`
- Modify: `src/agent/nli_router.py`
- Modify: `src/integration/openclaw/bridge.py`
- Test: `tests/agent/test_19_claw_shell_contract.py`

- [ ] **Step 1: Write the failing tests**

Add agent tests for:
- “如果我坚持 8% 年化，回撤会是多少”
- “如果我坚持回撤不超过 8%，收益率能到多少”
- “为什么推荐方案不是最高概率方案”
- “为什么推荐方案和最高概率方案是同一个”

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agent/test_19_claw_shell_contract.py -q`
Expected: FAIL because the router/bridge/explainability layer lacks the new intent/explanation.

- [ ] **Step 3: Write minimal implementation**

Add/extend an explainability path for target-risk tradeoff so the bridge can return structured scenario comparisons and rationale.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agent/test_19_claw_shell_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/explainability.py src/agent/nli_router.py src/integration/openclaw/bridge.py tests/agent/test_19_claw_shell_contract.py
git commit -m "feat: explain target-risk tradeoffs in claw shell"
```

### Task 7: Run Targeted Verification

**Files:**
- Test: `tests/contract/test_02_goal_solver_contract.py`
- Test: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`
- Test: `tests/agent/test_19_claw_shell_contract.py`

- [ ] **Step 1: Run kernel and UI regressions**

Run:
```bash
python3 -m pytest \
  tests/contract/test_02_goal_solver_contract.py \
  tests/contract/test_09_decision_card_contract.py \
  tests/contract/test_12_frontdesk_regression.py \
  tests/agent/test_19_claw_shell_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:
```bash
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "test: verify target-risk frontier patch"
```

