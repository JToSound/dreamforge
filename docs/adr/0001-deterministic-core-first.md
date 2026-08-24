# ADR 0001 — Deterministic-core-first

Status: Accepted
Date: 2026-08-24
Deciders: DreamForge technical lead (per MASTER_PROMPT.md §0 role)

## Context

MASTER_PROMPT.md requires a reproducible computational sandbox whose results
must be auditable byte-for-byte within a supported environment (§4.1 exactness
guarantee), while interactive/API/UI concerns are explicitly deferred (§7, §9:
"Do not create API routes, dashboard mockups, cloud adapters…"). The first
execution must prove an offline 8-hour deterministic trace before any interface
work.

Any early coupling to web frameworks, providers, or ambient state (clocks,
environment variables) would contaminate the determinism contract that every
later layer depends on.

## Decision

Build and prove **Layer A (deterministic core) first**, in this order:
domain models → deterministic engine → canonical serialization → tests →
(only later) interfaces. The core:

1. never imports FastAPI, Streamlit, LangGraph, provider SDKs, or filesystem/
   network clients;
2. never reads wall-clock time or environment variables; provenance timestamps
   arrive exclusively through an injected `Clock` protocol (`FixedClock` in
   tests/demos) and never affect state transitions or hashes;
3. uses exactly one seeded NumPy `Generator` root with named isolated child
   streams derived from `(run_seed, component_id)` (registry: stage=1,
   chemistry=2, replay=3, synthetic_memory=4, ensemble=5);
4. emits immutable Pydantic events consumed only through an in-memory
   append-only store for this phase.

Interfaces (API/dashboard/providers) are postponed until the core proves:
configuration validation, fixed-seed hash stability, bounded proxies, legal
transitions, export/import parity, and canonical-byte test vectors.

## Alternatives considered

- **Vertical slice through the UI first** — rejected: violates MASTER_PROMPT §9
  and would bake ambient nondeterminism into demos.
- **Adapters from day one for every port** — rejected as premature: only
  `Clock` is needed by the core now; other ports arrive with their consumers.
- **Wall-clock timestamps inside events hashed into the trace** — rejected:
  would make identical logical runs produce different hashes; timestamps are
  excluded from payload hashes by design (§4.2).

## Consequences

- Positive: every later feature inherits a verifiable determinism baseline;
  failures localize to a single component stream; CI can assert hash equality.
- Negative: no visible interface until M1 passes (accepted; stakeholders were
  warned by the milestone plan).
- Neutral: the component-ID registry is fixed and versioned; adding IDs later
  is additive and does not disturb existing streams.

## Migration / rollback

None required (greenfield). If the design fails its proof tests, the fallback
is narrowing scope further (fewer components), never weakening determinism.

## Status

Accepted and implemented in this first execution slice.
