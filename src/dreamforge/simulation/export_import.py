"""Canonical export/import with hash verification (section 4.4).

Exports contain ``events.ndjson``, ``manifest.json``, a canonical
configuration snapshot, checksums, migration records, and a verification
README. Only artifacts actually generated are included.

Import **re-validates before reconstruction**: strict JSON parsing, schema
validation, strict sequences, nondecreasing simulated time, legal stage
transitions against the manifest's declared matrix, event-ID recomputation,
checksums, and trace/manifest hashes. This module deliberately does NOT import
the simulation engine's run loop: rendering an imported export must never
execute simulator or provider code (only pure canonicalization/config helpers).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dreamforge.core.config import (
    ConfigError,
    SimulationConfig,
    dumps_config_canonical,
    load_config,
)
from dreamforge.core.models.events import (
    ALL_STAGES,
    BaseEvent,
    SimulationRunManifest,
)
from dreamforge.core.serialization.dqcj import (
    dumps_canonical,
    loads_strict,
)
from dreamforge.simulation.report import (
    GENERATIVE_LABEL,
    MECHANISTIC_LABEL,
    OUTPUT_CLASS_GENERATIVE,
    OUTPUT_CLASS_MECHANISTIC,
    RunReport,
)

EXPORT_LAYOUT_VERSION = "2"

_CORE_EXPORT_FILES = (
    "events.ndjson",
    "manifest.json",
    "config.canonical.json",
    "verification.json",
    "graph_snapshot.json",
    "README.txt",
)

_MAX_IMPORT_BYTES = 64 * 1024 * 1024
_MAX_EVENTS_PER_EXPORT = 200_000


class ImportError_(ValueError):
    """Raised when an export fails verification; ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ImportedRun:
    """Reconstructed, verified run state."""

    events: tuple[BaseEvent, ...]
    manifest: SimulationRunManifest
    config: SimulationConfig
    graph_snapshot: dict[str, Any]
    report: RunReport | None = None


