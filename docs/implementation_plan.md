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

---

# Session 2 Plan (2026-08-24, continuation)

## Objective

Close the remaining M1 gap identified in the session-1 release report: prove the
built wheel installs and behaves identically in a clean environment
(MASTER_PROMPT.md §3: "Install the built wheel into a clean environment … run
import smoke tests and tests against that installation").

## In scope

1. Build a wheel (`python -m build --wheel`, build tooling added to constraints).
2. Create a fresh venv; install ONLY the wheel + pinned constraints.
3. Import smoke from a neutral cwd: assert the loaded module resolves to
   site-packages (not src/), re-verify DQCJ byte vectors, and reproduce a
   small deterministic trace whose core hash matches the dev environment.
4. Run the full pytest suite against the installed-wheel environment.

## Out of scope

API/dashboard/providers/plugins (still forbidden), CI workflows, packaging
publishing, benchmark records.

## Acceptance criteria

- Wheel builds; clean venv contains no editable/src path.
- Smoke script prints ENGINE_PATH under site-packages, vectors pass, and the
  60-tick trace hash equals the dev-environment hash for identical config+seed.
- Full suite passes from the clean venv.
- Release report updated with only observed outcomes.

## Exact commands intended

".venv/Scripts/python.exe" -m pip install build
".venv/Scripts/python.exe" -m build --wheel
"C:/Users/User/AppData/Local/Microsoft/WindowsApps/python3.12.exe" -m venv .venv-wheel
".venv-wheel/Scripts/python.exe" -m pip install -c constraints.txt dist/*.py3-none-any.whl
cd $LOCALAPPDATA/Temp && ../..../.venv-wheel python scripts/smoke_installed_wheel.py
".venv-wheel/Scripts/python.exe" -m pytest -q

---

# Session 3 Plan (2026-08-24, M2 groundwork)

## Objective

Begin MASTER_PROMPT.md milestone M2 ("Structured generation") with the
deterministic half only: immutable DreamContext/DreamSegment, six [0,1]
structured features + weighted bizarreness score (§5.4), the mandatory offline
MockNarrativeProvider behind a typed protocol (§6.2), and composite-report
blocks each carrying exactly one primary output_class with the exact visible
label (§1.2). Plus ADR 0003 for the LLM/provider boundary.

## In scope

docs/adr/0003-narrative-provider-boundary.md;
src/dreamforge/core/models/dream_context.py;
src/dreamforge/core/scoring/bizarreness.py (+ public quantize_to in dqcj);
src/dreamforge/core/providers/narrative.py;
src/dreamforge/simulation/report.py; demo/report wiring; unit+integration
tests; RESEARCH.md + claim registry rows.

## Out of scope

LangGraph Layer-B agents, real/cloud provider adapters (declared deferred,
disabled-by-default in ADR 0003), unvalidated_secondary_rater (disabled by
default per §5.4 — documented, not implemented), dashboard/API.

## Key design decisions (subject to ADR 0003)

- Context construction is a POST-run pure function over emitted events —
  providers can therefore never mutate core state, and outage isolation is
  structurally guaranteed and tested.
- Features use documented evidence variables, missing-data -> 0.0, explicit
  normalizers/entropy denominators; score B = 100*clip(Σw·f,0,1) with
  validated weights (Σ=1, non-negative), scorer version recorded.
- MockNarrativeProvider renders from an ALLOWLISTED minimized projection only;
  records provider/model/template/context/response hashes + egress class;
  stores no prompts/responses. Budget overflow raises typed error (no silent
  truncation).

## Acceptance criteria

- All features provably in [0,1] incl. missing-data cases (property + unit).
- Same inputs -> identical context/score/narrative bytes; provider failure
  changes no core byte (hash equality asserted in test).
- Every report block serializes with correct exact §1.2 label strings.
- Full suite passes; coverage stays ≥85% core; ruff/black/mypy clean.

---

# Session 4 Plan (2026-08-24, M2 completion: report separation at export layer)

## Objective

Make the labeled composite report a first-class verified export artifact so
M2's "score, and report separation" holds at the file layer, not just in
memory: report.json inside the export, covered by a checksum and by fail-closed
import verification of its label contract.

## In scope

- Export layout v2: write_export gains optional `report`; when present the
  layout version bumps to "2" and report.json + SHA-256 join verification.json.
  Layout v1 exports remain importable (documented migration; no other consumers).
- import_and_verify: for v2, re-validate report.json strictly - schema, exact
  labels per block, run_id agreement with manifest, summary event_count
  agreement, bounded score, well-formed hashes - and its stored checksum.
- Demo writes the report; render-without-execution proof extended to v2.

## Out of scope

Dashboard/API (M3+, gated), provider adapters (ADR 0003), counterfactuals (M4).

## Acceptance criteria

- Round trip byte-identical; tampering any report field fails typed.
- v1 exports still verify; v2 without report.json refuses.
- Full suite green; coverage >=85%; ruff/black/mypy clean.

---

# Session 5 Plan (2026-08-24, parallel: M4 counterfactuals + M3 dashboard)

## Objective

Two bounded workstreams in one session, committed separately:
(A) M4 groundwork - fixed-seed CounterfactualEngine per §5.5 (control/changed
runs, enumerated changed parameters, model-conditional disclaimer);
(B) M3 dashboard start - offline Streamlit viewer over verified exports with
the §1.2 labels everywhere and an accessibility/theme document.

Gate-order note: M2's gate ("offline demo; provider outage cannot affect core;
labeled creative metadata; cloud disabled by default") is satisfiable NOW by
observed evidence because the only provider is the offline mock and cloud
adapters do not exist (ADR 0003). ADR 0004 records this interpretation and
authorizes starting M3. The optional real-provider items stay deferred and
are not claimed as passed.

## In scope

A: simulation/counterfactual.py + tests (determinism, invariants, disclaimer).
B: docs/adr/0004; visualization/loader.py (no engine import); visualization/dashboard app
(single-file Streamlit); DASHBOARD.md accessibility doc; AppTest smoke + label checks;
pyproject entry point + constraints pinning for streamlit/plotly.

## Out of scope

Real/cloud providers, LangGraph agents, parameter sweeps UI, multi-run DB,
3D/multi-person anything, API server.

## Acceptance criteria

A: same seeds+configs -> identical comparison bytes; changed-parameter list
exact; output differences labeled model-conditional everywhere.
B: bundled demo export renders without simulator/provider execution (AppTest);
every view carries the exact visible labels; keyboard/theme notes documented.
Full suite green; ruff/black/mypy clean; separate commits per workstream.

---

# Session 6 Plan (2026-08-24, M4: parameter sweeps + ensembles)

## Objective

Continue M4: deterministic parameter sweeps over the counterfactual machinery,
and fixed-seed ensemble runs with aggregate metrics. Both are pure post-hoc
orchestration over the existing engine - no new scientific claims, everything
labeled mechanistic_proxy.

## In scope

- simulation/sweeps.py: ParameterSweep - explicit grid of field overrides with
  deterministic cell ordering; each cell is a full CounterfactualComparison.
- simulation/ensemble.py: EnsembleRun - N member seeds from declared integer
  shifts of one base config; per-member RunMetrics + mean/min/max aggregates;
  duplicate effective seeds refused; labeled mechanistic_proxy.
- Unit tests: ordering determinism, aggregation invariants, label contract,
  refusal paths. Docs updates.

## Out of scope

Multi-night persistence/theme recurrence (needs a run repository port),
fictional pharmacology (deferred), LangGraph agents, sweep UI.

## Acceptance criteria

- Sweep cells execute in sorted documented order; identical grids produce
  identical result bytes.
- Ensemble aggregates provably derive from member metrics; labels exact.
- Full suite green; ruff/black/mypy clean.

---

# Session 7 Plan (2026-08-24, M4 completion: run repository + theme recurrence)

## Objective

Close M4's remaining items (multi-night synthetic persistence, theme
recurrence) by introducing the RunRepository port required by section 3.1,
with a JSON-file implementation outside the core (the core itself never does
filesystem work).

## In scope

- simulation/run_repository.py: StoredNightRecord (frozen model: night index,
  run_id, trace hash, selected token ids, final metrics subset),
  RunRepository protocol, JsonFileRunRepository with strict filename safety
  (run_id pattern + path-containment via resolved parents), canonical-bytes
  storage, sorted listing.
- theme_recurrence(nights): deterministic cross-night recurring-token report -
  pairwise consecutive-night intersections plus per-token appearance counts;
  exact mechanistic_proxy labeling; no interpretation beyond counts.
- Unit tests: round-trip, traversal refusal, ordering, recurrence math,
  label contract.

## Out of scope

Dashboard integration for multi-night views, real provider adapters,
pharmacology scenarios, M5 release chores.

## Acceptance criteria

- Store/load round-trip byte-stable; traversal-style ids refused typed.
- Recurrence output derives provably from stored records; identical inputs ->
  identical bytes; labels exact.
- Full suite green; ruff/black/mypy clean.

---

# Session 8 Plan (2026-08-24, M5 release preparation)

## Objective

Owner decision received: MIT. Execute M5 chores that need no further owner
input; draft the remaining checklist with explicit owner-action markers.

## In scope

- LICENSE (MIT, copyright 2026 JToSound - matches the owner's GitHub handle;
  trivially editable); pyproject license field; README license section.
- CHANGELOG.md (Keep a Changelog format, 0.1.0 entry).
- .github/workflows/ci.yml (ruff/black/mypy strict/pytest/build/wheel-install
  smoke on 3.11+3.12 matrix). Local equivalence runs recorded; the workflow
  itself executes only when pushed to GitHub (no remote by current setup).
- Container smoke: Dockerfile (slim python:3.12), .dockerignore; if the host
  has Docker, build and run the test suite inside the image - observed result
  recorded either way.
- pip-audit over the environment if network permits; otherwise documented.
- Rebuild wheel after metadata change; regenerate demo export; inspect.
- docs/M5_CHECKLIST.md with done/pending-owner items.

## Out of scope

PyPI publishing (needs owner accounts/decisions), SBOM formats beyond what
actually runs, real provider adapters (ADR 0003).

## Acceptance criteria

All executed items have observed outcomes in the release report; anything not
run is listed as NOT RUN without success language. Suite stays green.
