"""Simulation engine: orchestrates one deterministic offline run.

Layer A only. Consumes a validated :class:`SimulationConfig`, drives the
models over ``total_ticks`` epochs, emits frozen events through an append-only
store, and produces the manifest with hashes. No I/O, no clock reads, no
environment access inside the loop — provenance time arrives via :class:`Clock`
and never participates in any hash (section 4.2).
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np

import dreamforge
from dreamforge.core.config import SimulationConfig, dumps_config_canonical
from dreamforge.core.models.events import (
    COMPONENT_REGISTRY,
    RNG_CONTRACT_VERSION,
    BaseEvent,
    MemoryReplayPayload,
    NeurochemicalStatePayload,
    ReplayContribution,
    SimulationRunManifest,
    SleepStatePayload,
    StageTransitionPayload,
    make_event,
)
from dreamforge.core.models.memory_graph import (
    GraphSerializerV1,
    GraphSpecConfig,
    ReplayEventScheduler,
    ReplaySelectorConfig,
)
from dreamforge.core.models.neurochemistry import NeurochemicalProxyModel
from dreamforge.core.models.sleep_cycle import (
    SleepRegulationModel,
    SleepStageTransitionModel,
    StageTransitionInfo,
)
from dreamforge.core.provenance.clock import Clock


def derive_stream(run_seed: int, component: str) -> np.random.Generator:
    """Derive one component's isolated child stream (section 4.1, ADR 0002)."""
    component_id = COMPONENT_REGISTRY[component]
    seed_seq = np.random.SeedSequence([run_seed, component_id])
    return np.random.Generator(np.random.PCG64(seed_seq))


@dataclass(frozen=True)
class SimulationResult:
    """Outcome of one run: events, manifest, hashes, final state."""

    events: tuple[BaseEvent, ...]
    manifest: SimulationRunManifest
    core_trace_hash: str
    graph_snapshot: dict[str, Any]


class InMemoryEventStore:
    """Append-only in-memory event store (documented single-writer semantics).

    Concurrent writers are unsupported; appends validate strict sequence.
    """

    def __init__(self) -> None:
        self._events: list[BaseEvent] = []

    def append(self, event: BaseEvent) -> None:
        """Append strictly after the last sequence; refuse gaps/replays."""
        expected = self._events[-1].event_sequence + 1 if self._events else 1
        if event.event_sequence != expected:
            msg = f"sequence violation: got {event.event_sequence}, " f"expected {expected}"
            raise ValueError(msg)
        self._events.append(event)

    def all_events(self) -> tuple[BaseEvent, ...]:
        """Return every appended event in append order."""
        return tuple(self._events)


def _quantized_payload_dict(event: BaseEvent) -> dict[str, Any]:
    """Quantized canonical payload dict (delegates to the single helper)."""
    from dreamforge.core.models.events import quantized_payload_dict

    return quantized_payload_dict(str(event.event_type), event.payload)


def _canonical_core_record(event: BaseEvent) -> bytes:
    """DQCJ-1 record for hashing/export: envelope minus emitted_at."""
    envelope = event.model_dump(exclude={"emitted_at", "payload"})
    envelope["payload"] = _quantized_payload_dict(event)
    from dreamforge.core.serialization.dqcj import dumps_canonical

    return dumps_canonical(envelope)


