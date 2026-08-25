"""Micro-probe: is completed_dwell_epochs equal to the drawn dwell?"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.models.sleep_cycle import (  # noqa: E402
    DwellDistribution,
    SleepStageTransitionModel,
)
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")


def part_a_model_level() -> None:
    """Drive SleepStageTransitionModel alone with degenerate dwell=3."""
    from dreamforge.core.models.sleep_cycle import TransitionMatrixConfig

    dwells = {
        s: DwellDistribution(min_epochs=3, weights=(1.0,), max_dwell_epochs=10) for s in STAGES
    }
    matrix_cfg = TransitionMatrixConfig(
        probabilities={
            s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
            for i, s in enumerate(STAGES)
        },
    )
    model = SleepStageTransitionModel(
        matrix_cfg,
        dwells,
        rng=np.random.default_rng(7),
        initial_stage="Wake",
    )
    print("model-level: degenerate dwell=3 -> expect every completed==3")
    for tick in range(12):
        info, ticks_in = model.advance(tick)
        marker = ""
        if info is not None:
            marker = (
                f" TRANSITION {info.from_stage}->{info.to_stage}"
                f" completed={info.completed_dwell_epochs}"
            )
        print(f"  tick {tick}: stage={model.current_stage} ticks_in={ticks_in}{marker}")


def part_b_engine_level() -> None:
    """Engine-level: degenerate dwell=3, collect completed histogram."""
    payload = {
        "schema_version": "1.0",
        "run_id": "micro-engine",
        "run_seed": 7,
        "total_ticks": 600,
        "transitions": {
            "probabilities": {
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
                for i, s in enumerate(STAGES)
            },
        },
        "dwells": {s: {"min_epochs": 3, "weights": [1.0], "max_dwell_epochs": 10} for s in STAGES},
        "chemistry": {
            "baselines": {
                c: 0.5 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "stage_modulation": {
                c: {s: 0.0 for s in STAGES}
                for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "circadian_gain": {
                c: 0.0 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 10, "edge_count": 20},
            "selector": {"top_k": 3},
            "replay_every_n_epochs": 100,
        },
    }
    result = run_simulation(load_config(payload), FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    hist: Counter[int] = Counter()
    for e in result.events:
        if e.event_type == "stage_transition":
            hist[int(e.payload.completed_dwell_epochs)] += 1
    print("engine-level: degenerate dwell=3 -> histogram:", dict(sorted(hist.items())))
    print("(every value should be 3; anything else = off-by-one)")


if __name__ == "__main__":
    part_a_model_level()
    print()
    part_b_engine_level()
