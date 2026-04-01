# Advisor-Agent Contracts

This folder defines the stable contracts between an advisor agent (e.g. OpenClaw) and this repo’s frontdesk workflows.

Key guarantees:
- Stable tool interfaces live in `contracts/`.
- NL intent routing examples live in `routing/` and `playbooks/`.
- External skills are referenced by source, not copied (`source_map.json`).
- Boundaries and patch-back policy are explicit (`boundary.md`, `patch_back_policy.md`).

