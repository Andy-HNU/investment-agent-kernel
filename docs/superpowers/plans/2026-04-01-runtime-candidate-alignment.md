# Runtime Candidate Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align `04 runtime_optimizer` candidate generation with the spec table so non-behavior workflows do not always emit `OBSERVE`, and `ADD_DEFENSE` is reserved for drawdown-risk events instead of leaking into monthly/structural flows.

**Architecture:** Keep the existing candidate generator shape and dedup/trim flow. Narrow only two generation rules: when `OBSERVE` is injected and when `ADD_DEFENSE` is generated. Cover with contract tests that exercise monthly, structural event, and drawdown event paths directly against `generate_candidates(...)`.

**Tech Stack:** Python 3, pytest, existing `runtime_optimizer.candidates` module

---

### Task 1: Add candidate-generation contract coverage

**Files:**
- Modify: `tests/contract/test_04_event_behavior_contract.py`
- Modify: `src/runtime_optimizer/candidates.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.contract
def test_monthly_generation_does_not_force_observe_or_add_defense(...):
    ev_state = build_ev_state(...)
    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.MONTHLY,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.FREEZE in action_types
    assert ActionType.OBSERVE not in action_types
    assert ActionType.ADD_DEFENSE not in action_types


@pytest.mark.contract
def test_drawdown_event_forces_add_defense_without_forcing_observe(...):
    ev_state = build_ev_state(...)
    candidates = generate_candidates(
        state=ev_state,
        params=runtime_optimizer_params_base,
        mode=RuntimeOptimizerMode.EVENT,
        drawdown_event=True,
    )
    action_types = {candidate.type for candidate in candidates}

    assert ActionType.ADD_DEFENSE in action_types
    assert ActionType.OBSERVE not in action_types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/contract/test_04_event_behavior_contract.py -q`
Expected: `FAIL` because `generate_candidates(...)` currently always injects `OBSERVE` and can emit `ADD_DEFENSE` from ordinary defense shortfall.

- [ ] **Step 3: Write minimal implementation**

```python
candidates.append(_build_action(ActionType.FREEZE, ...))

is_behavior_cooldown = behavior_event or behavior.get("high_emotion_flag") or behavior.get("panic_flag")
if is_behavior_cooldown:
    candidates.append(_build_action(ActionType.OBSERVE, ...))

...
if drawdown_event:
    candidates.append(_build_action(ActionType.ADD_DEFENSE, ...))
```

Keep the existing fallback that restores `OBSERVE` only if the candidate set would otherwise drop below `min_candidates`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/contract/test_04_event_behavior_contract.py -q`
Expected: all tests pass

### Task 2: Update backlog and verify regressions

**Files:**
- Modify: `handoff/CODEX_system_doc_gap_backlog.md`

- [ ] **Step 1: Update backlog status**

```md
本轮收口：
- candidate generation now matches mode table for OBSERVE forcing
- ADD_DEFENSE reserved for drawdown-event path
```

- [ ] **Step 2: Run targeted runtime/EV regression**

Run: `python3 -m pytest tests/contract/test_04_event_behavior_contract.py tests/contract/test_10_ev_report_contract.py tests/contract/test_07_orchestrator_contract.py -q`
Expected: all selected tests pass

- [ ] **Step 3: Run full regression**

Run: `python3 -m pytest -q`
Expected: full suite passes

## Self-Review

- Spec coverage: this slice directly addresses the `04 runtime_optimizer` mode-table drift called out in the system spec.
- Placeholder scan: each step names exact files and commands.
- Type consistency: this slice changes only candidate-generation rules; no new dataclasses or EV types are introduced.
