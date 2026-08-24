# Release Report — First Execution Slice (M0 partial + M1 vertical slice)

Date: 2026-08-24 · Author: DreamForge technical lead session (agent)
Scope authority: MASTER_PROMPT.md §9 ("First execution only") + §0.2 session protocol.
Session 2 addendum at the bottom closes the installed-wheel gap.

## Changed / created files

Repository bootstrap: `.gitattributes`, `.gitignore`, `.editorconfig`, `.env.example`,
`pyproject.toml`, `constraints.txt`.
Documents: `ARCHITECTURE.md`, `README.md`, `RESEARCH.md`, `LIMITATIONS.md`,
`SECURITY.md`, `docs/adr/0001-deterministic-core-first.md`,
`docs/adr/0002-event-sourcing-and-canonical-reproducibility.md`,
`docs/scientific_model/claim_registry.yaml`, `docs/implementation_plan.md`, this report.
Source: `src/dreamforge/{__init__,demo}.py`, `core/config.py`,
`core/models/{events,sleep_cycle,neurochemistry,memory_graph}.py`,
`core/provenance/clock.py`, `core/serialization/dqcj.py`,
`simulation/engine.py`, `simulation/export_import.py` (+ package `__init__` files).
Examples/tests/tooling: `examples/configs/demo_8h.json`,
`tests/**` (7 unit/property/integration modules + conftest),
`tests/fixtures/dqcj1_vectors.json`, `scripts/generate_dqcj_vectors.py`.

## Decisions / ADRs

- ADR 0001 deterministic-core-first; ADR 0002 event sourcing + DQCJ-1 + RNG isolation.
- Lock strategy: pinned `constraints.txt` (make/uv/poetry unavailable on host).
- DQCJ-1 rule addition: all float zeros serialize as `0.0` (sign-of-zero cannot split a hash).
- Event IDs derive from the **quantized** canonical payload form; export NDJSON carries
  the same quantized form, so file bytes, payload-hash inputs, and trace-hash inputs agree.
- Per-tick emission order fixed as `[sleep_state(new stage), stage_transition]`;
  import verification interprets transition origins accordingly.
- mypy checked under Python 3.12 semantics (numpy≥2.5 stubs use 3.12-only syntax);
  runtime floor remains ≥3.11.

## Commands actually run and observed outcomes (Windows 11, Python 3.12.10)

| Command | Observed outcome |
|---|---|
| `python3.12 -m venv .venv` + `pip install … numpy pydantic networkx pytest pytest-cov hypothesis ruff black mypy` | exit 0; versions pinned into `constraints.txt` |
| `.venv/Scripts/python.exe -m pip install -e .` | exit 0 (editable install) |
| `.venv/Scripts/python.exe -m pytest -q` | **84 passed** (unit + property + integration) |
| `.venv/Scripts/python.exe -m pytest -q --cov=src/dreamforge/core` | core line coverage **91%** total; every module ≥85% (`config` 92%, `events` 95%, `memory_graph` 93%, `neurochemistry` 93%, `sleep_cycle` 88%, `clock` 85%, `dqcj` 86%) |
| `.venv/Scripts/python.exe -m ruff check src tests examples scripts` | All checks passed |
| `.venv/Scripts/python.exe -m black --check src tests examples scripts` | 27 files unchanged |
| `.venv/Scripts/python.exe -m mypy src/dreamforge/core` | Success: no issues found in 11 source files (strict) |
| `.venv/Scripts/python.exe -m dreamforge.demo` (run twice) | both runs: `core_trace_hash = e86cd3402307ae914618a363ab34393cf97ba6ff2e7dbebe210bff4a5afee27b`, `manifest_hash = 615ca575ce828d5e5c8d1f876eb8d50ac1776f7661df39006c74856c8d8b0e86`; 2173 events (960 sleep_state, 960 neurochemical_state, 133 stage_transition, 120 memory_replay); `import verification: ok=True checks=20` |

