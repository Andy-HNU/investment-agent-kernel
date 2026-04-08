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

On onboarding inputs:
- `goal_amount` 表示期末总资产目标。
- 若用户提供的是“目标年化收益率”，应优先传 `target_annual_return`，由 kernel 结合当前资产、每月投入与期限折算 `goal_amount`。
- 不要在 advisor shell 侧手工把“年化目标”简化成只对当前资产复利后的终值。

Non-goals:
- No EV scoring or candidate generation here.
- No skill body copies from OpenClaw.
