"""Export layout v2: labeled report as a verified artifact (M2 separation)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreamforge.core.config import load_config
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.core.providers.narrative import MockNarrativeProvider
from dreamforge.simulation.engine import run_simulation
from dreamforge.simulation.export_import import (
    EXPORT_LAYOUT_VERSION,
    ImportError_,
    import_and_verify,
    write_export,
)
from dreamforge.simulation.report import attach_narrative, build_report


def build_small_run(tmp_path: Path, *, with_narrative: bool = True):
    """Run 40 ticks, build context/report, return everything needed."""
    from dreamforge.core.models.dream_context import build_dream_context

    payload = {
        "schema_version": "1.0",
        "run_id": "layout-v2-run-01",
        "run_seed": 4242,
        "total_ticks": 40,
        "transitions": _transitions(),
        "dwells": _dwells(),
        "chemistry": _chemistry(),
        "replay_policy": {
            "synthetic_graph": {"node_count": 6, "edge_count": 10},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 4,
        },
    }
    config = load_config(payload)
    result = run_simulation(config, FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    node_types = {
        str(n["id"]): str(n.get("node_type", "unknown")) for n in result.graph_snapshot["nodes"]
    }
    context = build_dream_context(
        run_id=config.run_id,
        schema_version="1.0",
        total_ticks=40,
        events=list(result.events),
        node_type_lookup=node_types,
    )
    from collections import Counter

    counts_dict = dict(Counter(str(event.event_type) for event in result.events))
    report = build_report(
        context=context,
        event_counts=counts_dict,
        core_trace_hash=result.core_trace_hash,
    )
    if with_narrative:
        report, _ = attach_narrative(context, report, MockNarrativeProvider(), style="plain")
    return config, result, context, report


class TestLayoutV2:
    def test_round_trip_report_byte_identical(self, tmp_path) -> None:
        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "exp"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
            report=report,
        )
        assert (out_dir / "report.json").is_file()
        imported, verification = import_and_verify(out_dir)
        assert verification.ok
        # layout version declared inside the verification artifact is "2"
        declared = __import__("json").loads(
            (out_dir / "verification.json").read_text(encoding="utf-8"),
        )["layout_version"]
        assert str(declared) == str(EXPORT_LAYOUT_VERSION)
        # byte-identical round trip of the canonical report bytes
        original = (out_dir / "report.json").read_bytes()
        from dreamforge.core.serialization.dqcj import dumps_canonical

        recanonical = dumps_canonical(imported.report.model_dump())  # type: ignore[union-attr]
        assert recanonical == original

    def test_tampered_labels_rejected(self, tmp_path) -> None:
        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "exp"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
            report=report,
        )
        path = out_dir / "report.json"
        tampered = path.read_text(encoding="utf-8").replace(
            "Simulated model proxy — not a biological measurement",
            "clinically validated measurement",
        )
        path.write_text(tampered, encoding="utf-8")
        with pytest.raises(ImportError_) as excinfo:
            import_and_verify(out_dir)
        assert excinfo.value.code in ("checksum:report.json", "report_labels_exact")

    def test_tampered_narrative_output_class_rejected(self, tmp_path) -> None:
        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "exp"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
            report=report,
        )
        path = out_dir / "report.json"
        raw = path.read_text(encoding="utf-8").replace(
            '"output_class":"generative_interpretation"',
            '"output_class":"mechanistic_proxy"',
        )
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(ImportError_) as excinfo:
            import_and_verify(out_dir)
        assert excinfo.value.code in ("checksum:report.json", "report_labels_exact")

    def test_v2_without_report_file_refused(self, tmp_path) -> None:
        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "exp"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
            report=report,
        )
        (out_dir / "report.json").unlink()
        with pytest.raises(ImportError_, match="requires report.json"):
            import_and_verify(out_dir)

    def test_v1_layout_still_verifies(self, tmp_path) -> None:
        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "exp_v1"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
        )  # no report -> v2 writer without report.json
        # Downgrade the declared layout version to simulate a legacy export.
        verification_path = out_dir / "verification.json"
        legacy = verification_path.read_text(encoding="utf-8").replace(
            '"layout_version": "2"',
            '"layout_version": "1"',
        )
        verification_path.write_text(legacy, encoding="utf-8")
        # The checksum recorded for verification.json itself is not verified by
        # design (it is the trust root), so the downgrade is accepted.
        imported, verification = import_and_verify(out_dir)
        assert verification.ok
        assert imported.report is None

    def test_render_without_execution_covers_v2(self, tmp_path) -> None:
        import subprocess
        import sys

        config, result, _context, report = build_small_run(tmp_path)
        out_dir = tmp_path / "x"
        write_export(
            out_dir=out_dir,
            events=result.events,
            manifest=result.manifest,
            config=config,
            graph_snapshot=result.graph_snapshot,
            report=report,
        )
        repo_root = Path(__file__).resolve().parents[2]
        probe = (
            "import sys;\n"
            "from dreamforge.simulation.export_import import import_and_verify;\n"
            f"imported, vr = import_and_verify({str(out_dir)!r});\n"
            "assert vr.ok and imported.report is not None;\n"
            "loaded = 'dreamforge.simulation.engine' in sys.modules;\n"
            "print('ENGINE_LOADED' if loaded else 'ENGINE_NOT_LOADED')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                "PYTHONPATH": str(repo_root / "src"),
                "PATH": "",
                "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
            },
        )
        assert "ENGINE_NOT_LOADED" in completed.stdout, completed.stderr


# --- inline config fragments (same shape as integration tests) --------------

_STAGES = ("Wake", "N1", "N2", "N3", "REM")


def _transitions() -> dict:
    return {
        "probabilities": {
            s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(_STAGES)}
            for i, s in enumerate(_STAGES)
        },
    }


def _dwells() -> dict:
    return {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in _STAGES}


def _chemistry() -> dict:
    channels = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
    return {
        "baselines": {c: 0.5 for c in channels},
        "stage_modulation": {c: {s: 0.0 for s in _STAGES} for c in channels},
        "circadian_gain": {c: 0.0 for c in channels},
    }
