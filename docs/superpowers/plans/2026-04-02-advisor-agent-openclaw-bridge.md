# Advisor-Agent OpenClaw Bridge Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an advisor-agent ↔ OpenClaw integration layer that routes natural-language tasks into existing frontdesk workflows without copying OpenClaw skills, with documented contracts, acceptance logs, and tests.

**Architecture:** A thin NL router maps intents to stable frontdesk entrypoints. Contracts live in `agent/` and `integration/openclaw/` as Markdown/YAML. A small CLI harness captures input/output logs in `artifacts/`. Tests validate contracts and bridge behavior.

**Tech Stack:** Python 3.11 stdlib; existing `frontdesk` package; `pytest`.

---

### Task 1: Doc contracts skeletons

**Files:**
- Create: `agent/README.md`
- Create: `agent/contracts/tool_contracts.yaml`
- Create: `agent/routing/skill_routing.yaml`
- Create: `agent/playbooks/frontdesk_nli_playbook.md`
- Create: `agent/source_map.yaml`
- Create: `agent/patch_back_policy.md`
- Create: `integration/openclaw/README.md`
- Create: `integration/openclaw/contracts/bridge_contract.md`
- Create: `integration/openclaw/config/schema.yaml`
- Create: `integration/openclaw/acceptance.md`
- Test: `tests/agent/test_agent_contracts.py`

- [ ] Step 1: Write failing doc-contract tests
- [ ] Step 2: Run tests (expect failures)
- [ ] Step 3: Add minimal docs with required keys/sections
- [ ] Step 4: Re-run tests (expect pass)
- [ ] Step 5: Commit

Example YAML keys required in tests:
```yaml
version: 1
interfaces:
  - name: frontdesk.onboarding
    inputs: [account_profile_id, display_name]
    outputs: [status, run_id]
```

### Task 2: Runtime bridge + NL router

**Files:**
- Create: `src/integration/openclaw/__init__.py`
- Create: `src/integration/openclaw/bridge.py`
- Create: `src/agent/__init__.py`
- Create: `src/agent/nli_router.py`
- Create: `scripts/openclaw_bridge_cli.py`
- Test: `tests/integration/test_openclaw_bridge.py`

- [ ] Step 1: Write failing bridge tests covering onboarding + status
- [ ] Step 2: Run tests (expect failures)
- [ ] Step 3: Implement minimal `handle_task()` using simple intent regex + numeric parsing; call `frontdesk.service`
- [ ] Step 4: Add CLI wrapper that logs input/output JSON to `artifacts/openclaw_bridge/<ts>.jsonl`
- [ ] Step 5: Re-run tests (expect pass)
- [ ] Step 6: Commit

Example API to implement:
```python
# src/integration/openclaw/bridge.py
from typing import Any, Optional

def handle_task(task: str, *, db_path: str, now: Optional[str] = None) -> dict[str, Any]:
    """Route an OpenClaw-style NL task into frontdesk workflows.
    Returns a JSON-serializable dict with keys: {intent, invocation, result}.
    """
    ...
```

### Task 3: Acceptance harness

**Files:**
- Create: `scripts/accept_openclaw_bridge.py`

- [ ] Step 1: Script reads tasks from stdin or `--file` and writes logs to `artifacts/openclaw_bridge/`
- [ ] Step 2: Add to docs in `integration/openclaw/acceptance.md`
- [ ] Step 3: Commit

### Task 4: Verification

- [ ] Step 1: Run targeted tests
- [ ] Step 2: Run full `pytest`
- [ ] Step 3: Commit and summarize changes

---

## Self-Review
- Spec coverage: docs contracts, router/bridge, acceptance logs, tests – covered by Tasks 1–3. Gaps will be noted if new intents are needed.
- Placeholders: Avoided; tests enforce required YAML keys.
- Type consistency: NL router returns dict with stable keys; docs reference those names.

