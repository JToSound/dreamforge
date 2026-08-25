"""Sleep-regulation and stage-transition model units (section 5.1)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamforge.core.models.events import ALL_STAGES, StageName
from dreamforge.core.models.sleep_cycle import (
    DEFAULT_TRANSITIONS,
    CircadianConfig,
    DwellDistribution,
    ProcessSConfig,
    SleepRegulationModel,
    SleepStageTransitionModel,
    TransitionMatrixConfig,
    circadian_value,
)


def make_dwells(cap: int = 40) -> dict[StageName, DwellDistribution]:
    return {
        "Wake": DwellDistribution(min_epochs=2, weights=(1.0, 1.0), max_dwell_epochs=cap),
        "N1": DwellDistribution(min_epochs=2, weights=(2.0, 1.0), max_dwell_epochs=cap),
        "N2": DwellDistribution(min_epochs=4, weights=(1.0, 2.0, 1.0), max_dwell_epochs=cap),
        "N3": DwellDistribution(min_epochs=6, weights=(2.0, 1.0), max_dwell_epochs=cap),
        "REM": DwellDistribution(min_epochs=3, weights=(1.0, 1.0), max_dwell_epochs=cap),
    }


class TestProcessS:
    def test_wake_ascent_toward_smax(self) -> None:
        cfg = ProcessSConfig(s_initial=0.2)
        model = SleepRegulationModel(cfg, CircadianConfig(), epoch_seconds=30.0)
        prev = model.s_value
        for tick in range(100):
            s_value, _ = model.step(tick, "Wake")
            assert s_value > prev or s_value == cfg.s_max
            prev = s_value
        assert 0.0 <= model.s_value <= 1.0

    def test_sleep_descent_toward_smin(self) -> None:
        cfg = ProcessSConfig(s_initial=0.9)
        model = SleepRegulationModel(cfg, CircadianConfig(), epoch_seconds=30.0)
        prev = model.s_value
        for tick in range(200):
            s_value, _ = model.step(tick, "N2")
            assert s_value < prev or s_value == cfg.s_min
            prev = s_value
        assert 0.0 <= model.s_value <= 1.0

    def test_smin_lt_smax_required(self) -> None:
        with pytest.raises(ValueError, match="s_min"):
            ProcessSConfig(s_min=0.8, s_max=0.5)

    def test_sinitial_within_bounds(self) -> None:
        with pytest.raises(ValueError, match="s_initial"):
            ProcessSConfig(s_initial=1.5)

    def test_nonfinite_tau_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessSConfig(tau_wake_minutes=float("nan"))


class TestCircadian:
    def test_second_harmonic_off_by_default(self) -> None:
        cfg = CircadianConfig()
        assert cfg.amplitude_a2 == 0.0
        values = [circadian_value(cfg, tick, 30.0) for tick in range(2880)]
        low, high = cfg.range()
        assert all(low <= v <= high for v in values)

    def test_second_harmonic_requires_period(self) -> None:
        with pytest.raises(ValueError, match="period_t2"):
            CircadianConfig(amplitude_a2=0.1)

    def test_known_value(self) -> None:
        # b + A*sin(0) with phi=0 at t=0 is exactly the baseline.
        cfg = CircadianConfig(baseline_b=0.5, amplitude_a=0.15)
        assert circadian_value(cfg, 0, 30.0) == pytest.approx(0.5)


class TestTransitions:
    def _model(self, seed: int = 7) -> SleepStageTransitionModel:
        matrix = TransitionMatrixConfig(probabilities=DEFAULT_TRANSITIONS)
        rng = np.random.Generator(np.random.PCG64(seed))
        return SleepStageTransitionModel(matrix, make_dwells(), rng=rng)

    def test_every_emitted_transition_is_allowed(self) -> None:
        model = self._model()
        for _ in range(400):
            info, _ticks = model.advance(tick=0)
            if info is not None:
                row = DEFAULT_TRANSITIONS[info.from_stage]
                assert info.to_stage in row and row[info.to_stage] > 0.0
                assert info.completed_dwell_epochs >= 1
                assert info.next_dwell_epochs >= 1

    def test_resample_invariants_hold(self) -> None:
        # Valid configs guarantee drawn dwells sit inside declared support, so
        # the capped-resampling defence must never fire: the counter stays
        # zero across many advances.
        model = self._model()
        for _ in range(500):
            model.advance(tick=0)
        assert model.resample_count == 0

    def test_degenerate_dwell_completed_equals_drawn(self) -> None:
        """Regression: completed_dwell_epochs must equal the drawn dwell.

        Found experimentally (scripts/microprobe_dwell.py): with a degenerate
        ``min_epochs=3, weights=(1.0,)`` prior every transition reported
        ``completed=4`` because the boundary tick was counted once for the old
        stage and once again as the first epoch of the new stage.
        """
        matrix = TransitionMatrixConfig(
            probabilities={
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(ALL_STAGES)}
                for i, s in enumerate(ALL_STAGES)
            },
        )
        dwells = {
            s: DwellDistribution(min_epochs=3, weights=(1.0,), max_dwell_epochs=10)
            for s in ALL_STAGES
        }
        model = SleepStageTransitionModel(matrix, dwells, rng=np.random.default_rng(7))
        completed: list[int] = []
        for tick in range(200):
            info, _ticks_in_stage = model.advance(tick)
            if info is not None:
                completed.append(info.completed_dwell_epochs)
        assert completed, "expected transitions to occur"
        assert set(completed) == {3}

    def test_completed_dwell_matches_drawn_distribution(self) -> None:
        """Multi-point prior: per-stage completed means track drawn means."""
        matrix = TransitionMatrixConfig(probabilities=DEFAULT_TRANSITIONS)
        dwells = {
            s: DwellDistribution(min_epochs=m, weights=w, max_dwell_epochs=40)
            for s, m, w in (
                ("Wake", 2, (1.0, 3.0)),
                ("N1", 2, (3.0, 1.0)),
                ("N2", 3, (1.0, 1.0, 4.0)),
                ("N3", 5, (2.0, 2.0, 1.0, 1.0)),
                ("REM", 3, (1.0, 2.0)),
            )
        }
        model = SleepStageTransitionModel(matrix, dwells, rng=np.random.default_rng(11))
        sums: dict[str, list[int]] = {s: [] for s in ALL_STAGES}
        for tick in range(4000):
            info, _ticks_in_stage = model.advance(tick)
            if info is not None:
                sums[info.from_stage].append(info.completed_dwell_epochs)
        expected = {
            "Wake": (2 * 1 + 3 * 3) / 4,
            "N1": (2 * 3 + 3 * 1) / 4,
            "N2": (3 * 1 + 4 * 1 + 5 * 4) / 6,
            "N3": (5 * 2 + 6 * 2 + 7 * 1 + 8 * 1) / 6,
            "REM": (3 * 1 + 4 * 2) / 3,
        }
        for stage, want in expected.items():
            got = sum(sums[stage]) / len(sums[stage])
            assert abs(got - want) < 0.35, (stage, got, want)

    def test_support_exceeding_cap_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="support exceeds"):
            DwellDistribution(min_epochs=10, weights=(1.0,), max_dwell_epochs=5)

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            DwellDistribution(min_epochs=1, weights=(1.0, -0.5), max_dwell_epochs=10)

    def test_zero_weight_sum_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            DwellDistribution(min_epochs=1, weights=(0.0, 0.0), max_dwell_epochs=10)

    def test_unknown_initial_stage_rejected(self) -> None:
        matrix = TransitionMatrixConfig(probabilities=DEFAULT_TRANSITIONS)
        rng = np.random.Generator(np.random.PCG64(1))
        with pytest.raises(ValueError, match="initial stage"):
            SleepStageTransitionModel(matrix, make_dwells(), rng=rng, initial_stage="N4")  # type: ignore[arg-type]

    def test_missing_dwell_rejected(self) -> None:
        matrix = TransitionMatrixConfig(probabilities=DEFAULT_TRANSITIONS)
        dwells = make_dwells()
        del dwells["REM"]
        rng = np.random.Generator(np.random.PCG64(1))
        with pytest.raises(ValueError, match="dwell"):
            SleepStageTransitionModel(matrix, dwells, rng=rng)

    def test_row_must_sum_to_one(self) -> None:
        bad = {k: dict(v) for k, v in DEFAULT_TRANSITIONS.items()}
        bad["Wake"]["N1"] = 0.9  # now sums to 1.2
        with pytest.raises(ValueError, match="sums to"):
            TransitionMatrixConfig(probabilities=bad)  # type: ignore[arg-type]

    def test_all_stages_covered(self) -> None:
        assert set(ALL_STAGES) == {"Wake", "N1", "N2", "N3", "REM"}
