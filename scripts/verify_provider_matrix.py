from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from snapshot_ingestion.provider_matrix import load_provider_capability_matrix


def main() -> None:
    matrix = [record.to_dict() for record in load_provider_capability_matrix()]
    print(json.dumps({"provider_capability_matrix": matrix}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
