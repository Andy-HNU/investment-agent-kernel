# Acceptance

Scripted path to capture NL inputs and outputs:

```
OPENCLAW_BRIDGE_DB="/tmp/frontdesk.sqlite" \
python scripts/accept_openclaw_bridge.py --file examples/tasks.txt
```

The script writes a JSONL log under `artifacts/openclaw_bridge/` and prints the path.

