# EV Cooldown Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `10 ev_engine` consume calibrated cooldown state (`BehaviorState.cooldown_active` / `ConstraintState.cooldown_currently_active`) as a hard feasibility input instead of relying only on emotion flags.

**Architecture:** Extend `_check_feasibility(...)` in `src/runtime_optimizer/ev_engine/engine.py` with one consolidated cooldown-active predicate. Keep the existing fail reason string and leave orchestrator-side cooldown guardrails unchanged. Cover with a direct EV contract test using cooldown flags without emotion flags.

**Tech Stack:** Python 3, pytest, existing `runtime_optimizer.ev_engine` contracts

---

### Task 1: Add cooldown-state feasibility contract coverage

**Files:**
- Modify: `tests/contract/test_10_ev_report_contract.py`
- Modify: `src/runtime_optimizer/ev_engine/engine.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.contract
def test_run_ev_engine_respects_calibrated_cooldown_state_without_emotion_flags(...):
    behavior_state = deepcopy(behavior_state_base)
    behavior_state["high_emotion_flag"] = False
    behavior_state["panic_flag"] = False
    behavior_state["cooldown_active"] = True

    constraint_state = deepcopy(constraint_state_base)
    constraint_state["cooldown_currently_active"] = True

    state = _ev_state(...)
    actions = [
        _action(ActionType.FREEZE, amount=0.0, amount_pct=0.0),
        _action(
            ActionType.ADD_CASH_TO_CORE,
            target_bucket="equity_cn",
            amount=3000.0,
            amount_pct=0.08,
            cooldown_applicable=True,
        ),
    ]

    report = run_ev_engine(state=state, candidate_actions=actions, trigger_type="monthly")

    assert len(report.ranked_actions) == 1
    assert report.ranked_actions[0].action.type == ActionType.FREEZE
    assert any(
        "当前处于高情绪冷静期，非观察/冻结动作不可执行" in eliminated.fail_reasons
        for _, eliminated in report.eliminated_actions
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_10_ev_report_contract.py::test_run_ev_engine_respects_calibrated_cooldown_state_without_emotion_flags -q`
Expected: `FAIL` because `_check_feasibility(...)` currently ignores cooldown flags unless emotion/panic flags are also set.

- [ ] **Step 3: Write minimal implementation**

```python
is_cooldown_active = bool(
    constraints.get("cooldown_currently_active")
    or behavior.get("cooldown_active")
    or behavior.get("high_emotion_flag")
    or behavior.get("panic_flag")
)
if action.cooldown_applicable and is_cooldown_active and action.type not in {ActionType.FREEZE, ActionType.OBSERVE}:
    reasons.append("当前处于高情绪冷静期，非观察/冻结动作不可执行")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_10_ev_report_contract.py::test_run_ev_engine_respects_calibrated_cooldown_state_without_emotion_flags -q`
Expected: `1 passed`

### Task 2: Update backlog and verify regressions

**Files:**
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Update backlog**

```md
本轮收口：
- EV feasibility now consumes calibrated cooldown state in addition to emotion flags
```

- [ ] **Step 2: Run targeted regression**

Run: `python3 -m pytest tests/contract/test_10_ev_report_contract.py tests/contract/test_04_runtime_optimizer_contract.py tests/contract/test_07_orchestrator_contract.py -q`
Expected: all selected tests pass

- [ ] **Step 3: Run full regression**

Run: `python3 -m pytest -q`
Expected: full suite passes

## Self-Review

- Spec coverage: this slice closes a concrete `05 -> 10` semantic gap, not a cosmetic wording change.
- Placeholder scan: exact files, commands, and the concrete predicate are included.
- Type consistency: no new public types; the slice extends only feasibility logic.
