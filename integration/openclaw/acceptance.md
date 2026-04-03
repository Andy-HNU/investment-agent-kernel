# Acceptance

Scripted path to capture NL inputs and outputs:

```bash
OPENCLAW_BRIDGE_DB="/tmp/frontdesk.sqlite" \
python scripts/accept_openclaw_bridge.py \
  --file integration/openclaw/examples/tasks.txt \
  --artifacts handoff/logs/openclaw_bridge_acceptance
```

The script writes a JSONL log under the `--artifacts` directory and prints the path.

The default task file is expected to cover:
- onboarding
- status
- show_user
- monthly
- quarterly
- event
- approve_plan
- feedback
- explain_probability
- explain_plan_change
