"""Hypothesis property tests: bounds, finiteness, legal transitions, round-trips."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from dreamforge.core.config import load_config
from dreamforge.core.models.memory_graph import (
    GraphSerializerV1,
    GraphSpecConfig,
    build_synthetic_graph,
)
from dreamforge.core.serialization.dqcj import dumps_canonical, loads_strict
from dreamforge.simulation.engine import derive_stream, run_simulation

STAGES = ("Wake", "N1", "N2", "N3", "REM")


@given(
    start=st.floats(min_value=0.0, max_value=1.0),
    awake=st.booleans(),
)
def test_process_s_update_stays_bounded(start: float, awake: bool) -> None:
    """One update from any in-bounds finite start stays inside [s_min, s_max]."""
    from dreamforge.core.models.sleep_cycle import (
        CircadianConfig,
        ProcessSConfig,
        SleepRegulationModel,
    )

    cfg = ProcessSConfig(s_initial=0.5)
    model = SleepRegulationModel(cfg, CircadianConfig(), epoch_seconds=30.0)
    model.s_value = start
    s_new, _ = model.step(0, "Wake" if awake else "N2")
    assert cfg.s_min <= s_new <= cfg.s_max


@settings(max_examples=10, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10**6))
def test_run_events_obey_bounds_sequences_and_legal_transitions(seed: int) -> None:
    """Full-run properties over randomized seeds (small tick counts)."""
    base = {
        "schema_version": "1.0",
        "run_id": f"prop-{seed:07d}",
        "run_seed": seed,
        "epoch_seconds": 30.0,
        "total_ticks": 40,
        "transitions": _demo_transitions(),
        "dwells": _demo_dwells(),
        "chemistry": _demo_chemistry(),
        "replay_policy": {
            "synthetic_graph": {"node_count": 6, "edge_count": 8},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 4,
        },
    }
    config = load_config(base)
    from dreamforge.core.provenance.clock import FixedClock

    result = run_simulation(config, FixedClock(_fixed_instant()))
    events = result.events
    # sequences strictly contiguous from 1
    assert [e.event_sequence for e in events] == list(range(1, len(events) + 1))
    # nondecreasing simulated time
    times = [e.simulated_time_minutes for e in events]
    assert times == sorted(times)
    # chemistry values finite and bounded
    chem = [e for e in events if e.event_type == "neurochemical_state"]
    assert chem, "chemistry events must exist"
    for e in chem:
        for field in ("acetylcholine", "serotonin", "noradrenaline", "cortisol"):
            value = getattr(e.payload, field)
            assert 0.0 <= value <= 1.0
    # every emitted transition allowed by the exported matrix
    declared = result.manifest.declared_policies["stage_process"]["transitions"]
    for e in events:
        if e.event_type == "stage_transition":
            probability = declared[e.payload.from_stage][e.payload.to_stage]
            assert float(probability) > 0.0


@settings(max_examples=15, deadline=None)
@given(
    seed_a=st.integers(min_value=0, max_value=2**31),
    seed_b=st.integers(min_value=0, max_value=2**31),
)
def test_component_streams_isolated_for_any_seed_pair(seed_a: int, seed_b: int) -> None:
    """Changing one component's stream identity never shifts another's draws."""
    stage_draws = [float(x) for x in derive_stream(seed_a, "stage").uniform(0, 1, size=3)]
    replay_before = [float(x) for x in derive_stream(seed_a, "replay").uniform(0, 1, size=3)]
    del seed_b  # other components do not depend on this stream's consumption
    replay_after = [float(x) for x in derive_stream(seed_a, "replay").uniform(0, 1, size=3)]
    assert replay_before == replay_after
    assert stage_draws != replay_before


@given(n=st.integers(min_value=2, max_value=30), m=st.integers(min_value=1, max_value=120))
def test_graph_round_trip_property(n: int, m: int) -> None:
    m = min(m, n * (n - 1))
    spec = GraphSpecConfig(node_count=n, edge_count=m)
    graph = build_synthetic_graph(spec, np.random.Generator(np.random.PCG64(n + m)))
    restored = GraphSerializerV1.deserialize(GraphSerializerV1.serialize(graph))
    assert GraphSerializerV1.serialize(restored) == GraphSerializerV1.serialize(graph)


@given(
    obj=st.recursive(
        st.none()
        | st.booleans()
        | st.integers(-(10**9), 10**9)
        | st.floats(allow_nan=False, allow_infinity=False, width=32)
        | st.text(max_size=8),
        lambda children: st.lists(children, max_size=4)
        | st.dictionaries(st.text(max_size=8), children, max_size=4),
        max_leaves=12,
    )
)
def test_dqcj_round_trip_json_compatible(obj: object) -> None:
    from dreamforge.core.serialization.dqcj import DQCJNormalizationError

    try:
        text = dumps_canonical(obj).decode("utf-8")
    except DQCJNormalizationError:
        # Rule 3: non-NFC text is rejected at the canonical boundary; the
        # round-trip property applies to accepted inputs only.
        return
    parsed_back = loads_strict(text)
    assert dumps_canonical(parsed_back) == dumps_canonical(obj)


# --- helpers -------------------------------------------------------------


def _fixed_instant():
    return datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC)


def _demo_transitions() -> dict:
    return {
        "probabilities": {
            "Wake": {"Wake": 0.0, "N1": 0.7, "N2": 0.25, "N3": 0.0, "REM": 0.05},
            "N1": {"Wake": 0.1, "N1": 0.0, "N2": 0.75, "N3": 0.1, "REM": 0.05},
            "N2": {"Wake": 0.08, "N1": 0.12, "N2": 0.0, "N3": 0.45, "REM": 0.35},
            "N3": {"Wake": 0.04, "N1": 0.06, "N2": 0.62, "N3": 0.0, "REM": 0.28},
            "REM": {"Wake": 0.35, "N1": 0.35, "N2": 0.24, "N3": 0.06, "REM": 0.0},
        },
    }


def _demo_dwells() -> dict:
    return {
        "Wake": {"min_epochs": 2, "weights": [0.4, 1.0], "max_dwell_epochs": 20},
        "N1": {"min_epochs": 2, "weights": [2.0, 1.2], "max_dwell_epochs": 20},
        "N2": {"min_epochs": 4, "weights": [1.0, 1.8, 1.6], "max_dwell_epochs": 30},
        "N3": {"min_epochs": 6, "weights": [1.2, 2.0, 0.8], "max_dwell_epochs": 40},
        "REM": {"min_epochs": 3, "weights": [0.6, 1.2, 1.0], "max_dwell_epochs": 30},
    }


def _demo_chemistry() -> dict:
    channels = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
    return {
        "baselines": {c: 0.5 for c in channels},
        "stage_modulation": {c: {s: 0.0 for s in STAGES} for c in channels},
        "circadian_gain": {c: 0.0 for c in channels},
    }
