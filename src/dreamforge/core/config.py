"""Strict simulation configuration loading (fail closed).

The configuration is the only external input to a run. It is validated into
frozen Pydantic models before any engine object is constructed; any violation
raises :class:`ConfigError` with a machine-readable ``code``. No environment
variables, clocks, or network access participate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dreamforge.core.models.events import ALL_STAGES, StageName
from dreamforge.core.models.memory_graph import GraphSpecConfig, ReplaySelectorConfig
from dreamforge.core.models.neurochemistry import NeurochemistryConfig
from dreamforge.core.models.sleep_cycle import (
    CircadianConfig,
    DwellDistribution,
    ProcessSConfig,
    TransitionMatrixConfig,
)

#: Hard limits guarding against oversized/hostile configs (section 6.3).
MAX_EPOCH_SECONDS = 3600.0
MIN_EPOCH_SECONDS = 1.0
MAX_TOTAL_TICKS = 100_000


class ConfigError(ValueError):
    """Raised when configuration fails validation; ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplayPolicyConfig(BaseModel):
    """Where replay selection gets its graph and its policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    synthetic_graph: GraphSpecConfig = Field(default_factory=GraphSpecConfig)
    selector: ReplaySelectorConfig = Field(default_factory=ReplaySelectorConfig)
    replay_every_n_epochs: int = Field(default=8, ge=1)


class SimulationConfig(BaseModel):
    """Fully validated run configuration (immutable after load)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    run_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    run_seed: int = Field(ge=0, le=2**64 - 1)
    epoch_seconds: float = Field(default=30.0)
    total_ticks: int = Field(ge=1)
    initial_stage: StageName = "Wake"
    process_s: ProcessSConfig = Field(default_factory=ProcessSConfig)
    circadian: CircadianConfig = Field(default_factory=CircadianConfig)
    transitions: TransitionMatrixConfig
    dwells: dict[StageName, DwellDistribution]
    chemistry: NeurochemistryConfig
    replay_policy: ReplayPolicyConfig = Field(default_factory=ReplayPolicyConfig)

    @field_validator("epoch_seconds")
    @classmethod
    def _epoch_bounds(cls, value: float) -> float:
        if not MIN_EPOCH_SECONDS <= value <= MAX_EPOCH_SECONDS:
            msg = f"epoch_seconds must be within " f"[{MIN_EPOCH_SECONDS}, {MAX_EPOCH_SECONDS}]"
            raise ValueError(msg)
        return value

    @field_validator("total_ticks")
    @classmethod
    def _ticks_cap(cls, value: int) -> int:
        if value > MAX_TOTAL_TICKS:
            msg = f"total_ticks exceeds MAX_TOTAL_TICKS={MAX_TOTAL_TICKS}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _dwell_support(self) -> SimulationConfig:
        missing = [s for s in ALL_STAGES if s not in self.dwells]
        if missing:
            msg = f"dwells missing stages: {missing}"
            raise ValueError(msg)
        for stage, dwell in self.dwells.items():
            longest = dwell.min_epochs + len(dwell.weights) - 1
            if longest > self.total_ticks:
                msg = f"dwell support for {stage} exceeds total_ticks"
                raise ValueError(msg)
        return self

    def simulated_time_minutes(self, tick: int) -> float:
        """Documented conversion: tick × epoch_seconds / 60."""
        return tick * self.epoch_seconds / 60.0


def dumps_config_canonical(config: SimulationConfig) -> bytes:
    """Canonical configuration snapshot bytes (embedded into exports).

    Lives here rather than in the simulation package so that export/import
    verification never needs to load the engine module at all.
    """
    from dreamforge.core.serialization.dqcj import dumps_canonical

    return dumps_canonical(config.model_dump(mode="json"))


def load_config(source: str | Path | dict[str, Any]) -> SimulationConfig:
    """Load and strictly validate a run configuration.

    ``source`` may be an already-parsed dict or a path to UTF-8 JSON. Raises
    :class:`ConfigError` on any violation (schema, ranges, structure).
    """
    if isinstance(source, dict):
        raw = source
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"config file unreadable: {exc.__class__.__name__}"
            raise ConfigError("config_unreadable", msg) from exc
        from dreamforge.core.serialization.dqcj import loads_strict

        try:
            raw = loads_strict(text)
        except ValueError as exc:
            raise ConfigError("config_invalid_json", str(exc)) from exc
        if not isinstance(raw, dict):
            raise ConfigError(
                "config_invalid_json",
                "top-level configuration must be a JSON object",
            )
    try:
        return SimulationConfig.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - re-raised typed below
        raise ConfigError("config_validation_failed", str(exc)) from exc
