# Goal Solver Model Honesty Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `02 goal_solver` self-describing about modeled probability semantics, historical-backtest boundaries, and not-yet-absorbed goal fields so downstream UX does not overstate what the solver knows.

**Architecture:** Reuse the existing `solver_notes` channel and add a second helper that emits deterministic model-honesty notes from `GoalSolverInput.goal`. Keep this as note-level metadata rather than changing core formulas in this slice.

**Tech Stack:** Python 3, pytest, dataclasses, existing `goal_solver` contracts

---

### Task 1: Add model-honesty contract coverage

**Files:**
- Modify: `tests/contract/test_02_goal_solver_contract.py`
- Modify: `src/goal_solver/engine.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.contract
def test_run_goal_solver_emits_model_honesty_notes(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["goal_amount_basis"] = "real"
    solver_input["goal"]["goal_amount_scope"] = "incremental_gain"
    solver_input["goal"]["tax_assumption"] = "after_tax"
    solver_input["goal"]["fee_assumption"] = "management_fee_plus_transaction_cost"
    solver_input["goal"]["contribution_commitment_confidence"] = 0.66

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.68,
            {"expected_terminal_value": 2_050_000.0},
            RiskSummary(
                max_drawdown_90pct=0.14,
                terminal_value_tail_mean_95=1_550_000.0,
                shortfall_probability=0.32,
                terminal_shortfall_p5_vs_initial=0.08,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(
        note == "probability_model method=parametric_monte_carlo distribution=normal historical_backtest_used=false"
        for note in result.solver_notes
    )
    assert any(
        note == "goal_semantics basis=real scope=incremental_gain tax=after_tax fee=management_fee_plus_transaction_cost"
        for note in result.solver_notes
    )
    assert any(
        note == "contribution_confidence value=0.6600 absorbed_into_solver=false"
        for note in result.solver_notes
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py::test_run_goal_solver_emits_model_honesty_notes -q`
Expected: `FAIL` because none of these note lines exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _append_model_honesty_notes(notes: list[str], inp: GoalSolverInput) -> None:
    notes.append(
        "probability_model "
        "method=parametric_monte_carlo "
        "distribution=normal "
        "historical_backtest_used=false"
    )
    notes.append(
        "goal_semantics "
        f"basis={inp.goal.goal_amount_basis} "
        f"scope={inp.goal.goal_amount_scope} "
        f"tax={inp.goal.tax_assumption} "
        f"fee={inp.goal.fee_assumption}"
    )
    notes.append(
        "contribution_confidence "
        f"value={inp.goal.contribution_commitment_confidence:.4f} "
        "absorbed_into_solver=false"
    )
```

Call this helper from `run_goal_solver(...)` before returning, alongside the existing context-note helper.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py::test_run_goal_solver_emits_model_honesty_notes -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_02_goal_solver_contract.py src/goal_solver/engine.py docs/superpowers/plans/2026-04-01-goal-solver-model-honesty.md
git commit -m "feat: disclose goal solver model semantics"
```

### Task 2: Update backlog and verify regressions

**Files:**
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Update backlog status**

```md
本轮收口：
- probability-model honesty notes
- goal semantics notes
- contribution-confidence not-yet-absorbed note
```

- [ ] **Step 2: Run targeted solver regression**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py tests/contract/test_02_goal_solver_doc_contract.py tests/smoke/test_goal_solver_to_ev_smoke.py -q`
Expected: all selected tests pass

- [ ] **Step 3: Run full regression**

Run: `python3 -m pytest -q`
Expected: full suite passes

## Self-Review

- Spec coverage: this slice targets the roadmap promise to clarify which outputs are modeled probabilities versus not-yet-integrated semantics.
- Placeholder scan: each step names exact files, commands, and note strings.
- Type consistency: no new public types are introduced; this slice extends only `solver_notes`.
