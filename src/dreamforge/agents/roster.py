"""The seven Layer-B agents (§6.1): read-only observers of the event stream.

Each agent inspects already-emitted events through one public ``observe``
method and returns a plain observation. Agents never import the engine, hold
no simulation state, and propose changes only via typed commands
(:mod:`dreamforge.agents.commands`) - which the engine's gate may refuse.
All outputs carry the mechanistic-proxy framing where user-visible.

OrchestratorAgent coordinates the other six over a shared read-only view;
it is NOT the simulation engine (the deterministic core remains authoritative
and untouched).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from dreamforge.core.models.events import BaseEvent


class _EventView(Protocol):
    """Read-only projection agents may consume."""

    def events(self) -> tuple[BaseEvent, ...]: ...


@dataclass(frozen=True)
class Observation:
    """One agent's structured reading of the stream (never prose-only)."""

    agent: str
    summary: dict[str, Any]
    label: str = "Simulated model proxy — not a biological measurement"


def _by_type(events: tuple[BaseEvent, ...]) -> dict[str, list[BaseEvent]]:
    grouped: dict[str, list[BaseEvent]] = {}
    for event in events:
        grouped.setdefault(str(event.event_type), []).append(event)
    return grouped


class OrchestratorAgent:
    """Coordinates the six specialist agents over one shared event view."""

    name = "orchestrator"

    def __init__(self) -> None:
        self.sleep = SleepCycleAgent()
        self.neurochemistry = NeurochemistryAgent()
        self.memory = MemoryConsolidationAgent()
        self.dream = DreamConstructorAgent()
        self.metacognition = MetacognitiveAgent()
        self.phenomenology = PhenomenologyReporter()

    def observe(self, view: _EventView) -> dict[str, Observation]:
        """Run every specialist over the same view; return keyed results."""
        results = {
            "sleep_cycle": self.sleep.observe(view),
            "neurochemistry": self.neurochemistry.observe(view),
            "memory_consolidation": self.memory.observe(view),
            "dream_constructor": self.dream.observe(view),
            "metacognitive": self.metacognition.observe(view),
            "phenomenology_reporter": self.phenomenology.report(view),
        }
        return results

    def propose(self, command: Any) -> Any:
        """Agents propose only through the typed gate (engine decides)."""
        return command  # passthrough for explicitness; gate does the work


class SleepCycleAgent:
    """Stage-sequence statistics: fractions, transition counts, dwell means."""

    name = "sleep_cycle"

    def observe(self, view: _EventView) -> Observation:
        grouped = _by_type(view.events())
        states = grouped.get("sleep_state", [])
        transitions = grouped.get("stage_transition", [])
        fractions = (
            {
                s: n / len(states)
                for s, n in sorted(Counter(str(e.payload.stage) for e in states).items())
            }
            if states
            else {}
        )
        dwells = [int(e.payload.completed_dwell_epochs) for e in transitions]
        mean_dwell = sum(dwells) / len(dwells) if dwells else 0.0
        return Observation(
            self.name,
            {
                "epochs_observed": len(states),
                "stage_fractions": {k: round(v, 4) for k, v in fractions.items()},
                "transitions": len(transitions),
                "mean_completed_dwell_epochs": round(mean_dwell, 3),
            },
        )


class NeurochemistryAgent:
    """Per-channel min/mean/max across emitted neurochemical states."""

    name = "neurochemistry"

    CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")

    def observe(self, view: _EventView) -> Observation:
        grouped = _by_type(view.events())
        states = grouped.get("neurochemical_state", [])
        stats: dict[str, dict[str, float]] = {}
        for channel in self.CHANNELS:
            values = [float(getattr(e.payload, channel)) for e in states]
            stats[channel] = (
                {
                    "min": round(min(values), 4),
                    "mean": round(sum(values) / len(values), 4),
                    "max": round(max(values), 4),
                }
                if values
                else {"min": 0.0, "mean": 0.0, "max": 0.0}
            )
        return Observation(self.name, {"samples": len(states), "channels": stats})