Determinism evidence: two independent full 960-epoch executions produced identical
core trace and manifest hashes; unit/integration tests additionally assert hash
equality across *different* provenance clocks and inequality across different seeds.

Artifacts actually generated and inspected: `exports/demo_8h/{events.ndjson (2173 lines),
manifest.json, config.canonical.json, graph_snapshot.json, verification.json, README.txt}`.
They are regenerable via the demo command and therefore not committed (gitignored).

## Commands NOT run

- `make lint/format-check/typecheck/test/demo` — `make` absent on host; exact command
  equivalents were run instead and are documented in ARCHITECTURE.md.
- GitHub Actions workflow, Docker Compose build/smoke — not created (outside §9 scope).
- Clean-vevn installed-wheel import test — deferred (editable install verified only);
  required before the M1 gate is declared fully closed.
- SBOM/audit artifact generation — not run, so none is claimed or retained.
- Cross-platform byte-identity checks — single-host verification only; spec promises
  byte identity within the supported environment, documented tolerance elsewhere.
- No benchmark records produced; no performance numbers are claimed anywhere.

## Known limitations

- Determinism verified on one Windows/CPython 3.12 machine with the pinned versions.
- DQCJ-1 test vectors cover representative cases (9 cases); RFC 8785 interop is
  deliberately out of scope.
- Replay anti-repetition currently uses novelty accumulation; the configured
  recent-window is reserved for a future hard-exclusion variant.
- Graph budget enforcement (pruning/compression warnings) not yet implemented;
  no budget was exceeded at demo sizes.
- Pharmacology, scenarios/counterfactuals, context features/bizarreness scoring,
  providers, API, dashboard: not started (later milestones).
- License text is an explicit placeholder pending the owner's licensing decision (M5).

## Blockers

None. No credentials, network services, or owner approvals were required for this slice.

---

# Session 2 Addendum — Installed-wheel verification (M1 gap closed)

Date: 2026-08-24 (same day, continuation session).

## What was done

1. Built `dist/dreamforge-0.1.0-py3-none-any.whl` (`pip install build`;
   `python -m build --wheel`) — observed success.
2. Created a clean venv `.venv-wheel` from WindowsApps python3.12 and installed
   **only** the wheel + pinned `constraints.txt` — observed success
   (installed set: dreamforge 0.1.0, numpy 2.5.2, pydantic 2.13.4,
   networkx 3.6.1 + transitive pins).
3. Ran `scripts/smoke_installed_wheel.py` from a neutral cwd (TEMP) under the
   clean venv — all four proofs passed:
   - proof-1 module path resolves to
     `.venv-wheel/Lib/site-packages/dreamforge` (no src/editable leakage);
   - proof-2 all 9 checked-in DQCJ-1 byte vectors reproduce exactly;
   - proof-3 installed-wheel 60-tick/seed-777001 trace hash equals the dev
     reference: `85b4a5b2e022d2af88a74f49101a2b84fc6088105c6078466efae1f6aa07014d`
     (dev value produced by `scripts/record_dev_trace_hash.py` under `.venv`);
   - proof-4 a full trace re-run with `socket.socket`/`socket.create_connection`
     monkey-blocked completes with an identical hash → zero connection attempts.
4. Installed pytest+hypothesis into the clean venv and ran the full suite
   against the installed wheel: **84 passed**.
5. The clean-environment Hypothesis run found one legitimate gap the dev run
   had not hit: the DQCJ round-trip property did not exempt the rule-3 NFC
   rejection path. Fixed the test to treat `DQCJNormalizationError` as an
   accepted-input boundary; production code was NOT weakened.

## Commands actually run (observed outcomes)

