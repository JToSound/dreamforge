"""Dashboard loader + Streamlit AppTest smoke and label checks (M3 gate)."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreamforge.core.config import load_config
from dreamforge.core.provenance.clock import FixedClock
from dreamforge.simulation.engine import run_simulation
from dreamforge.simulation.export_import import write_export
from dreamforge.visualization.loader import load_export

pytest.importorskip("streamlit", reason="dashboard extras not installed")


def build_export(tmp_path: Path) -> Path:
    """Produce a small verified export (with labeled report)."""
    from dreamforge.core.models.dream_context import build_dream_context
    from dreamforge.simulation.report import attach_narrative, build_report

    stages = ("Wake", "N1", "N2", "N3", "REM")
    payload = {
        "schema_version": "1.0",
        "run_id": "dash-demo-run-01",
        "run_seed": 77,
        "total_ticks": 30,
        "transitions": {
            "probabilities": {
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(stages)}
                for i, s in enumerate(stages)
            },
        },
        "dwells": {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in stages},
        "chemistry": {
            "baselines": {
                c: 0.5 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "stage_modulation": {
                c: {s: 0.0 for s in stages}
                for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "circadian_gain": {
                c: 0.0 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 5, "edge_count": 8},
            "selector": {"top_k": 2},
            "replay_every_n_epochs": 3,
        },
    }
    config = load_config(payload)
    result = run_simulation(config, FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    context = build_dream_context(
        run_id=config.run_id,
        schema_version="1.0",
        total_ticks=30,
        events=list(result.events),
    )
    counts = {
        et: sum(1 for e in result.events if e.event_type == et)
        for et in {str(e.event_type) for e in result.events}
    }
    report = build_report(
        context=context,
        event_counts=counts,
        core_trace_hash=result.core_trace_hash,
    )
    report, _ = attach_narrative(
        context,
        report,
        __import__(
            "dreamforge.core.providers.narrative",
            fromlist=["MockNarrativeProvider"],
        ).MockNarrativeProvider(),
        style="plain",
    )
    out_dir = tmp_path / "exp_dash"
    write_export(
        out_dir=out_dir,
        events=result.events,
        manifest=result.manifest,
        config=config,
        graph_snapshot=result.graph_snapshot,
        report=report,
    )
    return out_dir


class TestLoader:
    def test_load_export_projects_series(self, tmp_path) -> None:
        loaded = load_export(build_export(tmp_path))
        assert loaded.verification.ok
        assert len(loaded.stage_timeline) == 30
        assert len(loaded.proxy_timeline) == 30
        for row in loaded.proxy_timeline:
            for value in row.values():
                assert 0.0 <= value <= 1.0

    def test_engine_not_loaded_by_loader(self, tmp_path) -> None:
        build_export(tmp_path)
        probe = (
            "import sys;\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2] / 'src')!r});\n"
            "from dreamforge.visualization.loader import load_export;\n"
            f"load_export({str(tmp_path / 'exp_dash')!r});\n"
            "banned = {'dreamforge.simulation.engine', 'dreamforge.demo'};\n"
            "hits = banned & set(sys.modules);\n"
            "print('LOADED ' + ','.join(sorted(hits)) if hits else 'ENGINE_NOT_LOADED')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert "ENGINE_NOT_LOADED" in completed.stdout, completed.stderr


class TestAppSmoke:
    def test_apptest_renders_labels(self, tmp_path) -> None:
        from streamlit.testing.v1 import AppTest

        export_dir = build_export(tmp_path)
        at = AppTest.from_file(
            Path(__file__).resolve().parents[2] / "src/dreamforge/visualization/dashboard.py",
        )
        # Absolute path: AppTest resolves relative paths against ITS own cwd.
        at.query_params["export"] = str(export_dir.resolve())
        at.run(timeout=120)
        assert not at.exception, str(at.exception)

        all_text = "\n".join(
            block.value or "" for block in [*at.warning, *at.info, *at.caption, *at.error]
        )
        assert (
            "DreamForge is a research and visualization simulator" in all_text
        ), "mandatory disclaimer must render"
        assert "Simulated model proxy — not a biological measurement" in all_text
        assert "Generated interpretation — not a dream measurement or inference" in all_text
        # no measurement-implying wording anywhere
        forbidden = [
            "your brain did",
            "measured neurotransmitter",
            "scientifically proves",
            "clinically validated",
            "this is what you dreamed",
        ]
        for phrase in forbidden:
            assert phrase.lower() not in all_text.lower(), phrase

    def test_apptest_fails_closed_on_tampered_export(self, tmp_path) -> None:
        from streamlit.testing.v1 import AppTest

        export_dir = build_export(tmp_path)
        events_path = export_dir / "events.ndjson"
        original = events_path.read_bytes()
        events_path.write_bytes(original.replace(b'"Wake"', b'"Wake"', 1) + b"\n")
        at = AppTest.from_file(
            Path(__file__).resolve().parents[2] / "src/dreamforge/visualization/dashboard.py",
        )
        at.query_params["export"] = str(export_dir.resolve())
        at.run(timeout=120)
        errors = [error.value for error in at.error]
        assert any("Verification FAILED" in value for value in errors), errors