class MemoryConsolidationAgent:
    """Replay selection structure: token frequency, contribution shares."""

    name = "memory_consolidation"

    def observe(self, view: _EventView) -> Observation:
        grouped = _by_type(view.events())
        replays = grouped.get("memory_replay", [])
        token_freq: Counter[str] = Counter()
        candidate_counts: list[int] = []
        for replay in replays:
            token_freq.update(str(t) for t in replay.payload.selected_node_ids)
            candidate_counts.append(int(replay.payload.candidate_count))
        top = token_freq.most_common(5)
        return Observation(
            self.name,
            {
                "replay_epochs": len(replays),
                "distinct_tokens": len(token_freq),
                "top_tokens": [{"token": t, "count": c} for t, c in top],
                "mean_candidates": (
                    round(sum(candidate_counts) / len(candidate_counts), 2)
                    if candidate_counts
                    else 0.0
                ),
            },
        )


class DreamConstructorAgent:
    """Segments the night into stage episodes and tags each deterministically."""

    name = "dream_constructor"

    def observe(self, view: _EventView) -> Observation:
        grouped = _by_type(view.events())
        states = grouped.get("sleep_state", [])
        episodes: list[dict[str, Any]] = []
        current_stage: str | None = None
        run_start = 0
        for index, event in enumerate(states):
            stage = str(event.payload.stage)
            if stage != current_stage:
                if current_stage is not None:
                    episodes.append(
                        {
                            "stage": current_stage,
                            "start_epoch": run_start,
                            "end_epoch": index - 1,
                            "length": index - run_start,
                        }
                    )
                current_stage = stage
                run_start = index
        if current_stage is not None:
            episodes.append(
                {
                    "stage": current_stage,
                    "start_epoch": run_start,
                    "end_epoch": len(states) - 1,
                    "length": len(states) - run_start,
                }
            )
        longest = max(episodes, key=lambda e: e["length"]) if episodes else None
        return Observation(
            self.name,
            {
                "episodes": len(episodes),
                "longest_episode": longest,
            },
        )


class MetacognitiveAgent:
    """Flags structural anomalies IN THE SIMULATION ONLY (never clinical)."""

    name = "metacognitive"

    def observe(self, view: _EventView) -> Observation:
        grouped = _by_type(view.events())
        warnings = grouped.get("simulation_warning", [])
        states = grouped.get("sleep_state", [])
        rem_share = (
            sum(1 for e in states if str(e.payload.stage) == "REM") / len(states) if states else 0.0
        )
        notes: list[str] = []
        if warnings:
            notes.append(f"{len(warnings)} simulation warning(s) recorded")
        if states and rem_share > 0.5:
            notes.append(f"REM share {rem_share:.0%} exceeds half the night (unusual prior)")
        return Observation(
            self.name,
            {
                "warnings": [str(w.payload.code) for w in warnings],
                "rem_share": round(rem_share, 4),
                "notes": notes,
            },
        )


class PhenomenologyReporter:
    """Composes the labeled narrative block from OTHER agents' observations.

    The report is assembled from structured fields only; its visible label is
    fixed and no first-person experience is ever claimed.
    """

    name = "phenomenology_reporter"

    def report(self, view: _EventView) -> Observation:
        constructor = DreamConstructorAgent().observe(view)
        memory = MemoryConsolidationAgent().observe(view)
        episodes = int(constructor.summary["episodes"])
        replays = int(memory.summary["replay_epochs"])
        text = (
            f"The simulated night contained {episodes} stage episode(s) and "
            f"{replays} replay epoch(s). This is generated interpretation of a "
            "simulation — not a report of an actual dream, not a measurement, "
            "and not an inference about any mind."
        )
        return Observation(
            self.name,
            {
                "narrative_text": text,
                "output_class": "generative_interpretation",
            },
            label="Generated interpretation — not a dream measurement or inference",
        )
