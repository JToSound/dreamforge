"""Immutable event and manifest models (ADR 0002).

Envelope fields follow MASTER_PROMPT.md section 4.2 exactly::

    run_id, event_id, event_type, event_sequence, tick,
    simulated_time_minutes, source_component, schema_version,
    correlation_id, emitted_at

``emitted_at`` is provenance supplied through ``Clock`` and participates in no
hash. Payloads hold only deterministic fields; collections are stored as
tuples/mappings of immutables because ``frozen=True`` does not deep-freeze.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dreamforge.core.serialization.dqcj import dumps_canonical

#: Fixed documented namespace for event UUIDv5 derivation (ADR 0002).
NAMESPACE_DREAMFORGE_EVENT = uuid.UUID("7d444842-7fb0-4ae1-9d43-e8ddae0a4d67")

#: Version of the RNG contract recorded in manifests (section 4.1).
RNG_CONTRACT_VERSION = "dreamforge-rng-v1"

#: Fixed integer component registry (section 4.1). Never reorder or reuse IDs.
COMPONENT_REGISTRY: dict[str, int] = {
    "stage": 1,
    "chemistry": 2,
    "replay": 3,
    "synthetic_memory": 4,
    "ensemble": 5,
}

StageName = Literal["Wake", "N1", "N2", "N3", "REM"]
ALL_STAGES: tuple[StageName, ...] = ("Wake", "N1", "N2", "N3", "REM")

#: DQCJ-1 quantization registry for event payloads (dotted paths, ``*`` =
#: array element). Declared quanta are part of the engine contract (ADR 0002);
#: the engine asserts every declared path matches at least one float.
EVENT_QUANTIZATIONS: dict[str, str] = {
    # sleep_state
    "payload.s_value": "0.000001",
    "payload.c_value": "0.000001",
    # stage_transition
    # (integer fields only — nothing to declare)
    # neurochemical_state
    "payload.acetylcholine": "0.000001",
    "payload.serotonin": "0.000001",
    "payload.noradrenaline": "0.000001",
    "payload.cortisol": "0.000001",
    # memory_replay
    "payload.contributions.*.activation_share": "0.000001",
    "payload.contributions.*.recency_share": "0.000001",
    "payload.contributions.*.salience_share": "0.000001",
    "payload.contributions.*.stage_share": "0.000001",
    "payload.contributions.*.novelty_share": "0.000001",
}


def quantizations_for(event_type: str) -> dict[str, str]:
    """Return the quantization registry slice for one event type.

    Paths are prefixed with ``payload.`` already; the envelope's only float,
    ``simulated_time_minutes``, is quantized separately at export time.
    """
    prefixes = {
        "sleep_state": ("payload.s_value", "payload.c_value"),
        "stage_transition": (),
        "neurochemical_state": (
            "payload.acetylcholine",
            "payload.serotonin",
            "payload.noradrenaline",
            "payload.cortisol",
        ),
        "memory_replay": tuple(p for p in EVENT_QUANTIZATIONS if ".contributions." in p),
        "simulation_warning": (),
    }
    if event_type not in prefixes:
        msg = f"unknown event_type: {event_type!r}"
        raise ValueError(msg)
    return {p: EVENT_QUANTIZATIONS[p] for p in prefixes[event_type]}


def payload_hash_bytes(payload: dict[str, object]) -> str:
    """Return SHA-256 hex over DQCJ-1 bytes of a deterministic payload."""
    return hashlib.sha256(dumps_canonical(payload)).hexdigest()


def quantized_payload_dict(event_type: str, payload: BaseModel) -> dict[str, object]:
    """Return the payload dict with declared quantizations applied.

    This is the single canonical form: ``make_event`` derives IDs from it,
    the engine hashes trace records over it, and import verification
    recomputes both from it.
    """
    from dreamforge.core.serialization.dqcj import transform_canonical

    quant = {key[len("payload.") :]: value for key, value in quantizations_for(event_type).items()}
    return dict(transform_canonical(payload.model_dump(), quantizations=quant))


def compute_event_id(
    run_id: str,
    event_type: str,
    event_sequence: int,
    deterministic_payload_hash: str,
) -> str:
    """Derive ``event_id`` as UUIDv5 over an unambiguous UTF-8 encoding.

    Components are joined with ASCII unit separator 0x1F, which is excluded
    from every component's alphabet (UUID hex, ``[a-z_]`` event types, decimal
    integers, lowercase hex digests), making the encoding injective.
    """
    name = "\x1f".join(
        (run_id, event_type, str(event_sequence), deterministic_payload_hash),
    )
    return str(uuid.uuid5(NAMESPACE_DREAMFORGE_EVENT, name))


class _FrozenModel(BaseModel):
    """Base for all immutable payload/envelope models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplayContribution(_FrozenModel):
    """Per-factor normalized contribution shares for one selected node."""

    node_id: str
    activation_share: float
    recency_share: float
    salience_share: float
    stage_share: float
    novelty_share: float