@dataclass
class VerificationReport:
    """Machine-readable result of import verification."""

    ok: bool = False
    checks: list[dict[str, str]] = field(default_factory=list)

    def record(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": name, "status": status, "detail": detail})

    def require(self, name: str, condition: bool, detail: str = "") -> None:
        """Record pass/fail; raise on failure (fail-closed verification)."""
        if condition:
            self.record(name, "pass")
            return
        self.record(name, "fail", detail)
        raise ImportError_(name, f"verification failed: {name}: {detail}")


def _quantized_payload_dict(event: BaseEvent) -> dict[str, Any]:
    """Quantized canonical payload dict (delegates to the single helper)."""
    from dreamforge.core.models.events import quantized_payload_dict

    return quantized_payload_dict(str(event.event_type), event.payload)


def canonical_core_record(event: BaseEvent) -> bytes:
    """Envelope minus nondeterministic provenance, in DQCJ-1 bytes."""
    envelope = event.model_dump(exclude={"emitted_at", "payload"})
    envelope["payload"] = _quantized_payload_dict(event)
    return dumps_canonical(envelope)


def core_trace_hash_of(events: tuple[BaseEvent, ...] | list[BaseEvent]) -> str:
    """SHA-256 over concatenated canonical core records."""
    digest = hashlib.sha256()
    for event in events:
        digest.update(canonical_core_record(event))
    return digest.hexdigest()


def write_export(
    *,
    out_dir: Path,
    events: tuple[BaseEvent, ...] | list[BaseEvent],
    manifest: SimulationRunManifest,
    config: SimulationConfig,
    graph_snapshot: dict[str, Any],
    report: RunReport | None = None,
) -> dict[str, str]:
    """Write the versioned export layout; returns artifact checksums.

    Layout v2 additionally embeds ``report.json`` when a :class:`RunReport` is
    supplied; the artifact joins the checksum map and import verification.
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # Canonical boundary (DQCJ-1 rule 6): serialized records carry the
    # quantized payload form, matching trace-hash and event-ID derivation.
    # Only unhashed provenance (emitted_at) travels outside the hash scope.
    lines = []
    for event in events:
        envelope = event.model_dump(mode="json", exclude={"payload"})
        envelope["payload"] = _quantized_payload_dict(event)
        lines.append(dumps_canonical(envelope).decode("utf-8"))
    ndjson_text = "".join(line + "\n" for line in lines)
    (out_dir / "events.ndjson").write_text(ndjson_text, encoding="utf-8", newline="\n")

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "graph_snapshot.json").write_text(
        json.dumps(graph_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    config_bytes = dumps_config_canonical(config)
    (out_dir / "config.canonical.json").write_bytes(config_bytes)

    if report is not None:
        report_bytes = dumps_canonical(report.model_dump())
        (out_dir / "report.json").write_bytes(report_bytes)

    checksums = {
        "events.ndjson": hashlib.sha256(
            (out_dir / "events.ndjson").read_bytes(),
        ).hexdigest(),
        "manifest.json": hashlib.sha256(
            (out_dir / "manifest.json").read_bytes(),
        ).hexdigest(),
        "graph_snapshot.json": hashlib.sha256(
            (out_dir / "graph_snapshot.json").read_bytes(),
        ).hexdigest(),
        "config.canonical.json": hashlib.sha256(config_bytes).hexdigest(),
    }
    if report is not None:
        checksums["report.json"] = hashlib.sha256(
            (out_dir / "report.json").read_bytes(),
        ).hexdigest()

    verification = {
        "layout_version": EXPORT_LAYOUT_VERSION,
        "core_trace_hash": manifest.core_trace_hash,
        "manifest_hash": manifest.manifest_hash(),
        "checksums": checksums,
        "migration_records": [],
    }
    (out_dir / "verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "README.txt").write_text(
        "DreamForge offline export.\n"
        "Verification order: parse strictly -> schema-validate -> sequence/time/"
        "transition checks -> event-ID recomputation -> checksums -> "
        "trace/manifest hashes. Rendering this export must not execute "
        "simulator or provider code.\n"
        "DreamForge is a research and visualization simulator. It does not "
        "measure brains, diagnose conditions, predict dreams, infer "
        "psychological meaning, or provide medical advice.\n",
        encoding="utf-8",
        newline="\n",
    )
    return checksums


def import_and_verify(export_dir: Path) -> tuple[ImportedRun, VerificationReport]:
    """Verify an export completely, then reconstruct the run state.

    Fails closed on any violation with :class:`ImportError_` (code names the
    failed check).
    """
    report = VerificationReport()
    export_dir = Path(export_dir)

    report.require(
        "layout_files_present",
        all(
            (export_dir / name).is_file()
            for name in (
                "events.ndjson",
                "manifest.json",
                "config.canonical.json",
                "verification.json",
                "graph_snapshot.json",
                "README.txt",
            )
        ),
        str(export_dir),
    )

    raw_events_bytes = (export_dir / "events.ndjson").read_bytes()
    report.require(
        "size_within_limits",
        len(raw_events_bytes) <= _MAX_IMPORT_BYTES,
        f"{len(raw_events_bytes)} bytes",
    )
    verification = loads_strict(
        (export_dir / "verification.json").read_text(encoding="utf-8"),
    )
    layout_version = str(verification.get("layout_version", "1"))
    has_report = (export_dir / "report.json").is_file()
    if layout_version == "2" and not has_report:
        raise ImportError_(
            "layout_files_present",
            "layout v2 requires report.json",
        )

    # --- manifest first: later checks need its declared policies ------------
    manifest = SimulationRunManifest.model_validate(
        loads_strict((export_dir / "manifest.json").read_text(encoding="utf-8")),
    )
    report.require(
        "manifest_hash_matches",
        manifest.manifest_hash() == verification["manifest_hash"],
        manifest.manifest_hash(),
    )
    declared_transitions: dict[str, dict[str, float]] = {
        src: {dst: float(p) for dst, p in row.items()}
        for src, row in manifest.declared_policies["stage_process"]["transitions"].items()
    }

    # --- strict parse + schema validation -----------------------------------
    if raw_events_bytes:
        line_texts = raw_events_bytes.decode("utf-8").splitlines()
    else:
        line_texts = []
    if not line_texts:
        raise ImportError_("non_empty_trace", "no events found")
    if len(line_texts) > _MAX_EVENTS_PER_EXPORT:
        raise ImportError_("event_count_within_limits", "too many events")
    events: list[BaseEvent] = [BaseEvent.model_validate(loads_strict(line)) for line in line_texts]
    report.record("strict_parse_and_schema", "pass")
    report.record("event_count_within_limits", "pass", str(len(events)))

    # --- sequence, monotonic time --------------------------------------------
    prev_seq = 0
    prev_time = -1.0
    for event in events:
        if event.event_sequence != prev_seq + 1:
            msg = f"sequence break at {event.event_sequence}"
            raise ImportError_("event_sequence_strict", msg)
        prev_seq = event.event_sequence
        if event.simulated_time_minutes < prev_time:
            msg = f"time decreased at sequence {event.event_sequence}"
            raise ImportError_("simulated_time_nondecreasing", msg)
        prev_time = event.simulated_time_minutes
    report.require("event_sequence_strict", True)
    report.require("simulated_time_nondecreasing", True)

    # --- legal transitions against the DECLARED exported matrix ---------------
    # Per-tick emission order is [sleep_state(new stage), stage_transition],
    # so a transition's declared origin must match the stage observed at the
    # PREVIOUS tick, not this tick's sleep_state.
    current_stage: str | None = None
    stage_before_current_tick: str | None = None
    for event in events:
        if event.event_type == "sleep_state":
            stage_before_current_tick = current_stage
            stage_now = str(event.payload.stage)
            if stage_now not in ALL_STAGES:
                msg = f"unknown stage {stage_now!r}"
                raise ImportError_("transitions_permitted_by_matrix", msg)
            current_stage = stage_now
        elif event.event_type == "stage_transition":
            transition = event.payload
            row = declared_transitions.get(str(transition.from_stage), {})
            probability = row.get(str(transition.to_stage), 0.0)
            if probability <= 0.0:
                msg = (
                    f"undeclared transition {transition.from_stage} -> "
                    f"{transition.to_stage} at tick {event.tick}"
                )
                raise ImportError_("transitions_permitted_by_matrix", msg)
            if stage_before_current_tick is not None and stage_before_current_tick != str(
                transition.from_stage
            ):
                msg = (
                    f"transition origin mismatch at tick {event.tick}: "
                    f"observed {stage_before_current_tick}, "
                    f"declared {transition.from_stage}"
                )
                raise ImportError_("transitions_permitted_by_matrix", msg)
            current_stage = str(transition.to_stage)
    report.require("transitions_permitted_by_matrix", True)

    # --- bounded dwells under the hard cap -------------------------------------
    max_dwell = int(manifest.declared_policies["stage_process"]["dwells_max_cap"])
    for event in events:
        if event.event_type == "stage_transition":
            dwell = int(event.payload.next_dwell_epochs)
            if dwell < 1 or dwell > max_dwell:
                msg = f"dwell {dwell} outside declared cap {max_dwell}"
                raise ImportError_("dwells_bounded", msg)
    report.require("dwells_bounded", True)

    # --- event ID recomputation --------------------------------------------------
    from dreamforge.core.models.events import compute_event_id, payload_hash_bytes

    for event in events:
        digest = payload_hash_bytes(_quantized_payload_dict(event))
        expected = compute_event_id(
            event.run_id,
            str(event.event_type),
            event.event_sequence,
            digest,
        )
        if expected != event.event_id:
            msg = f"event_id mismatch at sequence {event.event_sequence}"
            raise ImportError_("event_ids_recomputable", msg)
    report.require("event_ids_recomputable", True)

    # --- proxy bounds (finite, [0,1]) ---------------------------------------------
    for event in events:
        if event.event_type == "neurochemical_state":
            values = [
                float(event.payload.acetylcholine),
                float(event.payload.serotonin),
                float(event.payload.noradrenaline),
                float(event.payload.cortisol),
            ]
            if any(not (0.0 <= v <= 1.0) for v in values):
                msg = f"proxy out of bounds at sequence {event.event_sequence}"
                raise ImportError_("proxies_bounded", msg)
    report.require("proxies_bounded", True)

    # --- checksums --------------------------------------------------------------------
    for name, expected_hash in sorted(verification["checksums"].items()):
        actual = hashlib.sha256((export_dir / name).read_bytes()).hexdigest()
        report.require(f"checksum:{name}", actual == expected_hash, actual)

    # --- config snapshot ---------------------------------------------------------------
    config_bytes = (export_dir / "config.canonical.json").read_bytes()
    try:
        config = load_config(json.loads(config_bytes.decode("utf-8")))
    except ConfigError as exc:
        raise ImportError_("config_snapshot_valid", str(exc)) from exc
    report.require(
        "config_snapshot_canonical_stable",
        dumps_config_canonical(config) == config_bytes,
    )
    report.require(
        "config_hash_matches_manifest",
        hashlib.sha256(config_bytes).hexdigest() == manifest.config_sha256,
    )

    # --- trace hash ------------------------------------------------------------------------
    recomputed_trace = core_trace_hash_of(tuple(events))
    report.require(
        "core_trace_hash_matches",
        recomputed_trace == verification["core_trace_hash"] == manifest.core_trace_hash,
        recomputed_trace,
    )
    report.require(
        "event_count_matches_manifest",
        len(events) == manifest.event_count,
        f"{len(events)} vs {manifest.event_count}",
    )

    # --- graph snapshot round-trip -----------------------------------------------------------
    graph_payload = loads_strict(
        (export_dir / "graph_snapshot.json").read_text(encoding="utf-8"),
    )
    from dreamforge.core.models.memory_graph import GraphSerializerV1

    try:
        graph = GraphSerializerV1.deserialize(graph_payload)
    except ValueError as exc:
        raise ImportError_("graph_round_trip", str(exc)) from exc
    reserialized = GraphSerializerV1.serialize(graph)
    report.require(
        "graph_round_trip_lossless",
        dumps_canonical(reserialized) == dumps_canonical(graph_payload),
    )

    # --- labeled report contract (layout v2) -------------------------------------------------
    run_report: RunReport | None = None
    if has_report:
        report_bytes_raw = (export_dir / "report.json").read_bytes()
        try:
            run_report = RunReport.model_validate(loads_strict(report_bytes_raw.decode("utf-8")))
        except ValueError as exc:
            raise ImportError_("report_schema_valid", str(exc)) from exc
        if run_report.run_id != manifest.run_id:
            msg = f"report run_id {run_report.run_id!r} != manifest {manifest.run_id!r}"
            raise ImportError_("report_run_id_matches", msg)
        summary_count = int(run_report.summary.event_count)
        if summary_count != len(events):
            msg = f"report event_count {summary_count} != {len(events)}"
            raise ImportError_("report_event_count_matches", msg)
        for block_name, output_class, label in (
            ("summary", OUTPUT_CLASS_MECHANISTIC, MECHANISTIC_LABEL),
            ("features_block", OUTPUT_CLASS_MECHANISTIC, MECHANISTIC_LABEL),
        ):
            block = getattr(run_report, block_name)
            if block.output_class != output_class or block.visible_label != label:
                msg = f"block {block_name} violates the §1.2 label contract"
                raise ImportError_("report_labels_exact", msg)
        narrative = run_report.narrative
        if narrative is not None and (
            narrative.output_class != OUTPUT_CLASS_GENERATIVE
            or narrative.visible_label != GENERATIVE_LABEL
        ):
            msg = "narrative block violates the §1.2 label contract"
            raise ImportError_("report_labels_exact", msg)
        score = float(run_report.features_block.score_bizarreness_0_100)
        if not 0.0 <= score <= 100.0:
            raise ImportError_("report_score_bounded", str(score))
        recomputed_report_bytes = dumps_canonical(run_report.model_dump())
        if recomputed_report_bytes != report_bytes_raw:
            raise ImportError_("report_round_trip_lossless", "bytes differ")
        report.record("report_contract", "pass")

    report.ok = True
    return (
        ImportedRun(
            events=tuple(events),
            manifest=manifest,
            config=config,
            graph_snapshot=reserialized,
            report=run_report,
        ),
        report,
    )
