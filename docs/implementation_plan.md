# Implementation Plan — First Execution (M0 partial + M1 vertical slice)

Date: 2026-08-24 (session 1)
Authority: `MASTER_PROMPT.md` v7.0. On conflict, MASTER_PROMPT.md wins; precedence per its Section 0.1.

## Objective

Execute Section 9 ("First execution only") exactly: prove an offline, deterministic,
8-hour (960 × 30 s epoch) simulation trace with configuration validation, fixed-seed
core hashing, finite bounded proxy values, permitted stage transitions,
export/import reconstruction, byte-level canonicalization test vectors, and
truthful limitation disclosure — plus the documents Section 9 mandates.

## In scope (Section 9 list only)

1. `ARCHITECTURE.md`
2. `docs/adr/0001-deterministic-core-first.md`
3. `docs/adr/0002-event-sourcing-and-canonical-reproducibility.md`
4. Minimal package metadata + lock strategy (pinned constraints file)
5. `src/dreamforge/core/models/sleep_cycle.py`
6. `src/dreamforge/core/models/neurochemistry.py`
7. `src/dreamforge/core/models/memory_graph.py`
8. Minimal immutable event/provenance models + DQCJ-1 canonical serializer
9. One synthetic structured input/configuration (`examples/configs/demo_8h.json`)
10. One minimal end-to-end deterministic integration test

Plus what Section 0.2 requires of any session: `docs/implementation_plan.md`
(this file) and `docs/release_report.md`. Plus repository hygiene files needed
to commit safely (.gitattributes before first add, .gitignore, .editorconfig).
Plus README/RESEARCH/LIMITATIONS/SECURITY skeletons carrying the mandatory
disclaimer sentence (M0 gate items kept minimal but truthful).

## Out of scope (explicitly forbidden by Section 9)

API routes, Streamlit dashboard, dashboard mockups, cloud/LLM provider adapters,
plugins, notebooks, speculative features, pharmacology scenarios, LangGraph
orchestration, Docker/CI workflows beyond local commands. None of these will be
created this session.

## Discovered state

- Directory contained only `MASTER_PROMPT.md` and an empty `prompts/` directory.
- Not a git repository (`git status` → "not a git repository").
- Python 3.12.10 available at
  `C:/Users/User/AppData/Local/Microsoft/WindowsApps/python3.12.exe`
  (the bare `python` on PATH is a different, tool-managed interpreter without pip;
  it must not be used for this project).
- `make`, `uv`, `poetry` not found on PATH → Makefile targets cannot run here.
  Lock strategy chosen: **pinned constraints** (`constraints.txt`) installed via
  `pip` into a project-local `.venv`, which Section 3 explicitly permits as one of
  three lock strategies. Documented exact install command replaces `make`.
- No network restrictions encountered for PyPI installs (pending observed result
  recorded in release report).

## Assumptions

- Target runtime is CPython 3.12 on Windows (3.11+ satisfies the contract);
  cross-platform byte-identity of hashes is NOT promised (Section 4.1 wording) —
  tests assert determinism within this environment, and canonical bytes are
  exercised through explicit test vectors rather than platform assumptions.
- Only standard PyPI packages are used; no proprietary credentials required.
- All data in this session is `public_synthetic`.

## Proposed interfaces (minimal, subject to ADRs)

```python
# core/models/events.py
SimulationRunManifest, BaseEvent (frozen pydantic), StageTransitionEvent,
NeurochemicalStateEvent, MemoryReplayEvent, MetricSnapshotEvent
# core/models/sleep_cycle.py
ProcessSConfig, CircadianConfig, SleepRegulationModel(.step(tick, awake))
StageDwellConfig, TransitionMatrixConfig, SleepStageTransitionModel(
    .current_stage, .advance(tick) -> StageTransitionEvent | None)
# core/models/neurochemistry.py
NeurochemistryConfig, NeurochemicalProxyModel(.step(tick, stage))
# core/models/memory_graph.py
SyntheticMemoryGraphSpec/build_synthetic_graph(), ReplaySelectorConfig,
ReplayEventScheduler(.select(tick, stage) -> ReplaySelection)
# core/provenance/clock.py
Clock protocol, FixedClock(UTC fixed datetime)
# core/serialization/dqcj.py
dumps_canonical(obj) -> bytes   # DQCJ-1, raises DQCJError subclasses
core_trace_hash(events) -> str  # SHA-256 over DQCJ-1 core records
# core/config.py
load_config(path | dict) -> SimulationConfig  # strict validation
# simulation/engine.py
run_simulation(config, clock) -> SimulationResult(events, manifest, trace_hash)
```

RNG: single root `numpy.random.Generator(PCG64(SeedSequence(run_seed)))`;
child streams `SeedSequence([run_seed, component_id])`; component registry:
stage=1, chemistry=2, replay=3, synthetic_memory=4, ensemble=5 (ADR 0002).

## Data classification

All inputs/outputs this session: `public_synthetic`. No PII, no health data,
no diary text, no network egress at runtime. Providers are out of scope.

## Scientific-claim impact

No empirical claims introduced. Every parameter carries `evidence_grade`
(`assumption` or `synthetic_demo`) with rationale strings. The claim registry
starts with entries that map each implemented equation to its grade and states
that no source has been verified yet — citations are added only after
bibliographic verification (Section 5). The mandatory disclaimer sentence is
placed verbatim in README/RESEARCH/LIMITATIONS (API/dashboard do not exist yet).

## Risks

| Risk | Mitigation |
|---|---|
| Windows path/encoding issues in tests | UTF-8 everywhere, `pathlib`, LF enforcement via .gitattributes |
| Coverage target unreachable in one session | Measure honestly; report actual numbers, never claim gates unmeasured |
| Semi-Markov dwell sampling complexity | Bounded integer-epoch distributions with hard cap + resampling counter, unit tested |
| Float quantization ambiguity in DQCJ-1 | Quantize only declared fields via Decimal ROUND_HALF_EVEN; reject undeclared floats |
| Time budget | Scope frozen to Section 9 list; anything extra deferred to next session |

## Acceptance criteria (this session)

- `pytest` passes: unit, integration (960 epochs), property (Hypothesis),
  canonical-byte vectors, export/import parity, config-rejection negatives.
- Identical config+seed → identical `core_trace_hash` (asserted twice).
- Proxy values finite in [0,1]; every emitted transition allowed by the
  exported matrix; event sequences strictly ordered from 1.
- Import reconstructs an exported run and re-verifies hashes.
- Ruff + Black clean; mypy strict passes on `src/dreamforge/core/` (api/ does
  not exist yet); coverage numbers reported truthfully against targets.
- Release report written with only actually-run commands and real outcomes.

## Migration/deprecation impact

None (greenfield). Public interfaces are minimal and versioned from birth;
compatibility breaks later require ADRs per Sections 2–3.

## Exact commands intended

```bash
git init -b main
"C:/Users/User/AppData/Local/Microsoft/WindowsApps/python3.12.exe" -m venv .venv
".venv/Scripts/python.exe" -m pip install --upgrade pip setuptools wheel
".venv/Scripts/python.exe" -m pip install -c constraints.txt <packages>
".venv/Scripts/python.exe" -m pytest -q
".venv/Scripts/python.exe" -m pytest -q --cov=src/dreamforge --cov-report=term-missing
".venv/Scripts/python.exe" -m ruff check src tests examples
".venv/Scripts/python.exe" -m black --check src tests examples
".venv/Scripts/python.exe" -m mypy src/dreamforge/core
```

(Make targets are documented in ARCHITECTURE.md as plain command equivalents
because `make` is unavailable on this host.)
