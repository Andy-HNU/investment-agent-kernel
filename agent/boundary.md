# Boundary

This layer:
- Routes NL tasks to frontdesk service entrypoints only.
- Does not compute EV, generate candidate allocations, or modify orchestrator logic.
- Does not redefine canonical types (see AGENTS.md ownership rules).
- Does not vendor or copy external OpenClaw skills; references only.

Allowed: parsing NL into structured profile and calling `frontdesk.service`.
Forbidden: scoring, allocation generation, strategy inference beyond routing.

