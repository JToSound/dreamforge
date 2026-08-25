"""DreamForge experimental suite — five experiment families, real runs only.

Families
--------
E1 determinism   : same seed -> identical trace hash across repeats and
                   process restarts; different seeds -> different hashes.
E2 scalability   : epochs/s and memory vs run length (linearity check).
E3 sleep science : stage distributions, Process S bounds/circadian shape,
                   dwell-length behaviour under varied parameters.
E4 stress edges  : minimal graphs, tiny dwells, extreme baselines, long
                   nights, replay-heavy configs - invariants must hold.
E5 ensembles     : cross-seed metric distributions (mean/sd/min/max).

Writes raw results to exports/_experiment_results.json and prints a summary.
Every scenario states its exact configuration; no claims beyond observations.

Run: .venv/Scripts/python.exe scripts/experiment.py [family ...]
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")
CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
CLOCK = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))


def payload(ticks: int = 960, seed: int = 42, **overrides) -> dict:
    p = {
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
    for key, value in overrides.items():
        if key in ("transitions", "dwells", "chemistry", "replay_policy"):
            p[key].update(value)
        else:
            p[key] = value
    return p


def run(payload: dict):
    return run_simulation(load_config(payload), CLOCK)


# --- E1: determinism ----------------------------------------------------------


def e1_determinism() -> dict:
    base = payload(ticks=960, seed=777)
    hashes = []
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        result = run(base)
        times.append(time.perf_counter() - t0)
        hashes.append(result.core_trace_hash)

    # Fresh-process check via a real temp runner file (exec-without-__file__
    # broke the first attempt - a bug in THIS script, not in the engine).
    import base64
    import tempfile

    runner = Path(tempfile.gettempdir()) / "_dreamforge_e1_runner.py"
    encoded = base64.b64encode(json.dumps(base).encode("utf-8")).decode("ascii")
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
        "result = run_simulation(load_config(payload), clock)\n"
        "print(result.core_trace_hash)\n",
        encoding="utf-8",
    )
    sub = subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    fresh_process_hash = sub.stdout.strip()
    runner.unlink(missing_ok=True)
    if sub.returncode != 0:
        fresh_process_hash = f"RUNNER_FAILED: {sub.stderr[-200:]}"

    distinct_other_seeds = {
        run(payload(ticks=960, seed=s)).core_trace_hash for s in (778, 100_000, 999_999)
    }
    return {
        "repeat_hashes_identical": len(set(hashes)) == 1,
        "n_repeats": len(hashes),
        "trace_hash": hashes[0][:16],
        "fresh_process_identical": fresh_process_hash == hashes[0],
        "other_seeds_all_differ": len(
            distinct_other_seeds | {hashes[0]},
        )
        == 4,
        "wall_s_range": [round(min(times), 3), round(max(times), 3)],
    }


# --- E2: scalability (upgraded: warmup + repeats, median + jitter) -------------


def e2_scalability() -> list[dict]:
    """Median-of-5 with a warmup run per size; jitter = (max-min)/median."""
    rows = []
    for ticks in (480, 960, 1920, 4800, 9600):
        run(payload(ticks=ticks))  # warmup: imports, caches, allocator
        times = []
        events = 0
        for _ in range(5):
            t0 = time.perf_counter()
            result = run(payload(ticks=ticks))
            times.append(time.perf_counter() - t0)
            events = len(result.events)
        med = statistics.median(times)
        rows.append(
            {
                "ticks": ticks,
                "repeats": 5,
                "median_seconds": round(med, 4),
                "jitter_frac": round((max(times) - min(times)) / med, 3),
                "epochs_per_s_median": round(ticks / med),
                "events": events,
            },
        )
    return rows


# --- E3: sleep-science behaviour ------------------------------------------------


def _stage_fractions(events) -> dict:
    counts: dict[str, int] = {}
    total = 0
    for event in events:
        if event.event_type == "sleep_state":
            stage = str(event.payload.stage)
            counts[stage] = counts.get(stage, 0) + 1
            total += 1
    return {stage: round(n / max(total, 1), 4) for stage, n in sorted(counts.items())}


def e3_uniform_matrix(seed: int) -> dict:
    result = run(payload(ticks=1920, seed=seed))
    fractions = _stage_fractions(result.events)
    expected = 1 / 5
    deviations = {s: abs(f - expected) for s, f in fractions.items()}
    return {
        "config": "uniform 0.25 off-diagonal transitions, 1920 ticks",
        "fractions": fractions,
        "max_abs_deviation_from_20pct": round(max(deviations.values()), 4),
    }


def e3_nrem_biased(seed: int) -> dict:
    matrix = {
        s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
        for i, s in enumerate(STAGES)
    }
    # Bias every row toward deep sleep: rows starting from any non-N3 stage
    # send 0.85 to N3; the N3 row sends 0.85 to N2 (a stage may not transition
    # to itself - the scheduler always changes state at dwell expiry). The
    # remaining three legal targets in each row get 0.05 each (sum = 1.00).
    for src in STAGES:
        target = "N2" if src == "N3" else "N3"
        for dst in STAGES:
            if src != dst:
                matrix[src][dst] = 0.05 if dst != target else 0.85
        assert abs(sum(matrix[src].values()) - 1.0) < 1e-9
    result = run(payload(ticks=1920, seed=seed, transitions={"probabilities": matrix}))
    fractions = _stage_fractions(result.events)
    return {
        "config": "every row biased 0.85 to deep sleep (N3; N3-row->N2), others 0.05",
        "fractions": fractions,
        "n3_fraction": fractions.get("N3", 0.0),
    }


def e3_process_s_bounds() -> dict:
    result = run(payload(ticks=9600, seed=31))
    values = [float(e.payload.s_value) for e in result.events if e.event_type == "sleep_state"]
    circadian = [
        float(getattr(e.payload, "c_value", 0.0))
        for e in result.events
        if e.event_type == "sleep_state"
    ]
    chemistry_ok = all(
        0.0 <= float(getattr(e.payload, ch)) <= 1.0
        for e in result.events
        if e.event_type == "neurochemical_state"
        for ch in CHANNELS
    )
    return {
        "config": "default chemistry+circadian, 9600 ticks",
        "s_min_observed": round(min(values), 4),
        "s_max_observed": round(max(values), 4),
        "s_within_unit_bounds": all(0.0 <= v <= 1.0 for v in values),
        "c_range_observed": [round(min(circadian), 4), round(max(circadian), 4)],
        "all_channels_within_0_1": chemistry_ok,
        "n_sleep_events": len(values),
    }


def e3_dwell_sensitivity() -> list[dict]:
    """Shorter max dwell -> more stage transitions (monotonic check)."""
    rows = []
    for cap in (2, 4, 8, 16):
        dwells = {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": cap} for s in STAGES}
        result = run(payload(ticks=1920, seed=99, dwells=dwells))
        transitions = sum(1 for e in result.events if e.event_type == "stage_transition")
        rows.append({"max_dwell_cap": cap, "transitions": transitions})
    monotonic = all(
        rows[i]["transitions"] >= rows[i + 1]["transitions"] for i in range(len(rows) - 1)
    )
    return {"rows": rows, "monotonic_nonincreasing": monotonic}


# --- E4: stress edges ------------------------------------------------------------


def e4_stress() -> list[dict]:
    results = []

    # E4a: minimal graph, top_k larger than node count is refused by config;
    # use equal sizes instead.
    try:
        result = run(
            payload(
                ticks=480,
                seed=5,
                replay_policy={
                    "synthetic_graph": {"node_count": 3, "edge_count": 3},
                    "selector": {"top_k": 3},
                    "replay_every_n_epochs": 10,
                },
            )
        )
        replays = [e for e in result.events if e.event_type == "memory_replay"]
        sizes = {len(e.payload.selected_node_ids) for e in replays}
        results.append(
            {
                "scenario": "minimal_graph_3_nodes_top_k3",
                "ok": True,
                "selection_sizes": sorted(sizes),
                "n_replays": len(replays),
            },
        )
    except Exception as exc:  # noqa: BLE001
        results.append(
            {"scenario": "minimal_graph_3_nodes_top_k3", "ok": False, "error": type(exc).__name__}
        )

    # E4b: extreme chemistry baselines (0 and 1) must stay clipped in [0,1].
    chem = {
        "baselines": {c: (0.0 if i % 2 == 0 else 1.0) for i, c in enumerate(CHANNELS)},
    }
    result = run(payload(ticks=480, seed=6, chemistry=chem))
    ok = all(
        0.0 <= float(getattr(e.payload, ch)) <= 1.0
        for e in result.events
        if e.event_type == "neurochemical_state"
        for ch in CHANNELS
    )
    results.append({"scenario": "extreme_baselines_0_and_1", "clipped_ok": bool(ok)})

    # E4c: very long night - invariants hold at scale.
    result = run(payload(ticks=28800, seed=7))
    seqs = [e.event_sequence for e in result.events]
    contiguous = seqs == list(range(1, len(seqs) + 1))
    results.append(
        {
            "scenario": "long_night_28800_ticks",
            "events": len(result.events),
            "sequence_contiguous": contiguous,
            "trace_hash": result.core_trace_hash[:12],
        }
    )

    # E4d: replay-every-epoch (heaviest replay load).
    result = run(
        payload(
            ticks=480,
            seed=8,
            replay_policy={
                "synthetic_graph": {"node_count": 50, "edge_count": 120},
                "selector": {"top_k": 5},
                "replay_every_n_epochs": 1,
            },
        )
    )
    replays = sum(1 for e in result.events if e.event_type == "memory_replay")
    results.append(
        {
            "scenario": "replay_every_epoch_topk5",
            "expected_replays": 480,
            "actual_replays": replays,
            "matches_schedule": replays == 480,
        }
    )
    return results


# --- E5: ensemble distribution ----------------------------------------------------


def e5_ensemble(n_members: int = 20, base_seed: int = 9000) -> dict:
    s_means, transitions, replays = [], [], []
    t0 = time.perf_counter()
    for index in range(n_members):
        result = run(payload(ticks=960, seed=base_seed + index))
        s_vals = [float(e.payload.s_value) for e in result.events if e.event_type == "sleep_state"]
        s_means.append(statistics.fmean(s_vals))
        transitions.append(sum(1 for e in result.events if e.event_type == "stage_transition"))
        replays.append(sum(1 for e in result.events if e.event_type == "memory_replay"))
    wall = time.perf_counter() - t0

    def stats(xs: list[float]) -> dict:
        return {
            "mean": round(statistics.fmean(xs), 4),
            "stdev": round(statistics.stdev(xs), 4) if len(xs) > 1 else 0.0,
            "min": round(min(xs), 4),
            "max": round(max(xs), 4),
        }

    hashes = set()
    for index in range(n_members):
        hashes.add(run(payload(ticks=960, seed=base_seed + index)).core_trace_hash)
    return {
        "members": n_members,
        "distinct_trace_hashes": len(hashes),
        "mean_s_value": stats(s_means),
        "stage_transitions": stats([float(x) for x in transitions]),
        "memory_replays": stats([float(x) for x in replays]),
        "wall_s_for_runs_only": round(wall, 2),
    }


FAMILIES = {
    "E1": e1_determinism,
    "E2": e2_scalability,
    "E3": lambda: {
        "uniform": e3_uniform_matrix(101),
        "nrem_biased": e3_nrem_biased(102),
        "process_s_bounds": e3_process_s_bounds(),
        "dwell_sensitivity": e3_dwell_sensitivity(),
    },
    "E4": e4_stress,
    "E5": e5_ensemble,
}


def main(argv: list[str]) -> int:
    wanted = argv or list(FAMILIES)
    out: dict[str, object] = {}
    for family in wanted:
        print(f"running {family} ...", flush=True)
        out[family] = FAMILIES[family]()
        print(json.dumps(out[family], indent=2)[:600], flush=True)

    (REPO / "exports").mkdir(exist_ok=True)
    target = REPO / "exports" / "_experiment_results.json"
    existing: dict = {}
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
    existing.update(out)
    existing["_meta"] = {
        "python": sys.version.split()[0],
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    target.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"\nraw -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
