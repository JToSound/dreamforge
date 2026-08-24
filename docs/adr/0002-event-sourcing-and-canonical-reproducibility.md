# ADR 0002 — Event sourcing, DQCJ-1 canonicalization, and RNG isolation

Status: Accepted
Date: 2026-08-24

## Context

MASTER_PROMPT.md §4 requires event-sourced runs whose canonical bytes are
reproducible and hashable, with a fully specified canonical JSON format
(DQCJ-1 — explicitly *not* claiming RFC 8785 conformance), UUIDv5 event IDs,
and per-component isolated random streams. The first execution must include
"minimal immutable event/provenance models and DQCJ-1 canonical serializer"
with byte-level test vectors.

## Decision

### Event model
- All events are frozen Pydantic models deriving from `BaseEvent` carrying:
  `run_id, event_id, event_type, event_sequence, tick,
  simulated_time_minutes, source_component, schema_version, correlation_id,
  emitted_at` (§4.2 field list).
- Payloads use immutable structures (tuples / `Mapping` wrappers). Deep
  immutability is enforced at construction by copying collections into tuples;
  we do not rely on `frozen=True` deep-freezing nested data (§4.4).
- `event_id = uuid5(NAMESPACE_DREAMFORGE_EVENT, UTF-8 bytes of the tuple
  (run_id, event_type, event_sequence, payload_hash))` where `payload_hash`
  is SHA-256 over DQCJ-1 bytes of the deterministic payload dict that excludes
  `event_id`, timestamps, and all nondeterministic provenance fields.
- `event_sequence` starts at 1, increases strictly, and is the only replay order.
- Timestamps (`emitted_at`) come from an injected `Clock`; they are excluded
  from every hash.

### DQCJ-1 (DreamForge Quantized Canonical JSON v1)
1. Input must already be schema-validated Pydantic models or plain
   JSON-compatible containers; serialization validates types recursively.
2. Rejects NaN, infinities, duplicate keys (detected during object parsing),
   unsupported types, and unpaired surrogates with typed errors.
3. Normalizes strings to NFC; a value that changes under NFC raises
   unless the caller passed it through the ingestion boundary opt-in
   (`normalize=True` path used only at ingestion).
4. Object keys sorted by Unicode code-point order.
5. Arrays serialized in schema-defined (insertion) order.
6. Float quantization applies **only** to fields declared as quantized in the
   event schema registry: value → `Decimal(str(x)).quantize(quantum,
   ROUND_HALF_EVEN)`. Undeclared floats raise rather than being silently
   formatted. Integers and booleans serialize as-is. All zeros (including
   `-0.0`) serialize identically as `0.0` so the sign of zero can never split
   a hash.
7. UTF-8 output, separators `,`/`:`, `ensure_ascii=False`, standard JSON string
   escaping; NDJSON records end with exactly one `\n`.
8. Version identifier `"dqcj": "DQCJ-1"` plus test-vector version are recorded
   in manifests.

`core_trace_hash` = SHA-256 over the concatenation of DQCJ-1 core record bytes
with nondeterministic provenance fields removed.
`manifest_hash` = SHA-256 over separate canonical manifest bytes.

### RNG isolation
Root generator seeded from `run_seed` (unsigned 64-bit). Child stream for a
component: `SeedSequence([run_seed, component_id])`. Fixed registry:
stage=1, chemistry=2, replay=3, synthetic_memory=4, ensemble=5. A component
never touches another's Generator instance; ensemble members derive from
stable member IDs. Contract version recorded in manifests.

## Alternatives considered
- **Claim RFC 8785 conformance** — rejected: JCS number serialization differs
  fundamentally from our declared-field quantization model; spec forbids the claim.
- **Hash full events including timestamps** — rejected: breaks §4.2 rule that
  provenance never affects hashes; would make replays environment-dependent.
- **One shared RNG stream for simplicity** — rejected: violates stream-isolation
  regression requirement; component changes would shift other components' draws.
- **msgpack/parquet canonical form** — rejected: text JSON keeps exports
  inspectable and diffable; NDJSON required by export layout.

## Consequences
- Positive: byte-stable audit trail; event IDs reproducible; component-level
  regressions detectable; exports verifiable without re-running simulation.
- Negative: custom serializer + vectors to maintain (accepted, spec-mandated);
  quantized boundary values require careful vector tests.
- Neutral: future RFC 8785 interop would be a separate named serializer.

## Migration / rollback
Version fields (`schema_version`, canonicalization version, vector version)
are in every artifact; format changes bump versions and add migration records
per §4.4. No rollback needed (greenfield).

## Status
Accepted; implemented with checked-in test vectors this session.
