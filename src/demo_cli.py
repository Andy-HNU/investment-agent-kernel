from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from shared.demo_scenarios import DEMO_SCENARIOS, build_demo_report, render_demo_report


SCENARIOS = DEMO_SCENARIOS


def run_demo_scenario(name: str) -> dict[str, Any]:
    return build_demo_report(name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local end-to-end demo scenarios for the investment decision system.",
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default=None,
        choices=SCENARIOS,
        help="Which demo scenario to run.",
    )
    parser.add_argument(
        "--scenario",
        dest="scenario_flag",
        choices=SCENARIOS,
        help="Optional named scenario flag; overrides the positional scenario when provided.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full serialized report as JSON.",
    )
    return parser


def _resolve_scenario(args: argparse.Namespace) -> str:
    if args.scenario_flag is not None:
        return args.scenario_flag
    if args.scenario is not None:
        return args.scenario
    return "full_lifecycle"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = run_demo_scenario(_resolve_scenario(args))

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(render_demo_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
