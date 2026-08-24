"""Anthropic-native messages-API narrative provider adapter (ADR 0005).

Same contract as the OpenAI-compat adapter: frozen caller-supplied config,
explicit construction, allowlisted projection only, strict response schema,
bounded retries via the shared vetted path, redacted typed errors, honest
egress classification. Wire differences: ``/v1/messages`` endpoint,
``x-api-key`` + ``anthropic-version`` headers, system prompt as a top-level
field, REQUIRED ``max_tokens``, content-block text extraction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dreamforge.core.providers.narrative import (
    GENERATIVE_LABEL,
    OUTPUT_CLASS_GENERATIVE,
    NarrativeRequest,
    NarrativeResponse,
    ProviderConfigError,
)
from dreamforge.integrations.errors import classify_egress
from dreamforge.integrations.openai_compat import _SYSTEM_PROMPT
from dreamforge.integrations.retry import redacted_error, send_with_retry
from dreamforge.integrations.transport import HttpTransport

ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 512
_CLOSING_LINE = "Generated interpretation - not a dream measurement or inference."
_STYLE_PHRASES = {"plain": "plain factual prose", "poetic": "poetic prose"}

_REQUEST_SCHEMA_HASH = hashlib.sha256(
    json.dumps(NarrativeRequest.model_json_schema(), sort_keys=True).encode("utf-8"),
).hexdigest()


class AnthropicCompatConfig(BaseModel):
    """Frozen adapter configuration supplied explicitly by the caller."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(pattern=r"^https?://")
    api_key: str = ""
    model: str = Field(min_length=1)
    max_tokens: int = Field(default=_DEFAULT_MAX_TOKENS, ge=16, le=4096)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=30)


class _WireMessages(BaseModel):
    """Subset of the messages-API response we consume (content blocks)."""

    content: list[dict[str, Any]] = Field(min_length=1)


class AnthropicCompatProvider:
    """Anthropic messages-API provider behind NarrativeProvider."""

    ADAPTER_VERSION = "anthropic-compat-v1"

    def __init__(self, config: AnthropicCompatConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport
        if not config.model.strip():
            raise ProviderConfigError("model must be non-empty")

    def name(self) -> str:
        """Provider identifier recorded in provenance."""
        return f"anthropic-compat({self._config.base_url})"

    # -- request assembly -----------------------------------------------------

    @staticmethod
    def _build_prompt(request: NarrativeRequest) -> str:
        context = request.minimized_context
        style_phrase = _STYLE_PHRASES.get(request.style, request.style)
        return (
            f"Simulated night {context.run_id}: stages "
            f"{', '.join(context.stage_labels)}; synthetic tokens "
            f"{', '.join(context.selected_token_ids)}; bizarreness index "
            f"{context.score_bizarreness_0_100:.1f}/100 (declared weights). "
            f"Write a short fictional report in {style_phrase}; include no "
            f"claims about real dreams or measurements. End with the exact "
            f"line: {_CLOSING_LINE}"
        )

    def _payload(self, user_message: str) -> dict[str, object]:
        return {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": 0,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._config.api_key:
            headers["x-api-key"] = self._config.api_key
        return headers

    # -- protocol --------------------------------------------------------------

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        """Render one validated response; fail closed on any fault."""
        context = request.minimized_context
        context.enforce_budget()  # BEFORE anything touches the network

        url = self._config.base_url.rstrip("/") + "/v1/messages"
        response = send_with_retry(
            transport=self._transport,
            url=url,
            headers=self._headers(),
            payload=self._payload(self._build_prompt(request)),
            timeout_seconds=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
            backoff_seconds=self._config.retry_backoff_seconds,
        )
        if response.status != 200:
            raise redacted_error("http_error", response.status, response.body)
        return _parse_messages_success(
            response.body,
            request,
            provider_name=self.name(),
            adapter_version=self.ADAPTER_VERSION,
            model=self._config.model,
            base_url=self._config.base_url,
        )


def _parse_messages_success(
    body: bytes,
    request: NarrativeRequest,
    *,
    provider_name: str,
    adapter_version: str,
    model: str,
    base_url: str,
) -> NarrativeResponse:
    """Validate a 200 body (content blocks) and build the response."""
    try:
        wire = _WireMessages.model_validate(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise redacted_error("response_schema_invalid", 200, body) from None
    parts = [str(block.get("text", "")) for block in wire.content if block.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise redacted_error("empty_completion", 200, body)
    context = request.minimized_context
    template_bundle = f"{_SYSTEM_PROMPT}|{_CLOSING_LINE}|{ANTHROPIC_VERSION}"
    return NarrativeResponse(
        text=text,
        provider=provider_name,
        adapter_version=adapter_version,
        model=model,
        request_schema_hash=_REQUEST_SCHEMA_HASH,
        prompt_template_hash=hashlib.sha256(template_bundle.encode("utf-8")).hexdigest(),
        context_sha256=context.context_sha256(),
        response_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        decoding="api:temperature=0",
        seed_support_declared=False,
        egress_classification=classify_egress(base_url),
        failure_status="none",
        output_class=OUTPUT_CLASS_GENERATIVE,
        visible_label=GENERATIVE_LABEL,
    )
