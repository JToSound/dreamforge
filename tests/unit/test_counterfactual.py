"""Counterfactual engine units (§5.5): fixed pairs, exact accounting, labels."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dreamforge.core.config import load_config
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.simulation.counterfactual import (
    DISCLAIMER,
    CounterfactualComparison,
    CounterfactualError,
    CounterfactualSpec,
    metrics_delta,
    run_counterfactual,
)


def make_config(total_ticks: int = 60, seed: int = 1000):
    payload = {
        "schema_version": "1.0",
        "run_id": f"cf-base-{seed}",
        "run_seed": seed,
        "total_ticks": total_ticks,
        "transitions": _transitions(),
        "dwells": _dwells(),
        "chemistry": _chemistry(),
        "replay_policy": {
            "synthetic_graph": {"node_count": 6, "edge_count": 10},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 4,
        },
    }
    return load_config(payload)


def clock() -> FixedClock:
    return FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC))


class TestCounterfactual:
    def test_seed_shift_changes_hash_and_enumerates_parameter(self) -> None:
        base = make_config(seed=1000)
        spec = CounterfactualSpec(base_config=base, override_fields={}, seed_shift=1)
        comparison = run_counterfactual(spec, clock())
        assert not comparison.identical_trace_hash
        assert comparison.changed_parameters[0].field == "run_seed"
        assert comparison.control_seed == 1000
        assert comparison.changed_seed == 1001

    def test_deterministic_identical_bytes(self) -> None:
        base = make_config(seed=2000)
        spec = CounterfactualSpec(
            base_config=base,
            override_fields={"initial_stage": "N2"},
        )
        a = run_counterfactual(spec, clock()).to_canonical_bytes()
        b = run_counterfactual(spec, clock()).to_canonical_bytes()
        assert a == b

    def test_field_override_enumerated_exactly(self) -> None:
        base = make_config(seed=3000)
        spec = CounterfactualSpec(
            base_config=base,
            override_fields={"epoch_seconds": 60.0},
        )
        comparison = run_counterfactual(spec, clock())
        fields = [p.field for p in comparison.changed_parameters]
        assert fields == ["epoch_seconds"]
        assert comparison.changed_parameters[0].control_value == 30.0
        assert comparison.changed_parameters[0].changed_value == 60.0

    def test_disallowlisted_field_refused(self) -> None:
        base = make_config()
        with pytest.raises(CounterfactualError, match="allowlist"):
            CounterfactualSpec(
                base_config=base,
                override_fields={"process_s": {"s_min": 0.5}},
            )

    def test_no_change_refused(self) -> None:
        base = make_config()
        with pytest.raises(CounterfactualError, match="at least one"):
            run_counterfactual(
                CounterfactualSpec(base_config=base, override_fields={}),
                clock(),
            )

    def test_labels_and_disclaimer_always_present(self) -> None:
        base = make_config(seed=4000)
        spec = CounterfactualSpec(
            base_config=base,
            override_fields={"initial_stage": "REM"},
        )
        comparison = run_counterfactual(spec, clock())
        assert isinstance(comparison, CounterfactualComparison)
        assert comparison.output_class == "mechanistic_proxy"
        assert comparison.visible_label == "Simulated model proxy — not a biological measurement"
        assert "not causal biological effects" in comparison.disclaimer
        assert comparison.disclaimer == DISCLAIMER

    def test_metrics_delta_numeric(self) -> None:
        base = make_config(seed=5000)
        spec = CounterfactualSpec(
            base_config=base,
            override_fields={"initial_stage": "N3"},
        )
        deltas = metrics_delta(run_counterfactual(spec, clock()))
        for name, value in deltas.items():
            assert isinstance(value, float)
            del name, value


# --- inline config fragments -------------------------------------------------

_STAGES = ("Wake", "N1", "N2", "N3", "REM")


def _transitions() -> dict:
    return {
        "probabilities": {
            s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(_STAGES)}
            for i, s in enumerate(_STAGES)
        },
    }


def _dwells() -> dict:
    return {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in _STAGES}


def _chemistry() -> dict:
    channels = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
    return {
        "baselines": {c: 0.5 for c in channels},
        "stage_modulation": {c: {s: 0.0 for s in _STAGES} for c in channels},
        "circadian_gain": {c: 0.0 for c in channels},
    }
