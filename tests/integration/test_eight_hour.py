"""End-to-end deterministic 8-hour integration test (MASTER_PROMPT.md M1).

Runs the full 960-epoch offline trace, asserts hash determinism, event
invariants, export/import parity, and render-without-execution semantics.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dreamforge.core.config import load_config
from dreamforge.simulation.engine import run_simulation
from dreamforge.simulation.export_import import import_and_verify, write_export

pytestmark = [pytest.mark.integration]


def test_960_epoch_trace_deterministic_and_verified(
    demo_config_dict,
    fixed_clock,
    tmp_path,
) -> None:
    config = load_config(demo_config_dict)  # total_ticks = 960
    assert config.total_ticks == 960

    result_a = run_simulation(config, fixed_clock)
    result_b = run_simulation(config, fixed_clock)

    # identical inputs -> identical core bytes/hash (M1 gate)
    assert result_a.core_trace_hash == result_b.core_trace_hash
    assert result_a.manifest.manifest_hash() == result_b.manifest.manifest_hash()

    events = result_a.events
    # every epoch emitted exactly one sleep_state and one chemistry record
    sleep_states = [e for e in events if e.event_type == "sleep_state"]
    chem = [e for e in events if e.event_type == "neurochemical_state"]
    assert len(sleep_states) == 960
    assert len(chem) == 960
    assert [e.tick for e in sleep_states] == list(range(960))

    # sequences contiguous from 1; time nondecreasing; ticks consistent
    assert [e.event_sequence for e in events] == list(range(1, len(events) + 1))
    times = [e.simulated_time_minutes for e in events]
    assert times == sorted(times)
    last_tick = max(e.tick for e in events)
    assert last_tick * config.epoch_seconds / 60.0 == pytest.approx(times[-1])

    # proxies finite and bounded across all epochs
    for e in chem:
        for field in ("acetylcholine", "serotonin", "noradrenaline", "cortisol"):
            value = getattr(e.payload, field)
            assert 0.0 <= value <= 1.0

    # transitions permitted by exported matrix; dwells bounded by cap
    declared = result_a.manifest.declared_policies["stage_process"]
    matrix = declared["transitions"]
    cap = int(declared["dwells_max_cap"])
    n_transitions = 0
    for e in events:
        if e.event_type == "stage_transition":
            p = float(matrix[e.payload.from_stage][e.payload.to_stage])
            assert p > 0.0
            assert 1 <= int(e.payload.next_dwell_epochs) <= cap
            n_transitions += 1
    assert n_transitions > 10  # a real night changes stages many times

    # replays exist with bounded selections
    replays = [e for e in events if e.event_type == "memory_replay"]
    expected_replays = len(range(0, 960, config.replay_policy.replay_every_n_epochs))
    assert len(replays) == expected_replays
    for e in replays:
        k = config.replay_policy.selector.top_k
        assert len(e.payload.selected_node_ids) == k

    # --- export / import parity -------------------------------------------
    out_dir = tmp_path / "export_demo"
    write_export(
        out_dir=out_dir,
        events=events,
        manifest=result_a.manifest,
        config=config,
        graph_snapshot=result_a.graph_snapshot,
    )
    imported, report = import_and_verify(out_dir)
    assert report.ok
    assert imported.manifest.core_trace_hash == result_a.core_trace_hash
    assert len(imported.events) == len(events)

    # tampering with any byte must fail verification (fail closed)
    ndjson_path = out_dir / "events.ndjson"
    original_bytes = ndjson_path.read_bytes()
    tampered = original_bytes.replace(b'"stage":"Wake"', b'"stage":"Wake" ', 1)
    if tampered == original_bytes:  # pragma: no cover - defensive
        pytest.skip("tamper target not present")
    ndjson_path.write_bytes(tampered)
    from dreamforge.simulation.export_import import ImportError_

    with pytest.raises(ImportError_):
        import_and_verify(out_dir)
    ndjson_path.write_bytes(original_bytes)


def test_render_without_execution(tmp_path) -> None:
    """Verifying an existing export never imports the engine run loop."""
    # Build a tiny valid export first.
    from datetime import UTC, datetime

    from dreamforge.core.provenance.clock import FixedClock

    payload = {
        "schema_version": "1.0",
        "run_id": "render-check-1",
        "run_seed": 5,
        "total_ticks": 4,
        "transitions": _transitions(),
        "dwells": _dwells(),
        "chemistry": _chemistry(),
        "replay_policy": {
            "synthetic_graph": {"node_count": 4, "edge_count": 4},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 2,
        },
    }
    config = load_config(payload)
    result = run_simulation(config, FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    write_export(
        out_dir=tmp_path / "x",
        events=result.events,
        manifest=result.manifest,
        config=config,
        graph_snapshot=result.graph_snapshot,
    )

    probe = (
        "import sys;\n"
        "from dreamforge.simulation.export_import import import_and_verify;\n"
        f"_, report = import_and_verify({str(tmp_path / 'x')!r});\n"
        "assert report.ok;\n"
        "loaded = 'dreamforge.simulation.engine' in sys.modules;\n"
        "print('ENGINE_LOADED' if loaded else 'ENGINE_NOT_LOADED')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert "ENGINE_NOT_LOADED" in completed.stdout


def test_demo_entrypoint_runs_offline_end_to_end(tmp_path) -> None:
    """The documented demo command works against the bundled config."""
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = tmp_path / "demo_out"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "dreamforge.demo",
            str(repo_root / "examples/configs/demo_8h.json"),
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        cwd=str(repo_root),
        env={
            "PYTHONPATH": str(repo_root / "src"),
            "PATH": "",
            "PYTHONIOENCODING": "utf-8",
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert "core_trace_hash:" in completed.stdout
    assert "Simulated model proxy — not a biological measurement" in completed.stdout
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_count"] > 2000


# --- minimal inline config fragments ---------------------------------------


def _transitions() -> dict:
    return {
        "probabilities": {
            s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(_STAGES)}
            for i, s in enumerate(_STAGES)
        },
    }


_STAGES = ("Wake", "N1", "N2", "N3", "REM")


def _dwells() -> dict:
    return {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in _STAGES}


def _chemistry() -> dict:
    channels = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
    return {
        "baselines": {c: 0.5 for c in channels},
        "stage_modulation": {c: {s: 0.0 for s in _STAGES} for c in channels},
        "circadian_gain": {c: 0.0 for c in channels},
    }
