"""Fixed-seed ensemble runs with aggregate metrics (M4, §5.5).

An ensemble derives N member seeds by declared integer shifts from ONE base
configuration. Members never share streams; every member is a full engine run
with its own trace hash. Aggregates (mean/min/max) are computed over member
metrics only — they are summaries of simulation outputs, labeled
mechanistic_proxy, and carry the model-conditional disclaimer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dreamforge.core.config import SimulationConfig
from dreamforge.core.provenance.clock import Clock
from dreamforge.core.serialization.dqcj import dumps_canonical
from dreamforge.simulation.counterfactual import (
    DISCLAIMER,
    CounterfactualError,
    RunMetrics,
)

MECHANISTIC_LABEL = "Simulated model proxy — not a biological measurement"


class EnsembleMember(BaseModel):
    """One executed ensemble member."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member_id: str
    seed: int = Field(ge=0, le=2**64 - 1)
    metrics: RunMetrics


class NumericAggregate(BaseModel):
    """Mean/min/max over one numeric metric across members."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mean: float
    min: float
    max: float


class EnsembleRun(BaseModel):
    """Complete labeled result of one ensemble execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = "mechanistic_proxy"
    visible_label: str = MECHANISTIC_LABEL
    disclaimer: str = DISCLAIMER
    base_run_id: str
    base_seed: int
    seed_shifts: tuple[int, ...]
    members: tuple[EnsembleMember, ...]
    aggregate_mean_s_value: NumericAggregate
    aggregate_stage_transition_count: NumericAggregate
    aggregate_replay_count: NumericAggregate
    distinct_trace_hashes: int

    @field_validator("members")
    @classmethod
    def _members_present(cls, value: tuple[EnsembleMember, ...]) -> tuple[EnsembleMember, ...]:
        if not value:
            msg = "ensemble must contain at least one member"
            raise ValueError(msg)
        return value

    def to_canonical_bytes(self) -> bytes:
        """DQCJ-1 canonical bytes of the ensemble result."""
        return dumps_canonical(self.model_dump())


def _aggregate(values: list[float]) -> NumericAggregate:
    return NumericAggregate(
        mean=sum(values) / len(values),
        min=min(values),
        max=max(values),
    )


def run_ensemble(
    base_config: SimulationConfig,
    seed_shifts: tuple[int, ...] | list[int],
    clock: Clock,
) -> EnsembleRun:
    """Execute all members deterministically and aggregate their metrics.

    Duplicate effective seeds (base + shift) are refused BEFORE any run:
    ensembles summarize variation across distinct seeds.
    """
    shifts = tuple(int(shift) for shift in seed_shifts)
    if not shifts:
        raise CounterfactualError("ensemble requires at least one seed shift")
    seeds = [int(base_config.run_seed) + shift for shift in shifts]
    if len(set(seeds)) != len(seeds):
        raise CounterfactualError(
            f"duplicate effective seeds in ensemble: {sorted(seeds)}",
        )

    from dreamforge.simulation.counterfactual import _metrics  # single source of metric logic

    members: list[EnsembleMember] = []
    for index, seed in enumerate(seeds):
        payload = base_config.model_dump()
        payload["run_seed"] = seed
        member_config = SimulationConfig.model_validate(payload)
        metrics = _metrics(member_config, clock)
        members.append(
            EnsembleMember(
                member_id=f"member-{index:03d}",
                seed=seed,
                metrics=metrics,
            ),
        )

    distinct_hashes = len({member.metrics.core_trace_hash for member in members})
    return EnsembleRun(
        base_run_id=base_config.run_id,
        base_seed=int(base_config.run_seed),
        seed_shifts=shifts,
        members=tuple(members),
        aggregate_mean_s_value=_aggregate(
            [float(member.metrics.mean_s_value) for member in members],
        ),
        aggregate_stage_transition_count=_aggregate(
            [float(member.metrics.stage_transition_count) for member in members],
        ),
        aggregate_replay_count=_aggregate(
            [float(member.metrics.replay_count) for member in members],
        ),
        distinct_trace_hashes=distinct_hashes,
    )
