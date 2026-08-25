"""Determinism hash runner — prints the trace hash for the committed payload.

Used by .github/workflows/determinism.yml to compare an ubuntu-latest run
against the Windows-generated expectation in exports/_determinism_expected.txt.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402


def main() -> int:
    payload_path = REPO / "exports" / "_determinism_payload.json"
    if not payload_path.exists():
        print("payload missing; generate it with:", file=sys.stderr)
        print("  python scripts/experiment_round2.py E10", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    clock = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))
    print(run_simulation(load_config(payload), clock).core_trace_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
