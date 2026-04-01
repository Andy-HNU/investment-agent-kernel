#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from integration.openclaw.bridge import handle_task, write_log_record


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="OpenClaw → frontdesk bridge CLI")
    parser.add_argument("--task", required=True, help="Natural language task")
    parser.add_argument("--db", help="SQLite DB path (overrides env OPENCLAW_BRIDGE_DB)")
    parser.add_argument("--artifacts", help="Artifacts dir (default artifacts/openclaw_bridge)")
    args = parser.parse_args(argv)

    db_path = Path(args.db or os.environ.get("OPENCLAW_BRIDGE_DB") or "data/investment_frontdesk.sqlite")
    artifacts = Path(args.artifacts or os.environ.get("OPENCLAW_ARTIFACTS") or "artifacts/openclaw_bridge")
    artifacts.mkdir(parents=True, exist_ok=True)
    result = handle_task(args.task, db_path=str(db_path))
    log_path = write_log_record(args.task, output=result, log_dir=artifacts)
    print(f"log_path={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