| Command | Outcome |
|---|---|
| `.venv/Scripts/python.exe -m pip install build` | exit 0 |
| `.venv/Scripts/python.exe -m build --wheel` | `Successfully built dreamforge-0.1.0-py3-none-any.whl` |
| python3.12 `-m venv .venv-wheel` + `pip install -c constraints.txt dist/*.whl` | exit 0 |
| `.venv/Scripts/python.exe scripts/record_dev_trace_hash.py` | `85b4a5b2…07014d` |
| clean-venv smoke (from `$LOCALAPPDATA/Temp`) | `SMOKE PASS`, proofs 1–4 OK |
| `.venv-wheel/Scripts/python.exe -m pytest -q` | **84 passed** |
| `.venv/Scripts/python.exe -m pytest -q` (re-run after fix) | **84 passed** |
| ruff / black / mypy strict (final sweep) | All checks passed / unchanged / no issues |

## Honest notes

- An earlier draft of proof-4 asserted "no socket module in sys.modules"; that
  invariant is false-by-construction because pydantic → importlib.metadata →
  email/zipfile transitively imports stdlib socket/urllib without network use.
  Replaced with the behavioral zero-connection-attempts proof above.
- Two smoke-script bugs were found by its own failures (marker string used dots
  instead of a slash; helper referenced before definition) — both fixed in the
  script, neither touched library code.
- `dist/` and `.venv-wheel/` are untracked build artifacts; `dist/` added to
  .gitignore this session.

## M1 gate status

The last open item ("clean installed-wheel import test") is now closed with
measured evidence. Remaining pre-gate items are milestone-level (CI workflow,
container smoke), which MASTER_PROMPT.md assigns to later milestones/M5, not §9.

## Smallest recommended next step

M1's §9-scope items are complete. Next bounded action: begin M2 groundwork —
deterministic `DreamContext`/`DreamSegment` models, the mandatory offline
`MockNarrativeProvider`, and structured feature/score separation (MASTER_PROMPT.md
§5.4, §6.2, milestone M2) — starting with an implementation plan and ADR for the
provider boundary. No dashboard/API work before the M2 gate (§7).

---

# Session 3 Addendum — M2 groundwork (deterministic half)

Date: 2026-08-24 (continuation session).

## What was done

- ADR 0003 accepted: narrative-provider boundary, structural outage isolation,
  adapters deferred until their full contract is testable offline.
- `core/models/dream_context.py`: immutable `DreamSegment`/`DreamContext`,
  segment builder over sleep_state events only, six [0,1] features with
  documented evidence variables/normalizers/missing-data behaviour, and
  per-segment replay-token attachment.
- `core/scoring/bizarreness.py`: validated weights (non-negative, sum-to-one),
  single terminal clip, B = 100·clip(Σw·f, 0, 1), scorer version recorded;
  export quantization to two decimals. `unvalidated_secondary_rater`
  deliberately NOT implemented (disabled by default).
- `core/providers/narrative.py`: typed `NarrativeProvider` protocol,
  allowlisted `MinimizedContext` projection (hashed; budget-checked, never
  silently truncated), credential-free deterministic `MockNarrativeProvider`
  recording schema/template/context/response hashes + egress class.
- `simulation/report.py`: composite `RunReport` where every block carries
  exactly one §1.2 output_class + exact visible label; narrative stays None
  unless explicitly attached — provider failure leaves a complete report.
- Demo now prints labeled context/features/score/narrative blocks.

## Commands actually run (observed outcomes)

| Command | Outcome |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **110 passed** |
| `pytest --cov=src/dreamforge/core` | core coverage: dream_context 94%, providers/narrative 97%, scoring/bizarreness 90%; all modules ≥85% |
| ruff / black / mypy strict (16 source files) | All checks passed / unchanged / no issues |
| `python -m dreamforge.demo` | full pipeline OK; context blocks labeled mechanistic_proxy; narrative block labeled generative_interpretation |

## Honest notes

- An initial segment "merge short trailing episodes" behaviour mislabeled
  stages; removed in favour of truthful per-episode segments (docstring
  documents that min_segment_ticks currently does not merge).
- The demo initially showed "(none)" tokens because segments were not joined
  with replay selections; fixed by attaching selections to containing segments.
