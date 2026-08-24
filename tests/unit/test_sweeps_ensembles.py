"""Parameter sweep + ensemble units (M4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dreamforge.core.config import load_config
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.simulation.counterfactual import CounterfactualError
from dreamforge.simulation.ensemble import run_ensemble
from dreamforge.simulation.sweeps import ParameterSweep, ParameterSweepResult


def make_config(seed: int = 9000, total_ticks: int = 40):
    stages = ("Wake", "N1", "N2", "N3", "REM")
    payload = {
        "schema_version": "1.0",
        "run_id": f"sweep-base-{seed}",
        "run_seed": seed,
        "total_ticks": total_ticks,
        "transitions": {
            "probabilities": {
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(stages)}
                for i, s in enumerate(stages)
            },
        },
        "dwells": {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in stages},
        "chemistry": {
            "baselines": {
                c: 0.5 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "stage_modulation": {
                c: {s: 0.0 for s in stages}
                for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "circadian_gain": {
                c: 0.0 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 5, "edge_count": 8},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 4,
        },
    }
    return load_config(payload)


def clock() -> FixedClock:
    return FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC))


class TestParameterSweep:
    def test_cells_sorted_by_field_then_value_order(self) -> None:
        sweep = ParameterSweep(
            make_config(),
            grid={"initial_stage": ("N2", "REM"), "epoch_seconds": (15.0,)},
        )
        cells = sweep._cells()
        assert [field for field, _value in cells] == [
            "epoch_seconds",
            "initial_stage",
            "initial_stage",
        ]
        initial_values = [value for field, value in cells if field == "initial_stage"]
        assert initial_values == ["N2", "REM"]

    def test_deterministic_identical_bytes(self) -> None:
        def run() -> bytes:
            sweep = ParameterSweep(
                make_config(),
                grid={"initial_stage": ("N2", "N3")},
            )
            return sweep.run(clock()).to_canonical_bytes()

        assert run() == run()

    def test_empty_grid_refused(self) -> None:
        with pytest.raises(CounterfactualError, match="at least one"):
            ParameterSweep(make_config(), grid={})

    def test_cap_enforced(self) -> None:
        big = tuple(range(65))
        with pytest.raises(CounterfactualError, match="cap is"):
            ParameterSweep(make_config(), grid={"total_ticks": big})

    def test_result_labeled(self) -> None:
        result = ParameterSweep(
            make_config(),
            grid={"initial_stage": ("N2",)},
        ).run(clock())
        assert isinstance(result, ParameterSweepResult)
        assert result.output_class == "mechanistic_proxy"
        assert result.visible_label == "Simulated model proxy — not a biological measurement"
        assert len(result.cells) == 1


class TestEnsemble:
    def test_members_distinct_seeds_and_hashes(self) -> None:
        run = run_ensemble(make_config(seed=7000), (0, 1, 2), clock())
        seeds = [member.seed for member in run.members]
        assert seeds == [7000, 7001, 7002]
        assert run.distinct_trace_hashes >= 1

    def test_aggregates_derive_from_members(self) -> None:
        run = run_ensemble(make_config(seed=7100), (0, 5), clock())
        means = [float(m.metrics.mean_s_value) for m in run.members]
        agg = run.aggregate_mean_s_value
        assert agg.min == pytest.approx(min(means))
        assert agg.max == pytest.approx(max(means))
        assert agg.mean == pytest.approx(sum(means) / len(means))

    def test_duplicate_effective_seed_refused(self) -> None:
        with pytest.raises(CounterfactualError, match="duplicate effective seeds"):
            run_ensemble(make_config(seed=7200), (0, 0), clock())

    def test_empty_shifts_refused(self) -> None:
        with pytest.raises(CounterfactualError, match="at least one"):
            run_ensemble(make_config(), (), clock())

    def test_labeled(self) -> None:
        run = run_ensemble(make_config(seed=7300), (1,), clock())
        assert run.output_class == "mechanistic_proxy"
        assert "not causal biological effects" in run.disclaimer
