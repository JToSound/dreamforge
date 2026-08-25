# ADR 0006 — Layer-B agents, pharmacology plugin, and streaming adapters

Status: Accepted
Date: 2026-08-25

## Context

Three roadmap tracks remained after v0.2.0: the §6.1 Layer-B agent roster
(Orchestrator/SleepCycle/Neurochemistry/MemoryConsolidation/DreamConstructor/
Metacognitive/PhenomenologyReporter), the §5.5 fictional-pharmacology surface,
and streaming/tool-use adapter features (deferred at ADR 0005).

## Decisions

### Layer B (`dreamforge/agents/`, outside the core)

1. Agents are **read-only observers** of emitted event streams. They hold no
   simulation state, never import the engine, and a subprocess probe enforces
   that the core never imports the agents package.
2. All state influence flows through **typed commands**
   (`AgentCommand` → `TypedCommandGate`). The gate is disabled-by-default for
   stage transitions; chemistry writes are bounded to [0,1] on known channels;
   every proposal — accepted or refused — lands in an audit trail.
3. **LangGraph is an optional runtime, not a dependency**: pure-Python
   orchestration (`run_roster`) is default; `langgraph_orchestrate` builds an
   equivalent StateGraph only when `langgraph` imports, and a test proves both
   paths produce identical results. The core stays dependency-free.
4. The PhenomenologyReporter composes its narrative from other agents'
   structured summaries and always emits `generative_interpretation` labeling.

### Pharmacology (`integrations/pharmacology.py`)

5. Inert until constructed with an explicit identity-free
   **Acknowledgement** whose statement must contain "fictional"; scenarios are
   qualitative per-channel/stage deltas applied to copies of config dicts;
   every application appends to an audit trail. Unknown scenarios and empty
   acknowledgements raise typed errors. A subprocess probe proves demo code
   never imports the module. `collective_metaphor` remains a permanently
   refusing placeholder (`speculative_collective_metaphor.py`).

### Streaming / tool-use (`integrations/streaming.py`)

6. SSE aggregation for both adapter families (OpenAI `stream=true` chunks,
   Anthropic `content_block_delta`), incremental `on_chunk` callbacks,
   tool-call/tool-use surfaces passed through raw for CALLER-owned tool loops.
   DreamForge defines no tools and never instructs models to act. Malformed
   frames raise redacted errors (status + digest). Transport injection keeps
   everything offline-testable.

## Alternatives considered

- LangGraph as a hard dependency — rejected: core purity and the zero-dep
  preference; the bridge gives the runtime when wanted without forcing it.
- Letting agents mutate engine state directly — rejected by §6.1; the typed
  gate preserves the deterministic core as sole authority.
- Implementing tool execution inside adapters — rejected: provider-agnostic
  transport should not grow an executor; callers own semantics.

## Consequences

- Positive: roadmap complete within spec boundaries; every new surface is
  disabled-by-default, audit-logged, offline-tested, and outside the core's
  import graph.
- Negative: three more modules to maintain; langgraph parity must be
  re-checked if agent outputs change (one test guards this).
