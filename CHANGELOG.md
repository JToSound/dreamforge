# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

## [Unreleased]

## [0.2.0] - 2026-08-24

### Added

- Optional networked narrative providers behind an injected HTTP transport
  (`dreamforge.integrations`, ADR 0005) — the deterministic core remains
  network-free and the offline mock stays the default:
  - `OpenAICompatProvider`: any `/chat/completions` endpoint incl. Ollama
    `/v1`; frozen caller-supplied config; budget enforced before any request;
    strict response schema; per-attempt timeout; bounded retries then
    fail-closed; errors redacted to status code + response sha256 only;
    honest `network_loopback` / `network_remote` egress classification.
  - `AnthropicCompatProvider`: messages API (top-level system field, required
    `max_tokens`, temperature 0, `x-api-key` + `anthropic-version` headers,
    content-block text extraction); retryable set includes Anthropic's 529.
  - Shared vetted bounded-retry/redaction layer (`integrations/retry.py`,
    `integrations/errors.py`) used by both adapters.
- mypy strict coverage widened to the whole integrations package.

[0.2.0]: https://github.com/JToSound/dreamforge/releases/tag/v0.2.0

## [0.1.0] - 2026-08-24

### Added

- Deterministic core: two-process-inspired sleep-regulation proxy, semi-Markov
  stage model (Wake/N1/N2/N3/REM, bounded integer-epoch dwells), four-channel
  normalized neuromodulatory proxy, synthetic token graph with weighted replay
  selection — all offline, fixed-seed, per-component isolated RNG streams.
- Event sourcing: immutable envelope/payload models, UUIDv5 event IDs derived
  from quantized canonical payloads, append-only store with strict sequences.
- DQCJ-1 canonical JSON serializer (declared-field quantization,
  ROUND_HALF_EVEN, NFC enforcement, sign-of-zero normalization) with 9
  checked-in byte-level test vectors.
- Exports: layout v2 (`events.ndjson`, `manifest.json`, `report.json`,
  `config.canonical.json`, `graph_snapshot.json`, `verification.json`,
  README) with SHA-256 checksums and 22-check fail-closed import verification;
  render-without-execution proven by subprocess probes.
- Structured dream context: six bounded features with documented evidence
  variables/normalizers/missing-data behaviour; bizarreness score
  B = 100·clip(Σw·f, 0, 1) with validated weights; LLM rater not implemented.
- Narrative provider protocol + deterministic offline `MockNarrativeProvider`
  (allowlisted minimized projection; hashes recorded; no payload storage).
  Cloud/local adapters deliberately deferred (ADR 0003).
- Composite run report: every block carries its exact §1.2 output_class label.
- M4 research sandbox: fixed-seed counterfactual pairs with exact changed-
  parameter accounting, parameter sweeps (capped, ordered), seed-shift
  ensembles with aggregates, JSON-file run repository (§3.1 port) with path
  containment, theme-recurrence counting across nights.
- Streamlit dashboard over verified exports only: stage timeline, proxy
  timeline, features/score, narrative block, verification table; fail-closed
  on any verification fault; accessibility/theme notes in DASHBOARD.md.
- Docs: ARCHITECTURE, RESEARCH, LIMITATIONS, SECURITY, claim registry,
  ADRs 0001–0004, DASHBOARD.md, implementation plan + release reports.
- Tooling: pinned constraints, wheel build + clean-venv smoke scripts,
  MIT license.

[0.1.0]: https://github.com/JToSound/dreamforge/releases/tag/v0.1.0
