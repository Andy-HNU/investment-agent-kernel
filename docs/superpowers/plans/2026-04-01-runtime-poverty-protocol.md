# Runtime Poverty Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `04 runtime_optimizer` candidate-poverty protocol so runtime results degrade to safe-action semantics themselves instead of depending entirely on orchestrator-side restriction.

**Architecture:** Add a small helper in `src/runtime_optimizer/engine.py` that patches `EVReport` when `ranked_actions < 2`. Keep orchestrator restrictions untouched; this slice only makes the runtime layer honest and self-contained. Cover it with direct runtime contract tests that monkeypatch candidate generation and EV reports.

**Tech Stack:** Python 3, pytest, dataclasses, existing `runtime_optimizer` and `ev_engine` dataclasses

---

### Task 1: Add runtime poverty protocol contract tests

**Files:**
- Create: `tests/contract/test_04_runtime_optimizer_contract.py`
- Modify: `src/runtime_optimizer/engine.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.contract
def test_run_runtime_optimizer_poverty_protocol_clears_unsafe_recommendation(..., monkeypatch):
    def _fake_candidates(**_kwargs):
        return [unsafe_action]

    def _fake_ev_report(*_args, **_kwargs):
        return EVReport(
            ...,
            ranked_actions=[
                EVResult(
                    action=unsafe_action,
                    score=unsafe_score,
                    rank=1,
                    is_recommended=True,
                    recommendation_reason="unsafe top1",
                )
            ],
            recommended_action=unsafe_action,
            recommended_score=unsafe_score,
            confidence_flag="medium",
            confidence_reason="top1-top2 unavailable",
            goal_solver_baseline=0.42,
            goal_solver_after_recommended=0.51,
            ...
        )

    monkeypatch.setattr(runtime_optimizer_engine, "generate_candidates", _fake_candidates)
    monkeypatch.setattr(runtime_optimizer_engine, "run_ev_engine", _fake_ev_report)

    result = run_runtime_optimizer(...)

    assert result.candidate_poverty is True
    assert result.ev_report.recommended_action is None
    assert result.ev_report.recommended_score is None
    assert result.ev_report.goal_solver_after_recommended == pytest.approx(0.42)
    assert result.ev_report.confidence_flag == "low"
    assert "候选通过过滤数量过少" in result.ev_report.confidence_reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_04_runtime_optimizer_contract.py -q`
Expected: `FAIL` because no poverty protocol exists in `run_runtime_optimizer(...)`.

- [ ] **Step 3: Write minimal implementation**

```python
def _apply_poverty_protocol(ev_report: EVReport) -> tuple[EVReport, bool]:
    if len(ev_report.ranked_actions) >= 2:
        return ev_report, False

    safe_types = {ActionType.FREEZE, ActionType.OBSERVE}
    safe_results = [item for item in ev_report.ranked_actions if item.action.type in safe_types]
    ev_report.confidence_flag = "low"
    if safe_results:
        ev_report.recommended_action = safe_results[0].action
        ev_report.recommended_score = safe_results[0].score
        ev_report.goal_solver_after_recommended = ev_report.goal_solver_baseline
        ev_report.confidence_reason = "候选通过过滤数量过少，已降级为安全动作优先"
    else:
        ev_report.recommended_action = None
        ev_report.recommended_score = None
        ev_report.goal_solver_after_recommended = ev_report.goal_solver_baseline
        ev_report.confidence_reason = "候选通过过滤数量过少，且不存在安全动作可推荐"
    return ev_report, True
```

Apply the helper inside `run_runtime_optimizer(...)` before constructing `RuntimeOptimizerResult`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_04_runtime_optimizer_contract.py -q`
Expected: `1 passed`

### Task 2: Update backlog and verify regressions

**Files:**
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Update backlog**

```md
本轮收口：
- runtime candidate-poverty protocol now patches EVReport to safe-action semantics
```

- [ ] **Step 2: Run targeted regression**

Run: `python3 -m pytest tests/contract/test_04_runtime_optimizer_contract.py tests/contract/test_07_orchestrator_contract.py tests/contract/test_09_decision_card_contract.py -q`
Expected: all selected tests pass

- [ ] **Step 3: Run full regression**

Run: `python3 -m pytest -q`
Expected: full suite passes

## Self-Review

- Spec coverage: this slice maps directly to `04`'s `_apply_poverty_protocol()` gap.
- Placeholder scan: exact file paths and commands are present.
- Type consistency: no new public types; the slice mutates existing `EVReport` fields only.
