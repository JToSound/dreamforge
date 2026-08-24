# Security Policy

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

Status: initial baseline for the first execution slice. This file grows with
each milestone; items marked *(planned)* are declared now and enforced when the
corresponding surface exists.

## Threat model (current slice)

Assets: synthetic configuration/graph inputs, generated event traces, export
archives, developer machines. There are no user secrets, no credentials, no
network listeners in this slice.

Trust boundaries: file system ↔ config loader; export writer ↔ import reader.
Everything inside `src/dreamforge/core/` performs no I/O and reads no
environment variables or clocks.

## Data flow / trust-boundary diagram

```text
examples/configs/*.json ──▶ load_config() ──▶ engine ──▶ InMemoryEventStore
   (public_synthetic,          strict fail-closed            │
    schema-validated)                                        ▼
                                              DQCJ-1 bytes + SHA-256 hashes
                                                             │
                                              exports/<run>/events.ndjson (+manifest)
                                                             │  import path re-validates:
                                                             ▼  sequences, hashes, containment
                                                        verification report
```

## Egress rules

The core performs zero network access. No provider adapters exist yet. When
narrative providers arrive: local/offline mock default, cloud adapters disabled
by default, no PII/diary/memory text ever transmitted, requests logged by hash
not content *(planned with M2)*.

## Retention / deletion

Exports live where the user writes them (`exports/`). Deleting the directory
deletes the data. Nothing is transmitted or retained elsewhere.

## Input handling controls (enforced now)

- Strict schema validation, fail-closed on any violation.
- Path containment on artifact paths; traversal rejected.
- Size/depth/count limits on imports *(import surface arrives with M1 completion
  of export tooling; limits already encoded in loader)*.
- No unsafe deserialization (`pickle`/`eval` banned; JSON + Pydantic only).
- Rejected sensitive input is refused without logging raw text.

## Dependency / supply-chain policy

Direct dependencies pinned in `constraints.txt`; purposes documented in
`pyproject.toml`; licenses reviewed before adoption *(formal review recorded
with M5)*. Lock updates require re-running the full check suite.

## Vulnerability reporting

Report privately to the maintainers (contact to be added before first public
release). Please do not open public issues for security reports.

## Supported versions

Only the latest commit on `main` during pre-release development.

## Security-test coverage

Hostile-input negatives (bad config, bad seed type, illegal transitions,
oversized dwell draws) and no-network enforcement run in CI-equivalent local
checks today; archive-expansion/MIME cases arrive with the import surface.
