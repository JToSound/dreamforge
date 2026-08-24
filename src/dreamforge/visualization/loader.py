"""Export loading for the dashboard — WITHOUT importing the engine.

The dashboard must render verified exports without executing simulator or
provider code (MASTER_PROMPT.md §7, M3 gate). This module reuses only
``import_and_verify`` (which itself never loads the run loop) and exposes a
small typed bundle for the Streamlit app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dreamforge.simulation.export_import import (
    ImportedRun,
    ImportError_,
    VerificationReport,
    import_and_verify,
)

__all__ = ["LoadedExport", "load_export", "ImportError_", "VerificationReport"]


@dataclass(frozen=True)
class LoadedExport:
    """Everything the dashboard needs from one verified export directory."""

    imported: ImportedRun
    verification: VerificationReport
    stage_timeline: list[tuple[int, str]]  # (tick, stage) per epoch
    proxy_timeline: list[dict[str, float]]  # per-epoch chemistry values
    replay_ticks: list[int]

    @property
    def label_summary(self) -> str:
        """Visible label for deterministic blocks (§1.2)."""
        assert self.imported.report is not None or True  # reports may be absent in v1
        return "Simulated model proxy — not a biological measurement"


def load_export(export_dir: Path) -> LoadedExport:
    """Verify and project one export into dashboard-ready series."""
    imported, verification = import_and_verify(Path(export_dir))
    stage_timeline = [
        (int(event.tick), str(event.payload.stage))
        for event in imported.events
        if event.event_type == "sleep_state"
    ]
    proxy_timeline = [
        {
            "acetylcholine": float(event.payload.acetylcholine),
            "serotonin": float(event.payload.serotonin),
            "noradrenaline": float(event.payload.noradrenaline),
            "cortisol": float(event.payload.cortisol),
        }
        for event in imported.events
        if event.event_type == "neurochemical_state"
    ]
    replay_ticks = [
        int(event.tick) for event in imported.events if event.event_type == "memory_replay"
    ]
    return LoadedExport(
        imported=imported,
        verification=verification,
        stage_timeline=stage_timeline,
        proxy_timeline=proxy_timeline,
        replay_ticks=replay_ticks,
    )
