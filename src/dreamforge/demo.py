"""Offline deterministic demo: 8-hour (960 epoch) run, export, verify, report.

Runs entirely offline with no credentials. Prints only facts observed during
execution (counts, hashes, check results). Rendering/verification never
re-runs the simulator beyond this entry point itself.

DreamForge is a research and visualization simulator. It does not measure
brains, diagnose conditions, predict dreams, infer psychological meaning, or
provide medical advice.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dreamforge.core.config import load_config
from dreamforge.core.models.dream_context import build_dream_context
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.core.providers.narrative import MockNarrativeProvider
from dreamforge.simulation.engine import run_simulation
from dreamforge.simulation.export_import import import_and_verify, write_export
from dreamforge.simulation.report import attach_narrative, build_report

DISCLAIMER = (
    "DreamForge is a research and visualization simulator. It does not "
    "measure brains, diagnose conditions, predict dreams, infer psychological "
    "meaning, or provide medical advice."
)


def main(argv: list[str] | None = None) -> int:
    """Run the bundled 8-hour demo; returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = Path(argv[0]) if argv else Path("examples/configs/demo_8h.json")
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("exports/demo_8h")

    config = load_config(config_path)
    clock = FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC))
    result = run_simulation(config, clock)

    # Deterministic context + score from emitted events (post-run projection).
    node_types = {
        str(node["id"]): str(node.get("node_type", "unknown"))
        for node in result.graph_snapshot["nodes"]
    }
    context = build_dream_context(
        run_id=config.run_id,
        schema_version="1.0",
        total_ticks=config.total_ticks,
        events=list(result.events),
        node_type_lookup=node_types,
    )

    counts = Counter(str(event.event_type) for event in result.events)
    run_report = build_report(
        context=context,
        event_counts=dict(counts),
        core_trace_hash=result.core_trace_hash,
    )
    provider = MockNarrativeProvider()
    run_report, response = attach_narrative(context, run_report, provider, style="plain")

    checksums = write_export(
        out_dir=out_dir,
        events=result.events,
        manifest=result.manifest,
        config=config,
        graph_snapshot=result.graph_snapshot,
        report=run_report,
    )

    imported, verification = import_and_verify(out_dir)

    print(DISCLAIMER)
    print(f"config: {config_path}")
    print(f"ticks: {config.total_ticks} x {config.epoch_seconds}s epochs")
    print("events:")
    for event_type in sorted(counts):
        print(f"  {event_type}: {counts[event_type]}")
    print(f"core_trace_hash: {result.core_trace_hash}")
    print(f"manifest_hash:   {result.manifest.manifest_hash()}")
    print("export artifacts:")
    for name in sorted(checksums):
        print(f"  {name}: sha256={checksums[name]}")
    print(f"import verification: ok={verification.ok} checks={len(verification.checks)}")
    failed = [check for check in verification.checks if check["status"] != "pass"]
    if failed:
        for check in failed:
            print(f"  FAILED: {check['check']}: {check['detail']}")
        return 1

    features = context.features
    print("context [mechanistic_proxy]:")
    print(f"  segments: {len(context.segments)}")
    print(
        "  features: "
        f"scene_discontinuity={features.scene_discontinuity:.3f} "
        f"entity_incongruity={features.entity_incongruity:.3f} "
        f"causal_implausibility={features.causal_implausibility:.3f} "
        f"temporal_distortion={features.temporal_distortion:.3f} "
        f"identity_instability={features.identity_instability:.3f} "
        f"memory_blending_entropy={features.memory_blending_entropy:.3f}",
    )
    print(
        f"  bizarreness score: {context.score_bizarreness_0_100:.2f}/100 "
        f"(scorer {context.scorer_version}) — "
        f"{context.visible_label}",
    )
    print(f"narrative [{response.output_class}]: {response.text}")

    imported_count_matches = len(imported.events) == len(result.events)
    print(f"imported event count matches: {imported_count_matches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
