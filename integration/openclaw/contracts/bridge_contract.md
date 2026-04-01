# Bridge Contract

Function:

```python
def handle_task(task: str, *, db_path: str, now: str | None = None) -> dict:
    """Return {intent, invocation, result}.
    - intent: {name, confidence}
    - invocation: tool inputs resolved from NL
    - result: frontdesk service summary or user_state snapshot
    """
```

Supported intents:
- onboarding → `frontdesk.service.run_frontdesk_onboarding(profile, db_path)`
- status → `frontdesk.service.load_user_state(account_profile_id, db_path)`
- monthly → `frontdesk.service.run_frontdesk_followup(account_profile_id, 'monthly', db_path, profile=...)`
- feedback → `frontdesk.service.record_frontdesk_execution_feedback(...)`
- approve_plan → `frontdesk.service.approve_frontdesk_execution_plan(...)`

Non-goals:
- No EV scoring or candidate generation here.
- No skill body copies from OpenClaw.