- Cloud/local provider adapters remain unimplemented BY DESIGN (ADR 0003);
  the M2 gate items they belong to stay open until then.

---

# Session 4 Addendum — M2 completion: report separation at the export layer

Date: 2026-08-24 (continuation session).

## What was done

- Export layout bumped to v2: `write_export` accepts an optional `RunReport`
  and embeds it as canonical-bytes `report.json`; the artifact joins the
  checksum map in verification.json. Layout v1 exports remain importable
  (documented migration; a v2 declaration without report.json is refused).
- `import_and_verify` gained typed fail-closed checks: report schema,
  run_id agreement with the manifest, summary event_count agreement with the
  actual event stream, exact per-block label contract (§1.2), score bounds,
  and byte-identical canonical round-trip of the stored report.
- Demo now writes report.json (import verification grew 20 -> 22 checks).
- ImportedRun carries the reconstructed labeled report for downstream readers.

## Commands actually run (observed outcomes)

| Command | Outcome |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **116 passed** (6 new layout-v2 integration tests) |
| ruff / black / mypy strict | All checks passed / unchanged / no issues |
| `python -m dreamforge.demo` | export now includes report.json sha256=...; import verification ok=True checks=22 |

## Honest notes

- The verifier caught a test-helper bug during development (fake event counts
  disagreed with the actual stream) — exactly the failure mode this check
  exists for; the helper was fixed to count real events.
- Legacy-layout support is asserted by downgrading the declared version in a
  test; no external consumers exist, so migration behaviour is untested
  against third-party tooling by definition.
- The demo's exported hashes changed from earlier sessions because the export
  set itself changed (report.json added); the core trace hash is unchanged.

---

# Session 5 Addendum — M4 counterfactuals + M3 dashboard (parallel)

Date: 2026-08-24 (continuation session).

## Workstream A: Counterfactual engine (M4 groundwork)

- `simulation/counterfactual.py`: `CounterfactualSpec` (variation allowlist:
  run_seed/epoch_seconds/total_ticks/initial_stage; anything else refused),
  `run_counterfactual` executes the control/changed pair with the component
  RNG policy untouched, enumerates changed parameters EXACTLY from validated
  payloads, and returns a fully labeled comparison carrying the
  model-conditional disclaimer (§5.5). Zero-difference specs are refused.
- Evidence: 7 new unit tests pass, including byte-identical determinism of
  the comparison and exact single-parameter enumeration.

## Workstream B: Dashboard (M3 start)

- ADR 0004 accepted: M2's gate evaluated against the implemented surface
  (offline mock-only provider; non-existent cloud adapters = strongest form
  of "disabled"); deferred adapters tracked separately; M3 authorized.
- `visualization/loader.py` imports NO engine/provider code (subprocess probe
  asserts ENGINE_NOT_LOADED); `visualization/dashboard.py` renders verified
  exports only — ANY verification fault shows an error instead of charts
  (fail closed).
- Views carry exact §1.2 labels: stage timeline + replay markers,
  proxy timeline, features/score block, narrative block, verification table;
  disclaimer in header banner and footer.
- `DASHBOARD.md`: one startup command, color-vision review (position/labels
  carry information, not hue), keyboard behaviour, light/dark theme notes.
- streamlit 1.62.0 / plotly 6.9.0 pinned in constraints.txt; optional
  `dashboard` extra declared in pyproject.toml.

## Commands actually run (observed outcomes)

| Command | Outcome |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **127 passed** (7 cf + 6 dashboard/loader new) |
| ruff / black / mypy strict | All checks passed / unchanged / no issues |
| Streamlit AppTest smoke | labels render; tampered export -> "Verification FAILED", no charts |

## Honest notes

- AppTest initially failed because it inherits pytest's sys.argv; export
  resolution now prefers query parameters over argv, making hosted/tested
  contexts deterministic. CLI usage unchanged.
- The dashboard's fail-closed path was widened from ImportError_-only to any
  exception after a malformed-export test exposed a JSONDecodeError leak.
