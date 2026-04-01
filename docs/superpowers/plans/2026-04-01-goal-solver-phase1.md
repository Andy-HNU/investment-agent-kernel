# Goal Solver Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten `02 goal_solver` so its Monte Carlo context, threshold-gap semantics, and no-feasible fallback explanations match the roadmap/spec intent instead of leaving frontdesk to infer them.

**Architecture:** Keep the existing Monte Carlo core and candidate ranking logic intact. Add deterministic note-building helpers around `run_goal_solver(...)` so the solver emits enough machine-readable context for downstream cards and audits, then extend infeasibility fallback scoring with a compact summary of dominant violation pressure.

**Tech Stack:** Python 3, pytest, dataclasses, existing `goal_solver` module contracts

---

### Task 1: Add solver context note coverage

**Files:**
- Modify: `tests/contract/test_02_goal_solver_contract.py`
- Modify: `src/goal_solver/engine.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.contract
def test_run_goal_solver_emits_context_and_threshold_gap_notes(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["goal"]["success_prob_threshold"] = 0.72
    solver_input["solver_params"]["n_paths"] = 321
    solver_input["solver_params"]["seed"] = 11
    solver_input["candidate_allocations"] = [
        {
            "name": "steady",
            "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            "complexity_score": 0.12,
            "description": "steady candidate",
        }
    ]

    def _fake_run_monte_carlo(*_args, **_kwargs):
        return (
            0.64,
            {"expected_terminal_value": 2_150_000.0},
            RiskSummary(
                max_drawdown_90pct=0.11,
                terminal_value_tail_mean_95=1_600_000.0,
                shortfall_probability=0.36,
                terminal_shortfall_p5_vs_initial=0.07,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(note == "monte_carlo paths=321 seed=11 horizon_months=36" for note in result.solver_notes)
    assert any(
        note == "success_threshold threshold=0.7200 recommended=0.6400 gap=0.0800 met=false"
        for note in result.solver_notes
    )
    assert any(note == "warning=success_probability_below_threshold threshold=0.7200 recommended=0.6400" for note in result.solver_notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py::test_run_goal_solver_emits_context_and_threshold_gap_notes -q`
Expected: `FAIL` because the new `monte_carlo ...` and `success_threshold ...` notes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _append_solver_context_notes(
    notes: list[str],
    inp: GoalSolverInput,
    cashflow_schedule: list[float],
    recommended_result: SuccessProbabilityResult,
) -> None:
    notes.append(
        "monte_carlo "
        f"paths={inp.solver_params.n_paths} "
        f"seed={inp.solver_params.seed} "
        f"horizon_months={inp.goal.horizon_months}"
    )
    threshold_gap = inp.goal.success_prob_threshold - recommended_result.success_probability
    notes.append(
        "success_threshold "
        f"threshold={inp.goal.success_prob_threshold:.4f} "
        f"recommended={recommended_result.success_probability:.4f} "
        f"gap={abs(threshold_gap):.4f} "
        f"met={'true' if threshold_gap <= 0 else 'false'}"
    )
```

Call this helper from `run_goal_solver(...)` after `best_result` is selected and before returning `GoalSolverOutput`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py::test_run_goal_solver_emits_context_and_threshold_gap_notes -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_02_goal_solver_contract.py src/goal_solver/engine.py docs/superpowers/plans/2026-04-01-goal-solver-phase1.md
git commit -m "feat: add goal solver context notes"
```

### Task 2: Add no-feasible fallback pressure summaries

