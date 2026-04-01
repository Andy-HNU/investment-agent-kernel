#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from integration.openclaw.bridge import handle_task, write_log_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acceptance harness for OpenClaw bridge")
    parser.add_argument("--file", help="Optional tasks file; otherwise reads stdin lines")
    parser.add_argument("--db", help="SQLite DB path (overrides env OPENCLAW_BRIDGE_DB)")
    parser.add_argument("--artifacts", help="Artifacts dir (default artifacts/openclaw_bridge)")
    args = parser.parse_args(argv)

    db_path = Path(args.db or os.environ.get("OPENCLAW_BRIDGE_DB") or "data/investment_frontdesk.sqlite")
    artifacts = Path(args.artifacts or os.environ.get("OPENCLAW_ARTIFACTS") or "artifacts/openclaw_bridge")
    tasks: list[str] = []
    if args.file:
        tasks = [line.strip() for line in Path(args.file).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        for line in sys.stdin:
            line = line.strip()
            if line:
                tasks.append(line)
    if not tasks:
        print("no tasks provided", file=sys.stderr)
        return 1
    artifacts.mkdir(parents=True, exist_ok=True)
    last_log = None
    for task in tasks:
        result = handle_task(task, db_path=str(db_path))
        last_log = write_log_record(task, output=result, log_dir=artifacts)
    if last_log:
        print(f"log_path={last_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

