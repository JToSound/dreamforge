"""Record the dev-environment reference hash for wheel-parity checking.

Writes the 60-tick/seed-777001 core trace hash to stdout. Run under the DEV
venv; the value must equal what scripts/smoke_installed_wheel.py prints under
the clean venv.
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
    """Print the reference trace hash for the fixed parity config."""
    payload = json.loads((REPO / "examples/configs/demo_8h.json").read_text(encoding="utf-8"))
    payload["total_ticks"] = 60
    payload["run_seed"] = 777001
    config = load_config(payload)
    result = run_simulation(config, FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC)))
    print(result.core_trace_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
