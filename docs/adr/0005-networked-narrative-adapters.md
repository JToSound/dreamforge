# ADR 0005 — Landing the first networked narrative adapters

Status: Accepted
Date: 2026-08-24

## Context

ADR 0003 deferred real narrative-provider adapters until they could be built
and tested offline while satisfying the full contract: schema validation,
timeouts, bounded retries, redacted errors, and disabled-by-default wiring.
M0–v0.1.0 are done; the deferred item was the last open engineering track.

## Decision

1. **Adapters live OUTSIDE the core** (`dreamforge/integrations/`). The
   deterministic core (§3, §4.1) keeps its zero-network, zero-environment
   guarantee untouched; importing the integration package is always explicit.
2. **Transport injection.** Providers depend on a tiny `HttpTransport`
   protocol. Production uses `UrllibTransport` (stdlib `urllib`, no new
   dependency); tests use scripted fakes. Every contract property is exercised
   offline against fakes — no credentials, no live endpoints in CI.
3. **OpenAI-compatible surface first** (`OpenAICompatProvider`): one adapter
   covers OpenAI-style `/chat/completions` endpoints including Ollama's
   `/v1` compatibility mode. Configuration is a frozen config object supplied
   by the CALLER — the adapter never reads environment variables or files;
   nothing is enabled unless application code constructs it.
4. **Contract enforcement:**
   - requests carry only the allowlisted `MinimizedContext` projection;
   - response schema strictly validated; malformed responses become typed
     redacted errors (`status code` + `response sha256`, never raw bodies);
   - per-attempt timeout; at most `max_retries` retries on transient failures
     then fail closed; backoff injectable so tests stay instant;
   - budget enforcement happens BEFORE any bytes hit the wire;
   - every response records schema/template/context/response hashes,
     decoding, and an honest `egress_classification`.
5. **Mock remains the default.** Demo and dashboard never construct the
   networked provider; docs show an explicit opt-in example.

## Alternatives considered

- SDK-based clients (openai/anthropic packages) — rejected: adds heavy
  dependencies to a zero-dep-preference project and hides the retry/timeout
  behaviour we need to guarantee.
- Putting adapters under `core/providers/` — rejected: would break the
  core-purity invariant that nothing under `core/` performs I/O.
- Env-var-driven enablement — rejected by §4.1; explicit construction only.

## Consequences

- Positive: the deferred contract item lands honestly and stays fully
  testable offline; core purity intact; Ollama users get local-model support
  with zero credentials.
- Negative: more modules to maintain; urllib streaming limitations are
  acceptable for small JSON payloads.
- Neutral: an Anthropic-native adapter follows the same shape.

## Status

Accepted; implemented with offline-tested contract coverage. Amended same day:
the Anthropic-native follow-up landed (`integrations/anthropic_compat.py`),
both adapters share one bounded retry/redaction path (`integrations/retry.py`),
and mypy strict coverage extends to the whole integrations package.
