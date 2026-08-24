"""DreamForge performance benchmark — honest, observed numbers only.

Measures the deterministic pipeline on THIS machine and prints results as a
markdown table. No claims beyond measured wall-clock times; every scenario
states its exact configuration. Run:

    .venv/Scripts/python.exe scripts/benchmark.py
"""

from __future__ import annotations

import json
import platform
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.core.serialization.dqcj import dumps_canonical  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402
from dreamforge.simulation.export_import import import_and_verify, write_export  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")


def make_payload(ticks: int, seed: int) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": f"bench-{ticks}-{seed}",
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
            "baselines": {
                c: 0.5 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "stage_modulation": {
                c: {s: 0.0 for s in STAGES}
                for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "circadian_gain": {
                c: 0.0 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 50, "edge_count": 120},
            "selector": {"top_k": 3},
            "replay_every_n_epochs": 5,
        },
    }


def bench_engine(ticks: int, seed: int = 42) -> dict:
    config = load_config(make_payload(ticks, seed))
    clock = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))

    tracemalloc.start()
    t0 = time.perf_counter()
    result = run_simulation(config, clock)
    elapsed = time.perf_counter() - t0
    _, peak_kb = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "ticks": ticks,
        "seconds": elapsed,
        "epochs_per_s": ticks / elapsed,
        "events": len(result.events),
        "trace_hash": result.core_trace_hash[:12],
        "peak_mb": peak_kb / 1024 / 1024,
    }


def bench_dqcj(n_events: int = 20000) -> dict:
    payload = {"i": list(range(20)), "f": [n / 7 for n in range(20)], "s": "x" * 40}
    t0 = time.perf_counter()
    for _ in range(n_events):
        dumps_canonical(payload, quantizations={"f.*": "0.000001"})
    elapsed = time.perf_counter() - t0
    return {"ops": n_events, "seconds": elapsed, "ops_per_s": n_events / elapsed}


def bench_export_import(ticks: int = 960) -> dict:
    from collections import Counter

    from dreamforge.core.models.dream_context import build_dream_context
    from dreamforge.simulation.report import build_report

    out_dir = REPO / "exports" / f"_bench_{ticks}"
    config = load_config(make_payload(ticks, 4242))
    result = run_simulation(config, FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    context = build_dream_context(
        run_id=config.run_id,
        schema_version="1.0",
        total_ticks=ticks,
        events=list(result.events),
    )
    counts = dict(Counter(str(e.event_type) for e in result.events))
    labeled_report = build_report(
        context=context,
        event_counts=counts,
        core_trace_hash=result.core_trace_hash,
    )

    t0 = time.perf_counter()
    write_export(
        out_dir=out_dir,
        events=result.events,
        manifest=result.manifest,
        config=config,
        graph_snapshot=result.graph_snapshot,
        report=labeled_report,
    )
    export_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    imported, verification = import_and_verify(out_dir)
    import_s = time.perf_counter() - t0

    import shutil

    shutil.rmtree(out_dir)
    assert verification.ok
    return {
        "ticks": ticks,
        "events": len(result.events),
        "export_s": export_s,
        "import_s": import_s,
        "checks": len(verification.checks),
    }


def main() -> int:
    print("## Environment\n")
    print(f"- python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    try:
        import numpy

        print(f"- numpy {numpy.__version__}")
    except ImportError:
        pass
    print(f"- date: {datetime.now(UTC).isoformat(timespec='seconds')}")
    print()

    print("## Engine throughput (fixed seed 42)\n")
    print("| ticks | wall s | epochs/s | events | peak RSS MB | trace hash |")
    print("|---|---|---|---|---|---|")
    engine_rows = []
    for ticks in (960, 9600, 19200):
        row = bench_engine(ticks)
        engine_rows.append(row)
        print(
            f"| {row['ticks']} | {row['seconds']:.3f} | {row['epochs_per_s']:,.0f} "
            f"| {row['events']} | {row['peak_mb']:.1f} | `{row['trace_hash']}…` |",
        )
        sys.stdout.flush()

    print("\n## DQCJ-1 canonical serialization (quantized floats)\n")
    dqcj = bench_dqcj()
    print(f"- {dqcj['ops']:,} ops in {dqcj['seconds']:.3f}s -> {dqcj['ops_per_s']:,.0f} ops/s")

    print("\n## Export/import round trip (layout v2)\n")
    ei = bench_export_import(960)
    print(
        f"- {ei['events']} events: export {ei['export_s']:.3f}s, "
        f"verified import {ei['import_s']:.3f}s ({ei['checks']} checks)",
    )

    (REPO / "exports").mkdir(exist_ok=True)
    (REPO / "exports" / "_bench_results.json").write_text(
        json.dumps({"engine": engine_rows, "dqcj": dqcj, "export_import": ei}, indent=2),
        encoding="utf-8",
    )
    print("\nraw JSON -> exports/_bench_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
