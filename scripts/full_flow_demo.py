from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from shared.demo_scenarios import run_demo_lifecycle, summarize_demo_lifecycle


def _print_pretty(summary: dict) -> None:
    print("Investment Decision System Demo")
    print()
    for phase in summary["phase_order"]:
        result = summary["results"][phase]
        print(f"[{phase}]")
        print(f"  run_id: {result['run_id']}")
        print(f"  workflow_type: {result['workflow_type']}")
        print(f"  status: {result['status']} / {result['status_badge']}")
        print(f"  recommended_action: {result['recommended_action']}")
        print(f"  primary_recommendation: {result['primary_recommendation']}")
        print(f"  summary: {result['summary']}")
        if result["guardrails"]:
            print(f"  guardrails: {', '.join(result['guardrails'])}")
        if result["review_conditions"]:
            print(f"  review_conditions: {', '.join(result['review_conditions'])}")
        if result["next_steps"]:
            print(f"  next_steps: {', '.join(result['next_steps'])}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local end-to-end demo lifecycle for the investment decision system.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print compact JSON instead of a human-readable summary.",
    )
    args = parser.parse_args()

    lifecycle = run_demo_lifecycle()
    summary = summarize_demo_lifecycle(lifecycle)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        _print_pretty(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