class SleepStatePayload(_FrozenModel):
    """Deterministic payload describing one epoch's regulatory state."""

    stage: StageName
    s_value: float
    c_value: float
    ticks_in_stage: int


class StageTransitionPayload(_FrozenModel):
    """Deterministic payload for one legal stage transition."""

    from_stage: StageName
    to_stage: StageName
    completed_dwell_epochs: int
    next_dwell_epochs: int


class NeurochemicalStatePayload(_FrozenModel):
    """Four dimensionless proxies, each in [0, 1]. Never concentrations."""

    acetylcholine: float
    serotonin: float
    noradrenaline: float
    cortisol: float


class MemoryReplayPayload(_FrozenModel):
    """Selection result of one replay epoch (graph selection, not firing)."""

    selected_node_ids: tuple[str, ...]
    contributions: tuple[ReplayContribution, ...]
    candidate_count: int
    rejected_ids_sha256_prefixes: tuple[str, ...]
    policy_reason: str


class SimulationWarningPayload(_FrozenModel):
    """Audit warning, e.g. deterministic graph-budget pruning."""

    code: str
    message: str


PayloadT = (
    SleepStatePayload
    | StageTransitionPayload
    | NeurochemicalStatePayload
    | MemoryReplayPayload
    | SimulationWarningPayload
)

EventType = Literal[
    "sleep_state",
    "stage_transition",
    "neurochemical_state",
    "memory_replay",
    "simulation_warning",
]


class BaseEvent(_FrozenModel):
    """Immutable event envelope; ``event_id`` is derived, never free-form."""

    run_id: str = Field(min_length=8, max_length=64)
    event_id: str = Field(min_length=36, max_length=36)
    event_type: EventType
    event_sequence: int = Field(ge=1)
    tick: int = Field(ge=0)
    simulated_time_minutes: float
    source_component: str
    schema_version: str
    correlation_id: str
    emitted_at: str  # timezone-aware ISO-8601; excluded from every hash
    payload: PayloadT

    @field_validator("emitted_at")
    @classmethod
    def _aware_iso(cls, value: str) -> str:
        from datetime import datetime

        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            msg = "emitted_at must be timezone-aware ISO-8601"
            raise ValueError(msg)
        return value

    def deterministic_record(self) -> dict[str, object]:
        """Return the record used for hashing: envelope minus provenance.

        Excludes ``emitted_at`` (nondeterministic provenance). The payload is
        the quantized canonical form, matching ``make_event`` ID derivation.
        """
        envelope = self.model_dump(exclude={"emitted_at", "payload"})
        envelope["payload"] = quantized_payload_dict(
            str(self.event_type),
            self.payload,
        )
        return envelope

    def deterministic_payload(self) -> dict[str, object]:
        """Return the payload-only dict used inside ``event_id`` derivation."""
        return self.payload.model_dump()


def make_event(
    *,
    run_id: str,
    event_type: EventType,
    event_sequence: int,
    tick: int,
    epoch_seconds: float,
    source_component: str,
    schema_version: str,
    correlation_id: str,
    emitted_at: str,
    payload: PayloadT,
) -> BaseEvent:
    """Construct an event, deriving ``event_id`` per ADR 0002.

    The digest is computed over the **quantized canonical** payload form so
    that import-time recomputation (which re-applies quantizations) matches
    byte-for-byte.
    """
    canonical_payload = quantized_payload_dict(str(event_type), payload)
    digest = hashlib.sha256(dumps_canonical(canonical_payload)).hexdigest()
    event_id = compute_event_id(run_id, str(event_type), event_sequence, digest)
    return BaseEvent(
        run_id=run_id,
        event_id=event_id,
        event_type=event_type,
        event_sequence=event_sequence,
        tick=tick,
        simulated_time_minutes=tick * epoch_seconds / 60.0,
        source_component=source_component,
        schema_version=schema_version,
        correlation_id=correlation_id,
        emitted_at=emitted_at,
        payload=payload,
    )


class SimulationRunManifest(_FrozenModel):
    """Run-level provenance. ``created_at`` is excluded from ``manifest_hash``."""

    manifest_version: str
    run_id: str
    run_seed: int = Field(ge=0, le=2**64 - 1)
    rng_contract_version: str
    component_registry: dict[str, int]
    engine_version: str
    dependency_versions: dict[str, str]
    python_version: str
    schema_versions: dict[str, str]
    canonicalization: dict[str, str]
    config_sha256: str
    input_data_sha256: str | None
    declared_policies: dict[str, dict[str, object]] = Field(default_factory=dict)
    event_count: int
    core_trace_hash: str
    created_at: str

    def hash_input(self) -> dict[str, object]:
        """Canonical dict hashed into ``manifest_hash`` (excludes created_at)."""
        return self.model_dump(exclude={"created_at"})

    def manifest_hash(self) -> str:
        """SHA-256 over separate canonical manifest bytes (section 4.3)."""
        return hashlib.sha256(dumps_canonical(self.hash_input())).hexdigest()
