# Release Report — First Execution Slice (M0 partial + M1 vertical slice)

Date: 2026-08-24 · Author: DreamForge technical lead session (agent)
Scope authority: MASTER_PROMPT.md §9 ("First execution only") + §0.2 session protocol.

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

## Smallest recommended next step

Close the remaining M1 gap: add a clean-venv wheel-build + install + import-smoke
test (build wheel, install into fresh venv from `constraints.txt`, import
`dreamforge.core.serialization.dqcj` and re-verify the checked-in vectors), then
declare the M1 gate with measured evidence.
