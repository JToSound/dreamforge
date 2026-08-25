"""Sleep-regulation proxy and stage-transition model (MASTER_PROMPT.md 5.1).

Two conceptual sub-models live here:

1. ``SleepRegulationModel`` — a two-process-inspired proxy. Process S follows
   exponential approach to ``S_max`` while awake and ``S_min`` while asleep;
   the circadian proxy ``C(t)`` is a sum of up to two sinusoids with the
   second harmonic disabled by default. All values are dimensionless
   constructs in [0, 1] after configuration validation.

   Update order within one epoch (documented contract, tested):
       a. classify awake/asleep from the *current* stage (Wake = awake);
       b. advance S by the corresponding exponential update over
          ``epoch_seconds``;
       c. clip S into ``[S_min, S_max]`` (bounds are inclusive);
       d. evaluate ``C(t)`` at the tick's simulated time.

   Sign convention: larger S = more homeostatic sleep pressure; C(t) is a
   dimensionless oscillator in ``[b - A - A2, b + A + A2]`` where higher
   values conventionally indicate the circadian-promoting portion of the
   cycle. Neither value is a physiological measurement.

2. ``SleepStageTransitionModel`` — a semi-Markov process over
   Wake/N1/N2/N3/REM at the simulation resolution of ``epoch_seconds``
   (default 30 s). This is explicitly *not* PSG scoring. Every dwell is drawn
   as a bounded integer epoch count from a declared discrete distribution
   under a hard cap, with a resampling counter for exhausted draws; every
   emitted transition is guaranteed allowed by the exported matrix.

All randomness flows through an injected :class:`numpy.random.Generator`
(the engine supplies each component's isolated child stream).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from dreamforge.core.models.events import ALL_STAGES, StageName


def _finite(value: float) -> float:
    if not math.isfinite(value):
        msg = f"value must be finite, got {value!r}"
        raise ValueError(msg)
    return value


class _ValidatedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=True)


class ProcessSConfig(_ValidatedModel):
    """Configuration for the homeostatic proxy."""

    s_min: float = Field(default=0.0, ge=0.0, le=1.0)
    s_max: float = Field(default=1.0, ge=0.0, le=1.0)
    s_initial: float = Field(default=0.5)
    tau_wake_minutes: float = Field(default=1140.0, gt=0.0)  # assumption-grade
    tau_sleep_minutes: float = Field(default=72.0, gt=0.0)  # assumption-grade

    @model_validator(mode="after")
    def _check(self) -> ProcessSConfig:
        _finite(self.s_min)
        _finite(self.s_max)
        _finite(self.s_initial)
        _finite(self.tau_wake_minutes)
        _finite(self.tau_sleep_minutes)
        if not self.s_min < self.s_max:
            msg = "s_min must be strictly less than s_max"
            raise ValueError(msg)
        if not self.s_min <= self.s_initial <= self.s_max:
            msg = "s_initial must lie within [s_min, s_max]"
            raise ValueError(msg)
        return self


class CircadianConfig(_ValidatedModel):
    """Configuration for the sinusoidal circadian proxy C(t).

    Time base: simulated minutes since run start. ``phi``/``phi2`` are phases
    in minutes within one period (wrapped into [0, T) / [0, T2)).
    """

    baseline_b: float = Field(default=0.5)
    amplitude_a: float = Field(default=0.15, ge=0.0)
    period_t_minutes: float = Field(default=1440.0, gt=0.0)
    phase_phi_minutes: float = Field(default=0.0)
    amplitude_a2: float = Field(default=0.0, ge=0.0)  # second harmonic OFF by default
    period_t2_minutes: float | None = Field(default=None, gt=0.0)
    phase_phi2_minutes: float = Field(default=0.0)

    @model_validator(mode="after")
    def _check(self) -> CircadianConfig:
        for name in (
            "baseline_b",
            "amplitude_a",
            "period_t_minutes",
            "phase_phi_minutes",
            "amplitude_a2",
            "phase_phi2_minutes",
        ):
            _finite(getattr(self, name))
        if self.amplitude_a2 > 0.0 and self.period_t2_minutes is None:
            msg = "amplitude_a2 > 0 requires period_t2_minutes"
            raise ValueError(msg)
        return self

    def range(self) -> tuple[float, float]:
        """Return the closed interval C(t) can take."""
        low = (
            self.baseline_b
            - self.amplitude_a
            - (self.amplitude_a2 if self.period_t2_minutes else 0.0)
        )
        high = (
            self.baseline_b
            + self.amplitude_a
            + (self.amplitude_a2 if self.period_t2_minutes else 0.0)
        )
        return low, high


class SleepRegulationModel:
    """Deterministic two-process-inspired regulatory proxy."""

    def __init__(
        self,
        s_config: ProcessSConfig,
        c_config: CircadianConfig,
        epoch_seconds: float,
    ) -> None:
        """Validate configs and freeze epoch length (> 0 seconds)."""
        if epoch_seconds <= 0:
            msg = "epoch_seconds must be positive"
            raise ValueError(msg)
        self._s = s_config
        self._c = c_config
        self._epoch_seconds = float(epoch_seconds)
        self.s_value: float = s_config.s_initial

    def _advance_s(self, *, awake: bool) -> float:
        cfg = self._s
        dt_minutes = self._epoch_seconds / 60.0
        if awake:
            target, tau = cfg.s_max, cfg.tau_wake_minutes
            new = target - (target - self.s_value) * math.exp(-dt_minutes / tau)
        else:
            target, tau = cfg.s_min, cfg.tau_sleep_minutes
            new = target + (self.s_value - target) * math.exp(-dt_minutes / tau)
        # Clip last (documented order): exp cannot overshoot, clip guards
        # accumulated float drift only.
        return min(max(new, cfg.s_min), cfg.s_max)

    def step(self, tick: int, stage: StageName) -> tuple[float, float]:
        """Advance one epoch; return ``(s_value, c_value)`` for that tick."""
        awake = stage == "Wake"
        self.s_value = self._advance_s(awake=awake)
        c_value = circadian_value(self._c, tick, self._epoch_seconds)
        return self.s_value, c_value


def circadian_value(config: CircadianConfig, tick: int, epoch_seconds: float) -> float:
    """Evaluate the circadian proxy at simulated time of ``tick``."""
    t_minutes = tick * epoch_seconds / 60.0
    two_pi = 2.0 * math.pi
    value = config.baseline_b
    value += config.amplitude_a * math.sin(
        two_pi
        * ((t_minutes - config.phase_phi_minutes) % config.period_t_minutes)
        / config.period_t_minutes,
    )
    if config.period_t2_minutes is not None and config.amplitude_a2 > 0.0:
        t2 = config.period_t2_minutes
        value += config.amplitude_a2 * math.sin(
            2.0 * two_pi * ((t_minutes - config.phase_phi2_minutes) % t2) / t2,
        )
    return value


class DwellDistribution(_ValidatedModel):
    """Bounded integer-epoch dwell distribution for one stage.

    ``weights[k]`` is the unnormalized probability of dwelling exactly
    ``min_epochs + k`` epochs. Weights must be finite, non-negative, and sum
    to a positive number; they are normalized internally.
    """

    min_epochs: int = Field(ge=1)
    weights: tuple[float, ...]
    max_dwell_epochs: int = Field(gt=1)

    @model_validator(mode="after")
    def _check(self) -> DwellDistribution:
        span = len(self.weights)
        if span == 0:
            msg = "weights must be non-empty"
            raise ValueError(msg)
        if any((not math.isfinite(w)) or w < 0.0 for w in self.weights):
            msg = "dwell weights must be finite and non-negative"
            raise ValueError(msg)
        total = sum(self.weights)
        if total <= 0.0:
            msg = "dwell weights must sum to a positive number"
            raise ValueError(msg)
        if self.min_epochs + span - 1 > self.max_dwell_epochs:
            msg = "distribution support exceeds max_dwell_epochs"
            raise ValueError(msg)
        return self


def dwell_distribution_is_degenerate(dwell: DwellDistribution) -> bool:
    """True when the distribution always yields the same dwell length.

    A distribution is *degenerate* when its normalized weights put all mass
    on a single support point (e.g. ``weights=[1.0]``): every draw is
    identical, so stage-transition counts become structurally fixed rather
    than stochastic. Discovered experimentally — see docs/EXPERIMENTS.md
    (E3 dwell-cap sensitivity) and docs/PERFORMANCE.md.
    """
    positive = [w for w in dwell.weights if w > 0.0]
    if len(positive) != 1:
        return False
    return bool(min(positive) / sum(positive) >= 1.0 - 1e-12)


def config_dwell_degeneracy(
    dwells: dict[StageName, DwellDistribution],
) -> dict[str, bool]:
    """Per-stage degeneracy map for manifest declaration."""
    return {stage: dwell_distribution_is_degenerate(d) for stage, d in sorted(dwells.items())}


DEFAULT_DWELL_WEIGHTS: dict[StageName, tuple[float, ...]] = {
    "Wake": (0.4, 1.0, 1.6, 2.2),
    "N1": (2.0, 1.2, 0.6),
    "N2": (1.0, 1.8, 2.2, 1.6, 1.0, 0.6),
    "N3": (1.2, 2.0, 2.4, 1.8, 1.2, 0.8, 0.5, 0.3),
    "REM": (0.6, 1.2, 1.8, 1.4, 1.0, 0.7),
}

DEFAULT_TRANSITIONS: dict[StageName, dict[StageName, float]] = {
    # Rows are complete stage distributions including an explicit zero
    # diagonal (the scheduler always changes state at dwell expiry).
    "Wake": {"Wake": 0.0, "N1": 0.70, "N2": 0.25, "N3": 0.0, "REM": 0.05},
    "N1": {"Wake": 0.10, "N1": 0.0, "N2": 0.75, "N3": 0.10, "REM": 0.05},
    "N2": {"Wake": 0.08, "N1": 0.12, "N2": 0.0, "N3": 0.45, "REM": 0.35},
    "N3": {"Wake": 0.04, "N1": 0.06, "N2": 0.62, "N3": 0.0, "REM": 0.28},
    "REM": {"Wake": 0.35, "N1": 0.35, "N2": 0.24, "N3": 0.06, "REM": 0.0},
}


class TransitionMatrixConfig(_ValidatedModel):
    """Exported transition policy: rows must be distributions incl. diagonal.

    The diagonal (staying put across a boundary event) is legal but never
    selected by the scheduler because dwell expiry always changes state via
    this matrix's off-diagonal mass; keeping the diagonal in the exported
    matrix documents that no transition is forced when its row would be
    degenerate.
    """

    probabilities: dict[StageName, dict[StageName, float]]

    @model_validator(mode="after")
    def _check(self) -> TransitionMatrixConfig:
        if set(self.probabilities) != set(ALL_STAGES):
            msg = "matrix must define every stage exactly once"
            raise ValueError(msg)
        for src, row in self.probabilities.items():
            if set(row) != set(ALL_STAGES):
                msg = f"row {src} must cover every stage"
                raise ValueError(msg)
            vals = {k: _finite(v) for k, v in row.items()}
            negatives = [k for k, v in vals.items() if v < 0.0]
            if negatives:
                msg = f"row {src} has negative entries: {negatives}"
                raise ValueError(msg)
            total = sum(vals.values())
            if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
                msg = f"row {src} sums to {total!r}, expected 1.0"
                raise ValueError(msg)
        return self


class SleepStageTransitionModel:
    """Semi-Markov stage process with bounded integer-epoch dwells."""

    def __init__(
        self,
        transitions: TransitionMatrixConfig,
        dwells: dict[StageName, DwellDistribution],
        rng: np.random.Generator,
        initial_stage: StageName = "Wake",
        resample_cap: int = 64,
    ) -> None:
        """Freeze policy tables and draw the first stage's remaining dwell.

        Raises ``ValueError`` on unsupported stages or a cap below 1.
        """
        if initial_stage not in ALL_STAGES:
            msg = f"unknown initial stage: {initial_stage!r}"
            raise ValueError(msg)
        if resample_cap < 1:
            msg = "resample_cap must be >= 1"
            raise ValueError(msg)
        missing = [s for s in ALL_STAGES if s not in dwells]
        if missing:
            msg = f"missing dwell distribution for stages: {missing}"
            raise ValueError(msg)
        self._transitions = transitions
        self._dwells = dwells
        self._rng = rng
        self._resample_cap = resample_cap
        #: Count of draws discarded because the capped support was exceeded.
        self.resample_count = 0
        self.current_stage: StageName = initial_stage
        self.ticks_in_current_stage = 0
        self.remaining_epochs = self._draw_dwell(initial_stage)

    def _draw_dwell(self, stage: StageName) -> int:
        dist = self._dwells[stage]
        weights = np.asarray(dist.weights, dtype=float)
        normalized = weights / weights.sum()
        for _ in range(self._resample_cap):
            k = int(self._rng.choice(len(normalized), p=normalized))
            dwell = dist.min_epochs + k
            if dwell <= dist.max_dwell_epochs:
                return dwell
            self.resample_count += 1
        msg = (
            f"dwell sampling exhausted resample_cap={self._resample_cap} "
            f"for stage {stage}; refusing to emit out-of-policy dwell"
        )
        raise RuntimeError(msg)

    def _next_stage(self) -> StageName:
        row = self._transitions.probabilities[self.current_stage]
        stages = sorted(row)  # deterministic comparator: Unicode code points
        probs = np.asarray([row[s] for s in stages], dtype=float)
        total = probs.sum()
        if not math.isclose(float(total), 1.0, rel_tol=0.0, abs_tol=1e-9):
            msg = f"transition row for {self.current_stage} does not sum to 1"
            raise RuntimeError(msg)
        idx = int(self._rng.choice(len(stages), p=probs / total))
        nxt = stages[idx]
        if nxt == self.current_stage:
            # Degenerate all-diagonal row: stay without consuming a change.
            return self.current_stage
        return nxt

    def advance(self, tick: int) -> tuple[StageTransitionInfo | None, int]:
        """Advance one epoch.

        Returns ``(transition_info_or_None, ticks_in_stage_after_advance)``
        where ``ticks_in_stage`` counts the completed epochs in the current
        stage *including* this one.
        """
        self.remaining_epochs -= 1
        self.ticks_in_current_stage += 1
        if self.remaining_epochs > 0:
            return None, self.ticks_in_current_stage
        nxt = self._next_stage()
        completed = self.ticks_in_current_stage
        info: StageTransitionInfo | None = None
        if nxt != self.current_stage:
            next_dwell = self._draw_dwell(nxt)
            info = StageTransitionInfo(
                from_stage=self.current_stage,
                to_stage=nxt,
                completed_dwell_epochs=completed,
                next_dwell_epochs=next_dwell,
                tick=tick,
            )
            self.current_stage = nxt
            self.remaining_epochs = next_dwell
            # This tick is the first epoch of the new stage (1-based counting).
            self.ticks_in_current_stage = 1
        else:
            self.remaining_epochs = self._draw_dwell(nxt)
        return info, self.ticks_in_current_stage

    def export_policy(self) -> dict[str, Any]:
        """Return the complete declared policy for exports/tests."""
        return {
            "transitions": {
                src: dict(sorted(row.items()))
                for src, row in self._transitions.probabilities.items()
            },
            "dwells": {
                stage: {
                    "min_epochs": d.min_epochs,
                    "weights": list(d.weights),
                    "max_dwell_epochs": d.max_dwell_epochs,
                }
                for stage, d in sorted(self._dwells.items())
            },
            "resample_cap": self._resample_cap,
            "initial_stage": self.current_stage,
        }


class StageTransitionInfo(BaseModel):
    """Plain data describing one legal transition (engine converts to event)."""

    model_config = ConfigDict(frozen=True)

    from_stage: StageName
    to_stage: StageName
    completed_dwell_epochs: int
    next_dwell_epochs: int
    tick: int
