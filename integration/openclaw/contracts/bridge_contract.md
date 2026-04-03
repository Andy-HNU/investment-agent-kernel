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
- show_user → `frontdesk.service.load_frontdesk_snapshot(account_profile_id, db_path)`
- status → `frontdesk.service.load_user_state(account_profile_id, db_path)`
- monthly → `frontdesk.service.run_frontdesk_followup(account_profile_id, 'monthly', db_path)`
- quarterly → `frontdesk.service.run_frontdesk_followup(account_profile_id, 'quarterly', db_path)`
- event → `frontdesk.service.run_frontdesk_followup(account_profile_id, 'event', db_path, event_context=...)`
- feedback → `frontdesk.service.record_frontdesk_execution_feedback(...)`
- approve_plan → `frontdesk.service.approve_frontdesk_execution_plan(...)`
- explain_probability → snapshot-based explanation of success probability, highest-probability alternative, implied required annual return, simulation mode, and market regime
- explain_plan_change → snapshot-based explanation of active vs pending execution-plan guidance and comparison detail

Current NL bridge input surface:
- onboarding: full natural-language profile parsing
- status / show_user / monthly / quarterly: `account_profile_id`
- event: `account_profile_id` + event keywords parsed into `event_context`
- approve_plan: `account_profile_id` + optional `plan_id` / `plan_version`; if missing, fallback to the only pending plan
- feedback: `account_profile_id` + optional `run_id`; if missing, fallback to the latest run

Direct frontdesk tools support richer follow-up inputs such as `profile_json`, `external_snapshot_source`, and `external_data_config`, but those richer overrides are not yet parsed from the v1.1 NL bridge.

Non-goals:
- No EV scoring or candidate generation here.
- No skill body copies from OpenClaw.
