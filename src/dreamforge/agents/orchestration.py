"""Optional LangGraph bridge for the Layer-B roster (§6.1).

Pure-Python orchestration (``run_roster``) is the default and needs no extra
dependency. When ``langgraph`` IS installed, ``langgraph_orchestrate``
builds an equivalent StateGraph so the same observations flow through a
LangGraph runtime; both produce identical structured results because the
agents themselves are dependency-free.

Nothing here can mutate engine state: agents read events and propose typed
commands only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dreamforge.agents.commands import AgentCommand, CommandOutcome, TypedCommandGate
from dreamforge.agents.roster import Observation, OrchestratorAgent


class EventListView:
    """Adapts any sequence of events to the agents' read-only view protocol."""

    def __init__(self, events: tuple) -> None:
        self._events = tuple(events)

    def events(self) -> tuple:
        return self._events


def run_roster(events: tuple) -> dict[str, Observation]:
    """Default orchestration: every specialist over one shared view."""
    return OrchestratorAgent().observe(EventListView(events))


def propose_through_gate(
    commands: list[AgentCommand], gate: TypedCommandGate
) -> list[CommandOutcome]:
    """Submit proposals to the gate; returns outcomes in order."""
    return [gate.propose(command) for command in commands]


def _build_langgraph_flow() -> Callable[[tuple], dict[str, Any]] | None:
    """Compile an equivalent StateGraph if langgraph is importable."""
    try:
        from langgraph.graph import END, START, StateGraph
        from typing_extensions import TypedDict
    except ImportError:
        return None

    class RosterState(TypedDict):
        events: tuple
        results: dict

    orchestrator = OrchestratorAgent()

    def observe_all(state: RosterState) -> RosterState:
        results = orchestrator.observe(EventListView(state["events"]))
        return {"events": state["events"], "results": {k: v.summary for k, v in results.items()}}

    graph = StateGraph(RosterState)
    graph.add_node("observe_all", observe_all)
    graph.add_edge(START, "observe_all")
    graph.add_edge("observe_all", END)
    compiled = graph.compile()

    def run(events: tuple) -> dict[str, Any]:
        return compiled.invoke({"events": events, "results": {}})["results"]

    return run


def langgraph_orchestrate(events: tuple) -> dict[str, Any] | None:
    """Route through LangGraph when available; None otherwise."""
    flow = _build_langgraph_flow()
    if flow is None:
        return None
    return flow(events)
