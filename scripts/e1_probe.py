"""E1 probe: reproduce the fresh-process hash comparison cleanly."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")
CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")


def payload(ticks: int = 960, seed: int = 777) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": f"exp-{ticks}-{seed}",
        "run_seed": seed,
        "total_ticks": ticks,
        "transitions": {
            "probabilities": {
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
                for i, s in enumerate(STAGES)
            },
        },
        "dwells": {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in STAGES},
        "chemistry": {
            "baselines": {c: 0.5 for c in CHANNELS},
            "stage_modulation": {c: {s: 0.0 for s in STAGES} for c in CHANNELS},
            "circadian_gain": {c: 0.0 for c in CHANNELS},
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 50, "edge_count": 120},
            "selector": {"top_k": 3},
            "replay_every_n_epochs": 5,
        },
    }


def main() -> None:
    p = payload()
    clock = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))
    in_process = run_simulation(load_config(p), clock).core_trace_hash
    print("IN-PROCESS :", in_process)

    runner = Path(tempfile.gettempdir()) / "_e1_runner.py"
    import base64

    encoded = base64.b64encode(json.dumps(p).encode("utf-8")).decode("ascii")
    runner.write_text(
        "import base64\n"
        "import json\n"
        "import sys\n"
        f"sys.path.insert(0, r'{REPO / 'src'}')\n"
        "from datetime import UTC, datetime\n"
        "from dreamforge.core.config import load_config\n"
        "from dreamforge.core.provenance.clock import FixedClock\n"
        "from dreamforge.simulation.engine import run_simulation\n"
        f"payload = json.loads(base64.b64decode('{encoded}').decode('utf-8'))\n"
        "clock = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))\n"
        "print(run_simulation(load_config(payload), clock).core_trace_hash)\n",
        encoding="utf-8",
    )
    sub = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True, timeout=300)
    runner.unlink(missing_ok=True)
    out = sub.stdout.strip()
    print("SUBPROCESS :", out if out else "(no stdout)")
    if sub.returncode != 0:
        print("STDERR tail:", sub.stderr[-600:])
    elif out and out == in_process:
        print("MATCH: yes")
    else:
        print("MATCH: NO")


if __name__ == "__main__":
    main()
