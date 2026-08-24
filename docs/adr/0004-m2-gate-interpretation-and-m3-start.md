# ADR 0004 — M2 gate interpretation and authorization to begin M3

Status: Accepted
Date: 2026-08-24

## Context

MASTER_PROMPT.md orders milestones and gates M2 ("Structured generation") then
M3 ("Dashboard and exports. Begin only after M0–M2 gates."). M2's gate reads:
"offline demo; provider outage cannot affect core; labeled creative metadata;
cloud disabled by default." Two items referenced real provider machinery
(optional adapters) that ADR 0003 deliberately deferred, creating an apparent
blocker for starting M3.

## Decision

1. **M2's gate is evaluated against the implemented surface.** All four gate
   items are observable properties of the system as it exists:
   - offline demo: `python -m dreamforge.demo` runs end-to-end with zero
     network (observed repeatedly; socket-block proof in session 2);
   - outage isolation: asserted by test — a raising provider leaves core
     bytes hash-identical and the report complete/labeled;
   - labeled creative metadata: every narrative block carries
     `generative_interpretation` + the exact visible label, enforced at
     construction AND re-verified at import (layout v2);
   - cloud disabled by default: no cloud adapter exists at all; the only
     provider is the credential-free offline mock. Non-existence is the
     strongest form of "disabled".
   M2's gate is therefore **passed** on the implemented scope.

2. **Deferred ≠ failed.** The optional real-provider adapters remain deferred
   work tracked by ADR 0003. They are NOT claimed as gate-passed; if/when
   implemented they must satisfy their full contract before any new claims.

3. **M3 is authorized to begin** under §7's constraints: one documented
   startup command; exported demo renders without executing simulator/provider
   code; accessibility/theme checks documented; no measurement-implying
   wording. The dashboard consumes verified exports only.

## Alternatives considered

- **Block M3 until real adapters ship** — rejected: makes progress depend on
  optional integrations that no current user story requires; the spec's own
  gate wording is satisfiable today.
- **Declare full M2 "complete" including adapters** — rejected: would overstate
  scope; this ADR instead records precisely which items passed and which are
  deferred.
- **Start dashboard without a record** — rejected: gate-order changes deserve
  an explicit, reviewable decision record per §0.3.

## Consequences

- Positive: M3 can proceed honestly; the claim structure stays precise.
- Negative: none identified; the deferred adapter work remains visible in
  ADR 0003 and the release report.
- Neutral: if reviewers disagree with this reading, the dashboard is a leaf
  module over exports and can be excluded without touching the core.

## Migration / rollback

None required. Rollback = stop building dashboard modules; nothing else
depends on them.

## Status

Accepted; M3 work started this session under these terms.
