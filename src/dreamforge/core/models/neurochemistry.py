"""Neuromodulatory proxy model (MASTER_PROMPT.md section 5.2).

Produces four finite dimensionless values in [0, 1] — acetylcholine,
serotonin, noradrenaline, cortisol — as *qualitative normalized synthetic
indices*. They are never concentrations, sampled measurements, patient values,
or pharmacokinetic predictions.

Transform order (documented contract, tested): for each channel,

    raw = baseline + stage_modulation[stage] + circadian_gain * C(t)
    value = clip(raw, 0.0, 1.0)      # exactly one clip, at the end

The optional circadian term is hypothesis-tagged and disabled per channel by
default. All randomness would flow through an injected Generator; this model
is fully deterministic given inputs and consumes **no** random draws itself
(the engine still owns an isolated ``chemistry`` stream so that future
configurable stochastic modulation cannot perturb other components).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dreamforge.core.models.events import ALL_STAGES, StageName


class _ValidatedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NeurochemistryConfig(_ValidatedModel):
    """Validated baseline/modulation configuration.

    ``baselines``/``stage_modulation`` are keyed by channel name
    (``acetylcholine``, ``serotonin``, ``noradrenaline``, ``cortisol``);
    modulation rows cover all five stages. The final clip to [0, 1] makes any
    configuration legal as long as inputs are finite.
    """

    CHANNELS: tuple[str, ...] = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")

    baselines: dict[str, float]
    stage_modulation: dict[str, dict[StageName, float]]
    circadian_gain: dict[str, float] = Field(
        default_factory=lambda: {
            c: 0.0
            for c in (
                "acetylcholine",
                "serotonin",
                "noradrenaline",
                "cortisol",
            )
        },
    )

    @field_validator("baselines", "circadian_gain")
    @classmethod
    def _channels_present(cls, value: dict[str, float]) -> dict[str, float]:
        expected = {"acetylcholine", "serotonin", "noradrenaline", "cortisol"}
        if set(value) != expected:
            msg = f"expected channels exactly {sorted(expected)}, got {sorted(value)}"
            raise ValueError(msg)
        return value

    @field_validator("stage_modulation")
    @classmethod
    def _rows_valid(
        cls,
        value: dict[str, dict[StageName, float]],
    ) -> dict[str, dict[StageName, float]]:
        expected_channels = {"acetylcholine", "serotonin", "noradrenaline", "cortisol"}
        expected_stages = set(ALL_STAGES)
        if set(value) != expected_channels:
            msg = f"stage_modulation must key channels exactly {sorted(expected_channels)}"
            raise ValueError(msg)
        for channel, row in value.items():
            if set(row) != expected_stages:
                msg = f"modulation row {channel} must cover stages {sorted(expected_stages)}"
                raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _finite(self) -> NeurochemistryConfig:
        for group in (self.baselines, self.circadian_gain):
            for channel, val in group.items():
                if not math.isfinite(val):
                    msg = f"non-finite config for {channel}"
                    raise ValueError(msg)
        for row in self.stage_modulation.values():
            for stage, val in row.items():
                if not math.isfinite(val):
                    msg = f"non-finite modulation for {stage}"
                    raise ValueError(msg)
        return self


class NeurochemicalProxyModel:
    """Deterministic four-channel normalized proxy."""

    def __init__(self, config: NeurochemistryConfig) -> None:
        """Freeze the validated configuration."""
        self._cfg = config

    def step(self, tick: int, stage: StageName, c_value: float) -> dict[str, float]:
        """Compute the four proxies for one epoch.

        ``c_value`` is the circadian proxy from :class:`SleepRegulationModel`.
        Returns channel -> value with every value finite in [0, 1].
        """
        if not math.isfinite(c_value):
            msg = "c_value must be finite"
            raise ValueError(msg)
        out: dict[str, float] = {}
        for channel in ("acetylcholine", "serotonin", "noradrenaline", "cortisol"):
            raw = (
                self._cfg.baselines[channel]
                + self._cfg.stage_modulation[channel][stage]
                + self._cfg.circadian_gain[channel] * c_value
            )
            # Transform-then-clip: single terminal clip (documented order).
            out[channel] = min(max(raw, 0.0), 1.0)
        return out
