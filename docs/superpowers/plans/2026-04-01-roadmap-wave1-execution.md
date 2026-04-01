# Roadmap Wave 1 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `30 loop` 约束下，继续推进 roadmap 的 `Phase 1` 主链，完成 `10/04` 语义硬化，同时起好 `Product Mapping / Execution Planner` 的第一版正式代码骨架，为后续 `03/05` 与 Claw shell 接入铺平接口。

**Architecture:** 这一波只做三条不冲突的子线。主线继续收紧 `ev_engine` 和 `runtime_optimizer` 的语义、过滤和解释链；侧线新增独立的 `product_mapping` 模块，不把产品层逻辑硬塞进 solver；独立 review/test 子线专门做 roadmap 对齐、硬编码排查和回归矩阵，防止“代码能跑、语义走偏”。

**Tech Stack:** Python 3, pytest, dataclasses, existing orchestrator/frontdesk workflow, git worktree

---

### Task 1: Harden `10 ev_engine` and `04 runtime_optimizer`

**Files:**
- Modify: `src/runtime_optimizer/ev_engine/engine.py`
- Modify: `src/runtime_optimizer/engine.py`
- Modify: `src/runtime_optimizer/candidates.py`
- Modify: `tests/contract/test_10_ev_report_contract.py`
- Modify: `tests/contract/test_04_runtime_optimizer_contract.py`
- Modify: `tests/smoke/test_goal_solver_to_ev_smoke.py`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Write the failing tests**

Add focused contract tests for:
- `recommendation_reason` when the top action wins because risk/execution penalties are lower rather than raw goal impact alone
- `confidence_reason` when ranking spread is narrow and candidate set is mixed between safe actions and active actions
- quarterly / event mode candidate filtering so `ADD_DEFENSE` only appears on the intended path and safe-action fallback stays explainable

- [ ] **Step 2: Run the targeted tests and verify they fail for the expected reason**

Run:
```bash
python3 -m pytest tests/contract/test_10_ev_report_contract.py -q
python3 -m pytest tests/contract/test_04_runtime_optimizer_contract.py -q
python3 -m pytest tests/smoke/test_goal_solver_to_ev_smoke.py -q
```

Expected:
- At least one new assertion fails because the current reason-generation / confidence semantics are still too coarse.

- [ ] **Step 3: Implement the minimal semantics to satisfy the tests**

Implementation scope:
- tighten `FeasibilityFilter` coverage without changing the public result shape
- make `_generate_reason(...)` and `_build_confidence(...)` consume the real winning dimensions instead of generic text
- keep `candidate_poverty` and safe-action degradation stable for orchestrator consumers

- [ ] **Step 4: Run targeted and full regression**

Run:
```bash
python3 -m pytest tests/contract/test_10_ev_report_contract.py tests/contract/test_04_runtime_optimizer_contract.py tests/smoke/test_goal_solver_to_ev_smoke.py -q
python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/contract/test_09_decision_card_contract.py -q
python3 -m pytest -q
```

Expected:
- All targeted suites pass
- Full suite stays green

- [ ] **Step 5: Commit**

```bash
git add src/runtime_optimizer/ev_engine/engine.py src/runtime_optimizer/engine.py src/runtime_optimizer/candidates.py tests/contract/test_10_ev_report_contract.py tests/contract/test_04_runtime_optimizer_contract.py tests/smoke/test_goal_solver_to_ev_smoke.py handoff/CODEX_system_doc_gap_backlog.md
git commit -m "feat: harden ev reasoning and runtime semantics"
```

### Task 2: Create the first `Product Mapping / Execution Planner` skeleton

**Files:**
- Create: `src/product_mapping/__init__.py`
- Create: `src/product_mapping/types.py`
- Create: `src/product_mapping/catalog.py`
- Create: `src/product_mapping/engine.py`
- Create: `tests/contract/test_11_product_mapping_contract.py`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Write the failing contract tests**

Add tests that require:
- a typed `ProductCandidate`
- a typed `ExecutionPlan`
- bucket-to-product mapping for at least `equity_cn`, `bond_cn`, `gold`, and `cash/liquidity`
- natural-language restrictions like `不碰股票` and `只接受黄金和现金` to prune product candidates
- alternate products to be surfaced rather than hidden

- [ ] **Step 2: Run the new product mapping tests and verify they fail**

Run:
```bash
python3 -m pytest tests/contract/test_11_product_mapping_contract.py -q
```

Expected:
- `FAIL` because the `product_mapping` module does not exist yet.

- [ ] **Step 3: Implement the minimal module skeleton**

Implementation scope:
- `types.py` defines `ProductCandidate`, `ExecutionPlanItem`, `ExecutionPlan`
- `catalog.py` ships a small built-in catalog for first-wave product families
- `engine.py` exposes a deterministic `build_execution_plan(...)` entry point
- the first version remains standalone and does not yet rewrite orchestrator/frontdesk flows

- [ ] **Step 4: Run contract regression**

Run:
```bash
python3 -m pytest tests/contract/test_11_product_mapping_contract.py -q
python3 -m pytest tests/contract/test_09_product_feedback_regression.py tests/contract/test_11_frontdesk_sqlite_contract.py -q
```

Expected:
- New product-mapping contract passes
- Existing feedback/storage contracts remain green

- [ ] **Step 5: Commit**

```bash
git add src/product_mapping/__init__.py src/product_mapping/types.py src/product_mapping/catalog.py src/product_mapping/engine.py tests/contract/test_11_product_mapping_contract.py handoff/CODEX_system_doc_gap_backlog.md
git commit -m "feat: add product mapping execution planner skeleton"
```

### Task 3: Independent review and regression gate

**Files:**
- Review: current branch diff
- Review: `handoff/CODEX_kernel_first_roadmap_2026-04-01.md`
- Review: `system/11_product_mapping_and_execution_planner_v2.md`
- Review: `system/13_policy_news_structured_signal_contract_v2.md`

- [ ] **Step 1: Run independent spec-compliance review**

Reviewer checks:
- roadmap vs code delta
- hardcoded assumptions or doc drift
- unsafe shortcuts in new semantics

- [ ] **Step 2: Run independent test review**

Tester checks:
- targeted test matrix covers the changed semantics
- no false-green path from missing assertions
- randomized / natural-language regression remains protected

- [ ] **Step 3: Record findings before integration**

If findings exist:
- fix them before merge
- re-run the exact proving command

If no findings:
- note the review outcome in the controller summary

### Task 4: Integration checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-04-01-roadmap-wave1-execution.md`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Reconcile the branch against roadmap**

Check:
- which `Phase 1` bullets are now closed
- which ones remain for the next wave
- whether `Task 2` is ready to be wired into orchestrator/frontdesk in the next slice

- [ ] **Step 2: Run final verification for the wave**

Run:
```bash
git status --short
python3 -m pytest -q
```

Expected:
- no unexpected dirty files
- full suite passes

- [ ] **Step 3: Prepare the next-wave handoff**

Update:
- completed bullets
- residual risks
- next concrete code slice
