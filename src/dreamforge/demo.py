"""Offline deterministic demo: 8-hour (960 epoch) run, export, verify.

Runs entirely offline with no credentials. Prints only facts observed during
execution (counts, hashes, check results). Rendering/verification never
re-runs the simulator beyond this entry point itself.

DreamForge is a research and visualization simulator. It does not measure
brains, diagnose conditions, predict dreams, infer psychological meaning, or
provide medical advice.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dreamforge.core.config import load_config
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.simulation.engine import run_simulation
from dreamforge.simulation.export_import import import_and_verify, write_export

DISCLAIMER = (
    "DreamForge is a research and visualization simulator. It does not "
    "measure brains, diagnose conditions, predict dreams, infer psychological "
    "meaning, or provide medical advice."
)


def main(argv: list[str] | None = None) -> int:
    """Run the bundled 8-hour demo; returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = Path(argv[0]) if argv else Path("examples/configs/demo_8h.json")
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("exports/demo_8h")

    config = load_config(config_path)
    clock = FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC))
    result = run_simulation(config, clock)

    checksums = write_export(
        out_dir=out_dir,
        events=result.events,
        manifest=result.manifest,
        config=config,
        graph_snapshot=result.graph_snapshot,
    )

    imported, report = import_and_verify(out_dir)

    counts = Counter(str(event.event_type) for event in result.events)
    print(DISCLAIMER)
    print(f"config: {config_path}")
    print(f"ticks: {config.total_ticks} x {config.epoch_seconds}s epochs")
    print("events:")
    for event_type in sorted(counts):
        print(f"  {event_type}: {counts[event_type]}")
    print(f"core_trace_hash: {result.core_trace_hash}")
    print(f"manifest_hash:   {result.manifest.manifest_hash()}")
    print("export artifacts:")
    for name in sorted(checksums):
        print(f"  {name}: sha256={checksums[name]}")
    print(f"import verification: ok={report.ok} checks={len(report.checks)}")
    failed = [check for check in report.checks if check["status"] != "pass"]
    if failed:
        for check in failed:
            print(f"  FAILED: {check['check']}: {check['detail']}")
        return 1
    print(
        "output_class: mechanistic_proxy — " "Simulated model proxy — not a biological measurement",
    )
    print(f"imported event count matches: {len(imported.events) == len(result.events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
