# ADR 0003 — Narrative-provider boundary and LLM isolation

Status: Accepted (amended 2026-08-24: first networked adapters landed under
`dreamforge/integrations/` per ADR 0005 — the core remains network-free; the
mock stays the default; adapters are explicit-construction only)
Date: 2026-08-24

## Context

MASTER_PROMPT.md milestone M2 requires deterministic context construction, a
mandatory offline `MockNarrativeProvider`, strict provider validation, score
and report separation (§5.4, §6.2). Optional local/cloud adapters are allowed
but must be disabled by default, fail cleanly without configuration, and never
touch core state. §1.2 demands one primary `output_class` per user-facing
result with exact visible labels.

## Decision

1. **Structural isolation.** `DreamContext`/`DreamSegment` and all six
   structured features plus the bizarreness score are pure post-run functions
   over emitted core events. Narrative providers receive only a minimized,
   allowlisted projection of that context. There is no code path from a
   provider back into core state, events, scores, or the trace hash. A
   provider outage therefore cannot affect a completed core run — asserted by
   test via hash equality.

2. **Typed protocol now, adapters later.** This slice defines the
   `NarrativeProvider` protocol and the mandatory credential-free
   `MockNarrativeProvider` (deterministic template renderer). Local Ollama /
   OpenAI-compatible / Anthropic-compatible adapters are *declared* here and
   explicitly deferred: they may not be implemented until they can satisfy
   request/response schema validation, allowlists, timeouts, bounded retries,
   redacted errors, egress classification, and disabled-by-default wiring.
   Absence of configuration raises a typed error; no silent fallback to any
   networked provider exists.

3. **Minimized projection allowlist.** Providers see only: stage label,
   simulated time, bounded feature values, selected synthetic token IDs, and
   the score. No free text, no diary-like content, no PII — inputs are
   controlled tokens from `public_synthetic` data only. The projection is
   hashed into run provenance (`context_sha256`).

4. **Provenance over content.** Provider records keep hashes (request-schema,
   prompt-template, minimized-context, response) plus adapter/model identity,
   declared seed support, egress classification, and failure status. Prompt
   and response bodies are NOT stored; optional persistence would require an
   explicit local opt-in, retention policy, and output-class label — not built.

5. **Labeling contract.** Every narrative block is
   `generative_interpretation` with visible label "Generated interpretation —
   not a dream measurement or inference". Deterministic blocks are
   `mechanistic_proxy`. Composite reports label every block separately
   (§1.2). The mock's creative text is still labeled identically — the class
   describes the pipeline stage, not perceived quality.

## Alternatives considered

- **Let providers enrich features/scores** — rejected outright: would make
  "deterministic score" a lie and violate §6.1 Layer separation.
- **Implement cloud adapters behind flags in this slice** — rejected: cannot
  honestly verify outage/retry/redaction behavior without real endpoints;
  deferring keeps M2's gate verifiable offline.
- **Store prompts/responses for debugging** — rejected for default behavior:
  retention risk without opt-in; hashes suffice for integrity checks.
- **Free-form mock text** — rejected: templates keyed on structured fields
  keep the mock deterministic and byte-reproducible like everything else.

## Consequences

- Positive: outage isolation provable by hash equality; offline demos forever
  reproducible; clear contract future adapters must satisfy.
- Negative: narratives from the mock are intentionally plain; adapters delayed
  until their full contract can be tested.
- Neutral: `unvalidated_secondary_rater` remains unimplemented (disabled by
  default per §5.4) — any future implementation inherits this boundary.

## Migration / rollback

None (additive). If adapters land later, they arrive as new modules behind the
same protocol; the mock remains the default and test fixture.

## Status

Accepted; protocol + mock implemented this session.
