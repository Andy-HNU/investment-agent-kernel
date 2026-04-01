# Phase 1A-1B Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先收口 `Phase 1A (02 + 04/10)` 的剩余语义 gap，再开始 `Phase 1B` 的 `ExecutionPlan -> orchestrator/frontdesk` 正式接线，让当前 kernel 从“桶级建议”推进到“有正式计划落账的双层输出”。

**Architecture:** 这一波分成两条不冲突的主线。`1A` 只处理 `goal_solver` 与 `ev/runtime` 的剩余文档语义，重点补 Monte Carlo/infeasibility notes 与 FeasibilityFilter/reasoning coverage；`1B` 只处理 `ExecutionPlan` 的类型、持久化、frontdesk 可见性和 decision card 摘要，不碰 provider 和 Claw sidecar。所有行为变化先用 contract test 锁定，再做最小实现。

**Tech Stack:** Python 3, pytest, dataclasses, sqlite3, existing orchestrator/frontdesk workflow, git worktree

---

### Task 1: Close the remaining `Phase 1A` goal-solver semantics

**Files:**
- Modify: `src/goal_solver/engine.py`
- Modify: `tests/contract/test_02_goal_solver_contract.py`
- Modify: `tests/contract/test_02_goal_solver_doc_contract.py`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [x] **Step 1: Write the failing tests**

Add contract coverage for:
- Monte Carlo notes disclosing `shrinkage_factor` and parametric limitations together with `paths/seed/horizon`
- no-feasible fallback notes carrying the chosen allocation's dominant infeasibility reasons and fallback score inputs
- lightweight solver path remaining reproducible while the richer notes only affect full solver output

- [x] **Step 2: Run the targeted tests and verify they fail for the expected reason**

Run:
```bash
python3 -m pytest tests/contract/test_02_goal_solver_contract.py -q
python3 -m pytest tests/contract/test_02_goal_solver_doc_contract.py -q
```

Expected:
- At least one new assertion fails because the current solver notes do not yet carry the richer Monte Carlo / infeasibility semantics.

- [x] **Step 3: Implement the minimal code to satisfy the tests**

Implementation scope:
- keep `_run_monte_carlo(...)` stable and deterministic
- enrich `solver_notes` only; do not change output schema
- expose the selected fallback allocation's dominant infeasibility context without turning solver_notes into raw dumps

- [x] **Step 4: Run targeted and adjacent regression**

Run:
```bash
python3 -m pytest tests/contract/test_02_goal_solver_contract.py tests/contract/test_02_goal_solver_doc_contract.py -q
python3 -m pytest tests/smoke/test_goal_solver_to_ev_smoke.py tests/contract/test_10_ev_report_contract.py -q
```

Expected:
- Goal solver contracts pass
- Existing `04/10` smoke and contract suites stay green

- [x] **Step 5: Commit**

```bash
git add src/goal_solver/engine.py tests/contract/test_02_goal_solver_contract.py tests/contract/test_02_goal_solver_doc_contract.py handoff/CODEX_system_doc_gap_backlog.md
git commit -m "feat: deepen goal solver infeasibility semantics"
```

### Task 2: Start `Phase 1B` execution-plan wiring

**Files:**
- Modify: `src/product_mapping/types.py`
- Modify: `src/orchestrator/types.py`
- Modify: `src/orchestrator/engine.py`
- Modify: `src/decision_card/types.py`
- Modify: `src/frontdesk/storage.py`
- Modify: `src/frontdesk/service.py`
- Modify: `tests/contract/test_07_orchestrator_contract.py`
- Modify: `tests/contract/test_11_frontdesk_sqlite_contract.py`
- Create: `tests/contract/test_11_execution_plan_persistence_contract.py`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [x] **Step 1: Write the failing tests**

Add contract coverage for:
- orchestrator persistence containing an `execution_plan` artifact when a non-blocked result has bucket recommendations
- sqlite persistence of `plan_id / plan_version / status / source_run_id`
- frontdesk user state surfacing the latest active execution plan summary separately from execution feedback
- feedback payload retaining the seeded plan reference once a run has an execution plan

- [x] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
python3 -m pytest tests/contract/test_07_orchestrator_contract.py -q
python3 -m pytest tests/contract/test_11_frontdesk_sqlite_contract.py -q
python3 -m pytest tests/contract/test_11_execution_plan_persistence_contract.py -q
```

Expected:
- At least one assertion fails because `ExecutionPlan` is not yet persisted or surfaced through frontdesk state.

- [x] **Step 3: Implement the minimal wiring**

Implementation scope:
- keep product mapping deterministic and versioned
- add execution-plan persistence without breaking existing execution feedback schema
- store plan records as first-class rows, not as note-field hacks
- expose a lightweight execution-plan summary to frontdesk/user-state and preserve backward compatibility for existing feedback consumers

- [x] **Step 4: Run targeted and full regression**

Run:
```bash
python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/contract/test_11_frontdesk_sqlite_contract.py tests/contract/test_11_execution_plan_persistence_contract.py -q
python3 -m pytest tests/contract/test_12_frontdesk_regression.py tests/smoke/test_frontdesk_followup_cli_smoke.py -q
python3 -m pytest -q
```

Expected:
- New execution-plan contracts pass
- Existing frontdesk regression stays green
- Full suite stays green

- [x] **Step 5: Commit**

```bash
git add src/product_mapping/types.py src/orchestrator/types.py src/orchestrator/engine.py src/decision_card/types.py src/frontdesk/storage.py src/frontdesk/service.py tests/contract/test_07_orchestrator_contract.py tests/contract/test_11_frontdesk_sqlite_contract.py tests/contract/test_11_execution_plan_persistence_contract.py handoff/CODEX_system_doc_gap_backlog.md
git commit -m "feat: persist execution plans through frontdesk"
```

### Task 3: Review, regression gate, and roadmap reconciliation

**Files:**
- Modify: `handoff/CODEX_kernel_first_roadmap_2026-04-01.md`
- Modify: `docs/superpowers/plans/2026-04-01-phase1a-1b-execution.md`
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Run independent spec review**

Reviewer checks:
- `1A` closeout matches `system/02_goal_solver.md` and existing `04/10` notes
- `1B` persistence matches `system/11_product_mapping_and_execution_planner_v2.md`
- no new hardcoding or doc drift

- [x] **Step 2: Run independent code-quality and test review**

Tester checks:
- new tests genuinely fail before implementation
- no false-green persistence path
- frontdesk summary/state remains backward compatible

- [x] **Step 3: Reconcile roadmap**

Update roadmap to show:
- `Phase 1A = 02 + 04/10`
- `Phase 1B = execution plan -> 07/09/frontdesk`
- `Phase 1C = 03/05/07`

- [x] **Step 4: Final verification**

Run:
```bash
git status --short
python3 -m pytest -q
git diff --check
```

Expected:
- no unexpected dirty files
- full suite green
- no whitespace / conflict issues
