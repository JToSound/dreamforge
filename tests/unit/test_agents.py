"""Layer-B agent roster, typed command gate, and orchestration units (§6.1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from datetime import UTC, datetime  # noqa: E402

from dreamforge.agents import orchestration  # noqa: E402
from dreamforge.agents.commands import (  # noqa: E402
    AgentCommand,
    CommandKind,
    CommandRefusalReason,
    TypedCommandGate,
)
from dreamforge.agents.roster import OrchestratorAgent  # noqa: E402
from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")


def make_events(ticks: int = 480, seed: int = 55):
    payload = {
        "schema_version": "1.0",
        "run_id": f"agents-{ticks}-{seed}",
        "run_seed": seed,
        "total_ticks": ticks,
        "transitions": {
            "probabilities": {
                s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
                for i, s in enumerate(STAGES)
            },
        },
        "dwells": {
            s: {"min_epochs": 1, "weights": [0.5, 1.0, 0.8], "max_dwell_epochs": 10} for s in STAGES
        },
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
            "synthetic_graph": {"node_count": 20, "edge_count": 40},
            "selector": {"top_k": 3},
            "replay_every_n_epochs": 10,
        },
    }
    result = run_simulation(load_config(payload), FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
    return result.events


class TestRoster:
    def test_all_seven_agents_produce_observations(self) -> None:
        events = make_events()
        results = OrchestratorAgent().observe(_View(events))
        assert set(results) == {
            "sleep_cycle",
            "neurochemistry",
            "memory_consolidation",
            "dream_constructor",
            "metacognitive",
            "phenomenology_reporter",
        }

    def test_sleep_cycle_fractions_sum_to_one(self) -> None:
        results = OrchestratorAgent().observe(_View(make_events()))
        fractions = results["sleep_cycle"].summary["stage_fractions"]
        assert abs(sum(fractions.values()) - 1.0) < 1e-3  # rounded to 4dp

    def test_neurochemistry_bounds(self) -> None:
        results = OrchestratorAgent().observe(_View(make_events()))
        channels = results["neurochemistry"].summary["channels"]
        for _channel, stats in channels.items():
            assert 0.0 <= stats["min"] <= stats["mean"] <= stats["max"] <= 1.0

    def test_phenomenology_report_labeled(self) -> None:
        results = OrchestratorAgent().observe(_View(make_events()))
        summary = results["phenomenology_reporter"].summary
        assert summary["output_class"] == "generative_interpretation"
        text = summary["narrative_text"]
        assert "not a report of an actual dream" in text

    def test_determinism_same_events_same_observations(self) -> None:
        events = make_events()
        first = OrchestratorAgent().observe(_View(events))
        second = OrchestratorAgent().observe(_View(events))
        assert {k: v.summary for k, v in first.items()} == {k: v.summary for k, v in second.items()}


class TestCommandGate:
    def test_stage_transitions_refused_while_disabled(self) -> None:
        gate = TypedCommandGate()  # disabled by default
        outcome = gate.propose(
            AgentCommand(
                kind=CommandKind.REQUEST_STAGE_TRANSITION,
                agent="sleep_cycle",
                tick=3,
                payload={"from_stage": "Wake", "to_stage": "N1"},
            )
        )
        assert not outcome.accepted
        assert outcome.reason is CommandRefusalReason.POLICY_DISABLED

    def test_allowed_transition_accepted_when_enabled(self) -> None:
        gate = TypedCommandGate(
            stage_transition_policy_enabled=True,
            allowed_transitions={"Wake": ("N1",)},
        )
        outcome = gate.propose(
            AgentCommand(
                kind=CommandKind.REQUEST_STAGE_TRANSITION,
                agent="orchestrator",
                tick=0,
                payload={"from_stage": "Wake", "to_stage": "N1"},
            )
        )
        assert outcome.accepted

    def test_disallowed_transition_refused(self) -> None:
        gate = TypedCommandGate(
            stage_transition_policy_enabled=True,
            allowed_transitions={"Wake": ("N1",)},
        )
        outcome = gate.propose(
            AgentCommand(
                kind=CommandKind.REQUEST_STAGE_TRANSITION,
                agent="orchestrator",
                tick=0,
                payload={"from_stage": "Wake", "to_stage": "REM"},
            )
        )
        assert outcome.reason is CommandRefusalReason.NOT_ALLOWED_TRANSITION

    def test_chemistry_out_of_bounds_refused(self) -> None:
        gate = TypedCommandGate()
        outcome = gate.propose(
            AgentCommand(
                kind=CommandKind.SET_CHEMISTRY_BASELINE,
                agent="neurochemistry",
                tick=1,
                payload={"channel": "serotonin", "value": 1.5},
            )
        )
        assert outcome.reason is CommandRefusalReason.OUT_OF_BOUNDS

    def test_unknown_channel_refused(self) -> None:
        gate = TypedCommandGate()
        outcome = gate.propose(
            AgentCommand(
                kind=CommandKind.SET_CHEMISTRY_BASELINE,
                agent="neurochemistry",
                tick=1,
                payload={"channel": "dopamine", "value": 0.2},
            )
        )
        assert outcome.reason is CommandRefusalReason.UNKNOWN_FIELD

    def test_audit_trail_records_everything(self) -> None:
        gate = TypedCommandGate()
        cmd = AgentCommand(
            kind=CommandKind.SET_CHEMISTRY_BASELINE,
            agent="neurochemistry",
            tick=1,
            payload={"channel": "serotonin", "value": 0.4},
        )
        gate.propose(cmd)
        assert len(gate.audit) == 1
        recorded_cmd, outcome = gate.audit[0]
        assert recorded_cmd == cmd and outcome.accepted


class TestLanggraphBridge:
    def test_pure_python_orchestration_works_without_langgraph_import(self) -> None:
        events = make_events(ticks=240)
        results = orchestration.run_roster(events)
        assert "sleep_cycle" in results

    def test_langgraph_route_matches_pure_python_when_available(self) -> None:
        if orchestration._build_langgraph_flow() is None:
            pytest.skip("langgraph not installed")
        events = make_events(ticks=240)
        via_graph = orchestration.langgraph_orchestrate(events)
        via_plain = {k: v.summary for k, v in orchestration.run_roster(events).items()}
        assert via_graph == via_plain


class _View:
    def __init__(self, events) -> None:
        self._events = tuple(events)

    def events(self):
        return self._events


def test_core_never_imports_agents_package() -> None:
    """Core purity: importing the engine pulls no agent code in."""
    import subprocess

    probe = (
        "import sys\n"
        "sys.path.insert(0, r'{src}')\n"
        "import dreamforge.simulation.engine\n"
        "hits = [m for m in sys.modules if m.startswith('dreamforge.agents')]\n"
        "print('PULLED:' + ','.join(hits) if hits else 'NOT_PULLED')\n"
    ).format(src=str(REPO / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120
    )
    assert "NOT_PULLED" in completed.stdout, completed.stdout + completed.stderr
