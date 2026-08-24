"""Fixed-seed counterfactual runs with exact change accounting (§5.5).

A counterfactual holds non-target configuration, input bytes, engine version,
and the component RNG policy fixed; varies ONLY declared parameters; and
reports control vs changed values plus the enumerated parameter list. Output
differences are stated to be model-conditional — never causal biological
effects. Everything is a mechanistic_proxy result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dreamforge.core.config import SimulationConfig
from dreamforge.core.provenance.clock import Clock
from dreamforge.core.serialization.dqcj import dumps_canonical
from dreamforge.simulation.engine import run_simulation

DISCLAIMER = (
    "Output differences are properties of this simulation model under its "
    "declared assumptions; they are not causal biological effects."
)

#: Top-level config fields a counterfactual may vary (allowlist).
VARYABLE_FIELDS = {
    "run_seed",
    "epoch_seconds",
    "total_ticks",
    "initial_stage",
}


class CounterfactualError(ValueError):
    """Raised when a counterfactual spec violates the fixed-pair contract."""


class ChangedParameter(BaseModel):
    """One declared difference between control and changed configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    control_value: Any
    changed_value: Any


class RunMetrics(BaseModel):
    """Small deterministic summary of one run for comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    core_trace_hash: str
    event_count: int
    stage_transition_count: int
    replay_count: int
    mean_s_value: float = Field(ge=0.0, le=1.0)
    final_stage: str


class CounterfactualComparison(BaseModel):
    """Complete labeled result of one control/changed pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = "mechanistic_proxy"
    visible_label: str = "Simulated model proxy — not a biological measurement"
    disclaimer: str = DISCLAIMER
    run_id: str
    control_seed: int
    changed_seed: int | None
    changed_parameters: tuple[ChangedParameter, ...]
    control_metrics: RunMetrics
    changed_metrics: RunMetrics
    identical_trace_hash: bool

    def to_canonical_bytes(self) -> bytes:
        """DQCJ-1 canonical bytes of the comparison."""
        return dumps_canonical(self.model_dump())


def _metrics(config: SimulationConfig, clock: Clock) -> RunMetrics:
    result = run_simulation(config, clock)
    s_values = [
        float(event.payload.s_value) for event in result.events if event.event_type == "sleep_state"
    ]
    transitions = sum(1 for e in result.events if e.event_type == "stage_transition")
    replays = sum(1 for e in result.events if e.event_type == "memory_replay")
    stage_events = [e for e in result.events if e.event_type == "sleep_state"]
    return RunMetrics(
        core_trace_hash=result.core_trace_hash,
        event_count=len(result.events),
        stage_transition_count=transitions,
        replay_count=replays,
        mean_s_value=sum(s_values) / max(len(s_values), 1),
        final_stage=str(stage_events[-1].payload.stage),
    )


@dataclass(frozen=True)
class CounterfactualSpec:
    """Declared variation: seed shift and/or allowlisted field overrides."""

    base_config: SimulationConfig
    override_fields: dict[str, Any]
    seed_shift: int = 0

    def __post_init__(self) -> None:
        illegal = set(self.override_fields) - VARYABLE_FIELDS - {"run_seed"}
        if illegal:
            msg = f"fields outside the variation allowlist: {sorted(illegal)}"
            raise CounterfactualError(msg)


def run_counterfactual(spec: CounterfactualSpec, clock: Clock) -> CounterfactualComparison:
    """Execute control and changed pairs and account for every difference."""
    base_payload = spec.base_config.model_dump()

    control_payload = dict(base_payload)
    if spec.seed_shift:
        control_payload["run_seed"] = int(spec.base_config.run_seed)
    control_cfg = (
        spec.base_config
        if not spec.seed_shift
        else SimulationConfig.model_validate(control_payload)
    )

    changed_payload = dict(base_payload)
    for field_name, value in spec.override_fields.items():
        changed_payload[field_name] = value
    if spec.seed_shift:
        changed_payload["run_seed"] = int(spec.base_config.run_seed) + int(spec.seed_shift)
    changed_cfg = SimulationConfig.model_validate(changed_payload)

    # Enumerate differences EXACTLY from the two validated payloads.
    changed_parameters = tuple(
        ChangedParameter(
            field=field_name,
            control_value=control_payload.get(field_name),
            changed_value=changed_payload.get(field_name),
        )
        for field_name in sorted(set(control_payload) | set(changed_payload))
        if control_payload.get(field_name) != changed_payload.get(field_name)
    )
    if not changed_parameters:
        raise CounterfactualError("counterfactual must vary at least one declared parameter")

    control_metrics = _metrics(control_cfg, clock)
    changed_metrics = _metrics(changed_cfg, clock)

    return CounterfactualComparison(
        run_id=f"cf-{spec.base_config.run_id}",
        control_seed=int(control_cfg.run_seed),
        changed_seed=int(changed_cfg.run_seed),
        changed_parameters=changed_parameters,
        control_metrics=control_metrics,
        changed_metrics=changed_metrics,
        identical_trace_hash=(control_metrics.core_trace_hash == changed_metrics.core_trace_hash),
    )


def metrics_delta(comparison: CounterfactualComparison) -> dict[str, float]:
    """Numeric deltas (changed minus control) for the compared scalar metrics.

    Trace hash is excluded (not numeric). Values are model outputs only.
    """
    control = comparison.control_metrics
    changed = comparison.changed_metrics
    return {
        "mean_s_value": changed.mean_s_value - control.mean_s_value,
        "stage_transition_count": float(
            changed.stage_transition_count - control.stage_transition_count,
        ),
        "replay_count": float(changed.replay_count - control.replay_count),
        "event_count": float(changed.event_count - control.event_count),
    }
