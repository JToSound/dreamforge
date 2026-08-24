"""Typed narrative-provider protocol and the mandatory offline mock (§6.2).

Boundary rules enforced here (ADR 0003):

- Providers render ONLY from a minimized allowlisted projection of the
  deterministic ``DreamContext``. They can never write core events, model
  parameters, or the trace hash.
- The mandatory default is :class:`MockNarrativeProvider`: offline,
  deterministic, credential-free, byte-reproducible.
- Cloud/local adapters (Ollama, OpenAI-compatible, Anthropic-compatible) are
  declared but deliberately NOT implemented yet; they may only land once they
  satisfy schema validation, timeouts, bounded retries, redacted errors, and
  disabled-by-default wiring.
- Provenance records hashes and identity — never prompt/response bodies.

DreamForge is a research and visualization simulator. It does not measure
brains, diagnose conditions, predict dreams, infer psychological meaning, or
provide medical advice.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from dreamforge.core.serialization.dqcj import dumps_canonical

#: Exact visible label for every generative block (§1.2 output taxonomy).
GENERATIVE_LABEL = "Generated interpretation — not a dream measurement or inference"
OUTPUT_CLASS_GENERATIVE = "generative_interpretation"

_MAX_CONTEXT_CHARS = 4000


class ProviderError(RuntimeError):
    """Base error for provider failures; never carries raw payloads."""


class ProviderConfigError(ProviderError):
    """Raised when required configuration is absent or invalid."""


class ContextBudgetExceededError(ProviderError):
    """Raised when the minimized projection exceeds the declared budget."""


class MinimizedContext(BaseModel):
    """Allowlisted projection: the ONLY data a provider may see."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    stage_labels: tuple[str, ...]
    simulated_minutes_span: float
    features: dict[str, float]
    selected_token_ids: tuple[str, ...]
    score_bizarreness_0_100: float
    output_class: str = OUTPUT_CLASS_GENERATIVE
    visible_label: str = GENERATIVE_LABEL

    def context_sha256(self) -> str:
        """SHA-256 over canonical bytes of this projection."""
        return hashlib.sha256(dumps_canonical(self.model_dump())).hexdigest()

    def enforce_budget(self) -> None:
        """Refuse oversized projections instead of silently truncating."""
        rendered = len(self.model_dump_json())
        if rendered > _MAX_CONTEXT_CHARS:
            msg = f"minimized context {rendered} chars exceeds budget {_MAX_CONTEXT_CHARS}"
            raise ContextBudgetExceededError(msg)


def minimize_context(context: Any, *, max_tokens: int = 12) -> MinimizedContext:
    """Project a DreamContext onto the provider-visible allowlist."""
    token_ids: list[str] = []
    for segment in context.segments:
        for node_id in segment.selected_node_ids:
            if node_id not in token_ids:
                token_ids.append(node_id)
    stage_labels = []
    for segment in context.segments:
        if segment.stage not in stage_labels:
            stage_labels.append(segment.stage)
    span = context.total_ticks * 30.0 / 60.0  # documented default epoch basis
    return MinimizedContext(
        run_id=context.run_id,
        stage_labels=tuple(stage_labels),
        simulated_minutes_span=span,
        features={
            "scene_discontinuity": context.features.scene_discontinuity,
            "entity_incongruity": context.features.entity_incongruity,
            "causal_implausibility": context.features.causal_implausibility,
            "temporal_distortion": context.features.temporal_distortion,
            "identity_instability": context.features.identity_instability,
            "memory_blending_entropy": context.features.memory_blending_entropy,
        },
        selected_token_ids=tuple(token_ids[:max_tokens]),
        score_bizarreness_0_100=context.score_bizarreness_0_100,
    )


class NarrativeRequest(BaseModel):
    """Validated request envelope (schema hash recorded by providers)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimized_context: MinimizedContext
    style: str = Field(default="plain", pattern=r"^[a-z]{3,16}$")


class NarrativeResponse(BaseModel):
    """Validated response with provenance metadata (no raw payload storage)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    adapter_version: str
    model: str
    request_schema_hash: str
    prompt_template_hash: str
    context_sha256: str
    response_sha256: str
    decoding: str
    seed_support_declared: bool
    egress_classification: str
    failure_status: str = "none"
    output_class: str = OUTPUT_CLASS_GENERATIVE
    visible_label: str = GENERATIVE_LABEL


class NarrativeProvider(Protocol):
    """Typed protocol all narrative providers must satisfy."""

    def name(self) -> str:
        """Provider identifier recorded in provenance."""
        ...

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        """Render one validated response from one validated request."""
        ...


# --- MockNarrativeProvider --------------------------------------------------

_TEMPLATES: dict[str, str] = {
    "plain": (
        "Simulated episode sequence: {stages}. "
        "Selected synthetic tokens: {tokens}. "
        "Bizarreness proxy {score}/100 under declared weights. "
        "This is a generated interpretation of a simulation — not a report of "
        "an actual dream, and not a measurement."
    ),
    "poetic": (
        "Tokens drift — {tokens} — through {stages}; "
        "the weighted index rests at {score}. Rendered fiction about a "
        "simulated night, never a measurement or an inference."
    ),
}

_REQUEST_SCHEMA_HASH = hashlib.sha256(
    dumps_canonical(NarrativeRequest.model_json_schema()),
).hexdigest()
_TEMPLATE_HASHES = {
    style: hashlib.sha256(template.encode("utf-8")).hexdigest()
    for style, template in _TEMPLATES.items()
}


class MockNarrativeProvider:
    """Offline deterministic template renderer (mandatory default provider).

    Deterministic given identical requests: no clock, no RNG, no I/O. Fails
    closed on unknown styles or oversized contexts.
    """

    ADAPTER_VERSION = "mock-v1"

    def __init__(self, *, allowed_styles: tuple[str, ...] = ("plain", "poetic")) -> None:
        """Freeze the style allowlist (request-time validation)."""
        unknown = [style for style in allowed_styles if style not in _TEMPLATES]
        if unknown:
            msg = f"unknown styles in allowlist: {unknown}"
            raise ValueError(msg)
        self._allowed_styles = tuple(allowed_styles)

    def name(self) -> str:
        """Provider identifier."""
        return "mock"

    def _validate_style(self, style: str) -> str:
        if style not in self._allowed_styles:
            msg = f"style {style!r} outside provider allowlist {self._allowed_styles}"
            raise ProviderConfigError(msg)
        return style

    @staticmethod
    def _sanitize(text: str) -> str:
        """Defense-in-depth strip of control characters (allowlist logging)."""
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        """Render deterministically from the minimized projection."""
        style = self._validate_style(request.style)
        context = request.minimized_context
        context.enforce_budget()
        template = _TEMPLATES[style]
        text = template.format(
            stages=", ".join(context.stage_labels) or "(no segments)",
            tokens=", ".join(context.selected_token_ids) or "(none)",
            score=f"{context.score_bizarreness_0_100:.1f}",
        )
        text = self._sanitize(text)
        return NarrativeResponse(
            text=text,
            provider="mock",
            adapter_version=self.ADAPTER_VERSION,
            model="deterministic-template",
            request_schema_hash=_REQUEST_SCHEMA_HASH,
            prompt_template_hash=_TEMPLATE_HASHES[style],
            context_sha256=context.context_sha256(),
            response_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            decoding="template",
            seed_support_declared=False,
            egress_classification="local_offline",
            failure_status="none",
        )
