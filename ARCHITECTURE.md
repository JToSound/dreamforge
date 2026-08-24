# DreamForge AI — Architecture

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

Version: 0.1.0 (first execution slice, MASTER_PROMPT.md §9)

## What exists now

A deterministic, offline simulation core proving an 8-hour (960 × 30 s epoch)
trace. No API, no dashboard, no providers, no plugins exist yet — by explicit
scope control (MASTER_PROMPT.md §9).

## Context diagram

```text
                ┌───────────────────────────────────────────────┐
                │                 DreamForge core               │
                │                                               │
 examples/ ───▶ │  config.py ──▶ simulation/engine.py           │
 configs        │                    │                          │
 (public_       │        ┌───────────┼───────────────┐          │
 synthetic      │        ▼           ▼               ▼          │
 JSON only)     │  SleepRegulation  SleepStage     Neurochemical │
                │  Model (S/C)      Transition     ProxyModel    │
                │                   Model                        │
                │        └───────────┬───────────────┘          │
                │                    ▼                          │
                │            MemoryGraphModel +                 │
                │            ReplayEventScheduler               │
                │                    │                          │
                │                    ▼                          │
                │         immutable events (pydantic, frozen)   │
                │                    │                          │
                │                    ▼                          │
                │      InMemoryEventStore (append-only)         │
                │                    │                          │
                │                    ▼                          │
                │      DQCJ-1 canonical bytes + trace hash      │
                └────────────────────┼──────────────────────────┘
                                     ▼
                        exports/ (events.ndjson, manifest.json)
                        [future: API, dashboard, providers]
```

Trust boundaries: everything inside the core box is deterministic and offline.
The only external inputs are validated config/input files classified
`public_synthetic`. Nothing egresses; no clock/env/network access in core code.

## Data flow

1. `load_config()` validates the run configuration strictly (fail closed).
2. `run_simulation(config, clock)` constructs one root NumPy Generator from
   `run_seed` and derives isolated child streams per component
   (stage=1, chemistry=2, replay=3, synthetic_memory=4, ensemble=5).
3. Each epoch (tick): Process S integrates toward wake/sleep asymptote;
   circadian C(t) evaluates; stage semi-Markov advances on dwell expiry via its
   own stream; chemistry proxies map (S, C, stage) → four bounded values via
   their stream; the replay scheduler selects graph nodes via its stream.
4. Components emit frozen Pydantic events through an append-only store.
5. Canonical DQCJ-1 bytes and `core_trace_hash` derive from core records with
   nondeterministic provenance excluded; the manifest records versions, seeds,
   component IDs, and hashes.

## Component responsibilities

| Component | File | Responsibility |
|---|---|---|
| Process S / Circadian | `core/models/sleep_cycle.py` | Two-process-inspired homeostatic + sinusoidal proxies |
| Stage transitions | `core/models/sleep_cycle.py` | Semi-Markov Wake/N1/N2/N3/REM with bounded dwell distributions |
| Neuromodulatory proxy | `core/models/neurochemistry.py` | Four normalized [0,1] qualitative indices |
| Synthetic memory graph | `core/models/memory_graph.py` | Directed weighted graph over controlled synthetic tokens |
| Replay selection | `core/models/memory_graph.py` | Weighted graph-selection policy with exposed contributions |
| Events/provenance | `core/models/events.py` | Immutable event + manifest models, UUIDv5 IDs |
| Canonicalization | `core/serialization/dqcj.py` | DQCJ-1 bytes, trace/manifest hashes, vectors |
| Engine | `simulation/engine.py` | Orchestration of one deterministic run |

Layer separation follows MASTER_PROMPT.md §6.1: everything above is Layer A.
Layer B orchestration (LangGraph agents), providers, API, and visualization do
not exist yet and cannot be reached from the core.

## Ports and adapters present

- `Clock` protocol — `FixedClock` implementation (tests/demos). Real clocks are
  permitted only outside core hashing and are not yet wired anywhere.
- `EventStore` protocol — in-memory append-only implementation.
- `NarrativeProvider` protocol — offline deterministic `MockNarrativeProvider`
  (ADR 0003); cloud/local adapters deliberately not implemented yet.
Other ports (`ArtifactStore`, `GraphSerializer` beyond v1,
`CanonicalSerializer` beyond DQCJ-1, `RunRepository`) arrive with their
consumers in later milestones.

## Counterfactuals (M4 groundwork)

`simulation/counterfactual.py` runs fixed-seed control/changed pairs over an
explicit variation allowlist (`run_seed`, `epoch_seconds`, `total_ticks`,
`initial_stage`), enumerates every changed parameter exactly, and labels all
output differences as model-conditional — never causal biological effects
(§5.5). Deterministic: identical specs produce identical comparison bytes.

## Sweeps and ensembles (M4)

- `simulation/sweeps.py` — `ParameterSweep`: explicit single-field grids with
  documented cell ordering (fields sorted, values in declared order), a 64-cell
  runtime cap, and per-cell canonical-byte hashes. Identical grids produce
  identical sweep bytes.
- `simulation/ensemble.py` — `run_ensemble`: N members from declared integer
  seed shifts of one base config; duplicate effective seeds refused before any
  run; mean/min/max aggregates computed over member metrics only. Everything
  carries the exact §1.2 mechanistic_proxy label and the model-conditional
  disclaimer.

## Multi-night persistence and theme recurrence (M4)

`simulation/run_repository.py` provides the §3.1 `RunRepository` port with a
JSON-file implementation OUTSIDE the core: small per-night summaries (token
ids, stage sequence, trace hash) stored as canonical DQCJ-1 bytes, strict
run-id pattern plus resolved-path containment (traversal refused typed),
sorted listings. `theme_recurrence()` derives cross-night recurring-token
counts deterministically (count desc, then id) — counts only, no meaning
inference anywhere.

## Dashboard (M3)

`visualization/dashboard.py` (Streamlit) renders **verified exports only** —
loading runs the full fail-closed import verification; the loader imports no
engine/provider code. Every view carries the exact §1.2 visible labels.
Startup command, color-vision review, keyboard behaviour, and theme notes are
documented in [`DASHBOARD.md`](DASHBOARD.md). Gate-order interpretation for
starting M3 is recorded in ADR 0004.

## Determinism summary

See ADR 0001/0002. Identical `(config bytes, input bytes, package versions)`
in this environment ⇒ identical canonical core bytes and `core_trace_hash`.
Cross-platform identity is not claimed.

## Build, check, and demo commands

`make` is unavailable on the current host, so targets are documented as exact
commands (Windows, project-local `.venv`):

```bash
PY=".venv/Scripts/python.exe"
"$PY" -m pip install -c constraints.txt -e .        # install (editable dev)
"$PY" -m pytest -q                                   # test
"$PY" -m pytest -q --cov=src/dreamforge --cov-report=term-missing   # coverage
"$PY" -m ruff check src tests examples               # lint
"$PY" -m black --check src tests examples            # format-check
"$PY" -m mypy src/dreamforge/core                    # typecheck (strict)
"$PY" -m dreamforge.demo                             # 8-hour offline demo run
```

These correspond 1:1 to the M0 gate targets (`make lint`, `make format-check`,
`make typecheck`, `make test`, `make demo`) once a host with `make` runs them.

## Visualization plan (not built)

Dashboard views planned for M3 per MASTER_PROMPT.md §7 will document
color-vision review, non-color encodings, keyboard behavior, and theme
behavior at build time. No mockups exist now.