def run_simulation(
    config: SimulationConfig,
    clock: Clock,
) -> SimulationResult:
    """Execute the full deterministic run described by ``config``.

    Emits per epoch: ``sleep_state``; ``stage_transition`` when the semi-Markov
    boundary fires; ``neurochemical_state`` every epoch; ``memory_replay``
    every ``replay_every_n_epochs``. Emits ``simulation_warning`` audit events
    only if deterministic pruning triggers (not expected at demo sizes).
    """
    epoch_seconds = config.epoch_seconds
    schema_version = "1.0"

    store = InMemoryEventStore()
    sequence = 0
    emitted_at = clock.now().isoformat()

    def emit(event_type: Any, payload: Any) -> BaseEvent:
        nonlocal sequence
        sequence += 1
        event = make_event(
            run_id=config.run_id,
            event_type=event_type,
            event_sequence=sequence,
            tick=tick,
            epoch_seconds=epoch_seconds,
            source_component=_SOURCE_BY_TYPE[event_type],
            schema_version=schema_version,
            correlation_id=f"corr-{config.run_id}",
            emitted_at=emitted_at,
            payload=payload,
        )
        store.append(event)
        return event

    # --- isolated component streams -------------------------------------
    stage_rng = derive_stream(config.run_seed, "stage")
    chemistry_rng = derive_stream(config.run_seed, "chemistry")
    synthetic_memory_rng = derive_stream(config.run_seed, "synthetic_memory")
    replay_rng = derive_stream(config.run_seed, "replay")
    # chemistry currently consumes no draws; touch the stream once so the
    # stream is exercised and its independence stays regression-tested.
    _ = float(chemistry_rng.uniform(0.0, 1.0))

    # --- components -------------------------------------------------------
    regulation = SleepRegulationModel(config.process_s, config.circadian, epoch_seconds)
    transitions_model = SleepStageTransitionModel(
        config.transitions,
        config.dwells,
        rng=stage_rng,
        initial_stage=config.initial_stage,
    )
    chemistry_model = NeurochemicalProxyModel(config.chemistry)

    graph_spec: GraphSpecConfig = config.replay_policy.synthetic_graph
    selector_cfg: ReplaySelectorConfig = config.replay_policy.selector
    graph = _build_graph_with_audit(graph_spec, synthetic_memory_rng, emit)
    scheduler = ReplayEventScheduler(
        graph,
        selector_cfg,
        rng=replay_rng,
    )

    # --- main loop ---------------------------------------------------------
    for tick in range(config.total_ticks):
        stage_before = transitions_model.current_stage
        transition_info, ticks_in_stage = transitions_model.advance(tick)
        current_stage = transitions_model.current_stage

        s_value, c_value = regulation.step(tick, current_stage)

        # sleep_state describes the pre-transition classification of this
        # epoch's regulatory step target... we record the stage actually in
        # effect after advancing (the stage whose dwell includes this epoch).
        del stage_before
        emit(
            "sleep_state",
            SleepStatePayload(
                stage=current_stage,
                s_value=s_value,
                c_value=c_value,
                ticks_in_stage=ticks_in_stage,
            ),
        )

        if transition_info is not None:
            emit("stage_transition", StageTransitionPayload(**_info_dict(transition_info)))

        chem = chemistry_model.step(tick, current_stage, c_value)
        emit(
            "neurochemical_state",
            NeurochemicalStatePayload(**chem),
        )

        if tick % config.replay_policy.replay_every_n_epochs == 0:
            selection = scheduler.select(tick, current_stage)
            contributions = tuple(ReplayContribution(**row) for row in selection["contributions"])
            emit(
                "memory_replay",
                MemoryReplayPayload(
                    selected_node_ids=tuple(selection["selected_node_ids"]),
                    contributions=contributions,
                    candidate_count=int(selection["candidate_count"]),
                    rejected_ids_sha256_prefixes=tuple(
                        selection["rejected_ids_sha256_prefixes"],
                    ),
                    policy_reason=str(selection["policy_reason"]),
                ),
            )

    events = store.all_events()

    # --- hashes ------------------------------------------------------------
    trace_hash = hashlib.sha256(
        b"".join(_canonical_core_record(event) for event in events),
    ).hexdigest()

    config_sha256 = hashlib.sha256(
        dumps_config_canonical(config),
    ).hexdigest()

    stage_policy = transitions_model.export_policy()
    replay_policy = scheduler.export_policy()
    stage_policy["resample_count"] = transitions_model.resample_count
    stage_policy["dwells_max_cap"] = max(int(d.max_dwell_epochs) for d in config.dwells.values())

    manifest = SimulationRunManifest(
        manifest_version="1.0",
        run_id=config.run_id,
        run_seed=config.run_seed,
        rng_contract_version=RNG_CONTRACT_VERSION,
        component_registry=dict(sorted(COMPONENT_REGISTRY.items())),
        engine_version=dreamforge.__version__,
        dependency_versions={
            "numpy": np.__version__,
            "pydantic": _dep_version("pydantic"),
            "networkx": _dep_version("networkx"),
        },
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        schema_versions={"event": schema_version, "config": config.schema_version},
        canonicalization={"name": "DQCJ-1", "test_vectors": "1"},
        config_sha256=config_sha256,
        input_data_sha256=None,
        declared_policies={
            "stage_process": stage_policy,
            "replay_selection": replay_policy,
            "graph": {
                "serializer": GraphSerializerV1.VERSION,
                **graph_snapshot_summary(graph),
            },
        },
        event_count=len(events),
        core_trace_hash=trace_hash,
        created_at=clock.now().isoformat(),
    )
    assert manifest.manifest_hash()  # self-check; value used by exporters

    return SimulationResult(
        events=events,
        manifest=manifest,
        core_trace_hash=trace_hash,
        graph_snapshot=GraphSerializerV1.serialize(graph),
    )


_SOURCE_BY_TYPE = {
    "sleep_state": "sleep_regulation",
    "stage_transition": "stage_transitions",
    "neurochemical_state": "neurochemistry",
    "memory_replay": "replay_scheduler",
    "simulation_warning": "engine",
}


def _info_dict(info: StageTransitionInfo) -> dict[str, Any]:
    return {
        "from_stage": info.from_stage,
        "to_stage": info.to_stage,
        "completed_dwell_epochs": info.completed_dwell_epochs,
        "next_dwell_epochs": info.next_dwell_epochs,
    }


def _build_graph_with_audit(
    spec: GraphSpecConfig,
    rng: np.random.Generator,
    emit: Any,
) -> Any:
    from dreamforge.core.models.memory_graph import build_synthetic_graph

    graph = build_synthetic_graph(spec, rng)
    del emit  # budget-pruning warnings arrive with graph budgets (later milestone)
    return graph


def graph_snapshot_summary(graph: Any) -> dict[str, Any]:
    """Small privacy-safe summary embedded in the manifest."""
    return {
        "node_count": int(graph.number_of_nodes()),
        "edge_count": int(graph.number_of_edges()),
    }


def _dep_version(name: str) -> str:
    from importlib.metadata import version

    return version(name)
