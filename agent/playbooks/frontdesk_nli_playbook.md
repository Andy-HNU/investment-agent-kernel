# Frontdesk NLI Playbook

Purpose: deterministic mapping of natural-language intents to stable tools.

- Detect intent via keyword regex; prefer explicit verbs ("onboard", "status").
- Extract profile fields with simple patterns: `assets`, `monthly`, `goal`, `months`, `risk`.
- Use conservative defaults when missing; never invent complex behavior.
- Always call frontdesk service functions; never compute EV or allocations here.

Example:
```
Input: "onboard user alice assets 50000 monthly 12000 goal 1000000 in 60 months risk moderate"
→ Tool: frontdesk.onboarding
→ Outputs: workflow=onboarding, run_id=frontdesk_onboarding_alice_...
```