**Files:**
- Modify: `tests/contract/test_02_goal_solver_doc_contract.py`
- Modify: `src/goal_solver/engine.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.contract
def test_run_goal_solver_summarizes_no_feasible_pressure(goal_solver_input_base, monkeypatch):
    solver_input = deepcopy(goal_solver_input_base)
    solver_input["constraints"]["max_drawdown_tolerance"] = 0.05
    solver_input["constraints"]["liquidity_reserve_min"] = 0.40
    solver_input["candidate_allocations"] = [
        {
            "name": "too_risky_a",
            "weights": {"equity_cn": 0.82, "bond_cn": 0.08, "gold": 0.05, "satellite": 0.05},
            "complexity_score": 0.40,
            "description": "violates drawdown and liquidity",
        },
        {
            "name": "too_risky_b",
            "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
            "complexity_score": 0.30,
            "description": "violates drawdown and liquidity less severely",
        },
    ]

    def _fake_run_monte_carlo(weights, *_args, **_kwargs):
        drawdown = 0.18 if weights["equity_cn"] > 0.75 else 0.12
        probability = 0.61 if weights["equity_cn"] > 0.75 else 0.58
        return (
            probability,
            {"expected_terminal_value": 2_300_000.0},
            RiskSummary(
                max_drawdown_90pct=drawdown,
                terminal_value_tail_mean_95=1_700_000.0,
                shortfall_probability=1.0 - probability,
                terminal_shortfall_p5_vs_initial=0.10,
            ),
        )

    monkeypatch.setattr(goal_solver_engine, "_run_monte_carlo", _fake_run_monte_carlo)

    result = run_goal_solver(solver_input)

    assert any(note == "warning=no_feasible_allocation" for note in result.solver_notes)
    assert any(note.startswith("fallback_dominant_constraints ") for note in result.solver_notes)
    assert any(note.startswith("fallback_pressure_score allocation=too_risky_b") for note in result.solver_notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_doc_contract.py::test_run_goal_solver_summarizes_no_feasible_pressure -q`
Expected: `FAIL` because the solver currently emits only the generic fallback notes.

- [ ] **Step 3: Write minimal implementation**

```python
def _summarize_infeasibility_reasons(all_results: list[SuccessProbabilityResult]) -> str:
    counts: dict[str, int] = {}
    for result in all_results:
        for reason in result.infeasibility_reasons:
            reason_key = reason.split()[0]
            counts[reason_key] = counts.get(reason_key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ",".join(key for key, _count in ordered[:3])


def _handle_no_feasible_allocation(...):
    ...
    notes = [
        "warning=no_feasible_allocation",
        f"fallback=closest_feasible_candidate allocation={best_allocation.name}",
        f"fallback_pressure_score allocation={best_allocation.name} score={best_score:.4f}",
        f"fallback_dominant_constraints reasons={_summarize_infeasibility_reasons(all_results)}",
        "action_required=reassess_goal_amount_or_horizon_or_drawdown_or_candidate_allocations",
    ]
```

Use the already computed infeasibility score from the fallback chooser rather than recomputing a second formula.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_doc_contract.py::test_run_goal_solver_summarizes_no_feasible_pressure -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_02_goal_solver_doc_contract.py src/goal_solver/engine.py
git commit -m "feat: deepen goal solver infeasibility notes"
```

### Task 3: Run regression coverage for the slice

**Files:**
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Update the backlog note after code lands**

```md
### 02 goal_solver

仍缺：
- 更贴近正式文档的 Monte Carlo / infeasibility 细节
- 更深的 `solver_notes` / 结果解释口径

本轮收口：
- Monte Carlo context notes (`paths / seed / horizon`)
- success-threshold gap notes
- no-feasible dominant-constraint summary
- fallback pressure score note
```

- [ ] **Step 2: Run targeted goal solver tests**

Run: `python3 -m pytest tests/contract/test_02_goal_solver_contract.py tests/contract/test_02_goal_solver_doc_contract.py tests/smoke/test_goal_solver_to_ev_smoke.py -q`
Expected: all selected tests pass

- [ ] **Step 3: Run full regression**

Run: `python3 -m pytest -q`
Expected: full suite passes

- [ ] **Step 4: Commit**

```bash
git add handoff/CODEX_system_doc_gap_backlog.md
git commit -m "docs: update goal solver backlog status"
```

## Self-Review

- Spec coverage: this plan only covers the first `02 goal_solver` slice from the roadmap and backlog, not the full Phase 1. It maps directly to the remaining gaps called out for Monte Carlo/infeasibility detail and deeper `solver_notes`.
- Placeholder scan: no `TODO`/`TBD` markers remain; each task names exact files, tests, and commands.
- Type consistency: all proposed helpers use the existing `GoalSolverInput`, `SuccessProbabilityResult`, and `StrategicAllocation` types. No new public dataclasses are introduced in this slice.
