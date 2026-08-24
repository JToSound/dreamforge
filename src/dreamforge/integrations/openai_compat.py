"""OpenAI-compatible narrative provider adapter (ADR 0005).

Works against any ``/chat/completions``-style endpoint, including Ollama's
``/v1`` compatibility mode. Constructed EXPLICITLY with a frozen config —
never enabled by default, never reads environment variables. All contract
properties (schema validation, timeouts, bounded retries, redacted errors)
are exercised offline via injected fake transports.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dreamforge.core.providers.narrative import (
    GENERATIVE_LABEL,
    OUTPUT_CLASS_GENERATIVE,
    NarrativeRequest,
    NarrativeResponse,
    ProviderConfigError,
)
from dreamforge.integrations.transport import HttpTransport, TransportError

_SYSTEM_PROMPT = (
    "You write short fictional dream-report prose about a SIMULATED sleep "
    "episode. You receive structured simulation outputs only. You must never "
    "claim to describe a real person's dream, and never imply measurement of "
    "any brain or mind."
)

_PROMPT_TEMPLATE_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
_REQUEST_SCHEMA_HASH = hashlib.sha256(
    json.dumps(NarrativeRequest.model_json_schema(), sort_keys=True).encode("utf-8"),
).hexdigest()

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatConfig(BaseModel):
    """Frozen adapter configuration supplied explicitly by the caller."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(pattern=r"^https?://")
    api_key: str = ""
    model: str = Field(min_length=1)
    style: str = "plain"
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    classify_loopback: bool = True


class _WireResponse(BaseModel):
    """Strict schema for the subset of the wire format we consume.

    ``choices`` stays ``list[dict]`` (NOT a nested model) so unknown top-level
    fields of each choice don't trip extra="forbid" — we validate the one
    path we consume and ignore the rest deliberately.
    """

    choices: list[dict[str, Any]] = Field(min_length=1)


class OpenAICompatProvider:
    """Networked provider behind the same NarrativeProvider protocol."""

    ADAPTER_VERSION = "openai-compat-v1"

    def __init__(self, config: OpenAICompatConfig, transport: HttpTransport) -> None:
        self._config = config
        self._transport = transport
        if not config.model.strip():
            raise ProviderConfigError("model must be non-empty")

    def name(self) -> str:
        """Provider identifier recorded in provenance."""
        return f"openai-compat({self._config.base_url})"

    # -- request assembly -----------------------------------------------------

    def _build_prompt(self, request: NarrativeRequest) -> str:
        context = request.minimized_context
        return (
            f"Simulated night {context.run_id}: stages "
            f"{', '.join(context.stage_labels)}; synthetic tokens "
            f"{', '.join(context.selected_token_ids)}; bizarreness index "
            f"{context.score_bizarreness_0_100:.1f}/100 (declared weights). "
            "Write a short fictional report in the requested style; include "
            "no claims about real dreams or measurements."
        )

    def _payload(self, request: NarrativeRequest, user_message: str) -> dict[str, object]:
        return {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
                {
                    "role": "system",
                    "content": (
                        "Style: " + request.style + ". End with: Generated interpretation - not a "
                        "dream measurement or inference."
                    ),
                },
            ],
            "temperature": 0,
        }

    # -- error helpers ---------------------------------------------------------

    @staticmethod
    def _redacted_error(code: str, status: int | None, body: bytes | None) -> ProviderResponseError:
        digest = hashlib.sha256(body or b"").hexdigest()[:16]
        detail = f"status={status if status is not None else 'none'} sha256={digest}"
        return ProviderResponseError(code, detail)

    # -- protocol --------------------------------------------------------------

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        """Render one validated response; fail closed on any fault."""
        context = request.minimized_context
        context.enforce_budget()  # BEFORE anything touches the network
        prompt = self._build_prompt(request)
        payload = self._payload(request, prompt)

        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        url = self._config.base_url.rstrip("/") + "/chat/completions"
        attempts_allowed = self._config.max_retries + 1
        last_code = "unknown"
        last_detail = ""

        for attempt in range(attempts_allowed):
            try:
                response = self._transport.post_json(
                    url,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=self._config.timeout_seconds,
                )
            except TransportError:
                # Transport failures are already redacted at the seam; the
                # attempt simply counts toward the bounded retry budget.
                last_code, last_detail = "transport_error", "redacted"
            else:
                if response.status == 200:
                    return self._parse_success(response.body, request, attempt)
                if response.status in _RETRYABLE_STATUS:
                    last_code, last_detail = "retryable_status", f"status={response.status}"
                else:
                    raise self._redacted_error("http_error", response.status, response.body)
            if attempt < attempts_allowed - 1:
                if self._config.retry_backoff_seconds > 0:
                    time.sleep(self._config.retry_backoff_seconds)

        msg = f"provider failed after {attempts_allowed} attempt(s): {last_code} {last_detail}"
        raise ProviderExhaustedError(msg)

    def _parse_success(
        self,
        body: bytes,
        request: NarrativeRequest,
        attempts_used: int,
    ) -> NarrativeResponse:
        del attempts_used
        try:
            wire = _WireResponse.model_validate(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            raise self._redacted_error("response_schema_invalid", 200, body) from None
        message = wire.choices[0].get("message") or {}
        text = str(message.get("content", "")).strip()
        if not text:
            raise self._redacted_error("empty_completion", 200, body)
        context = request.minimized_context
        egress = (
            "network_loopback"
            if self._config.classify_loopback
            and any(
                host in self._config.base_url
                for host in ("127.0.0.1", "localhost", "[::1]", "0.0.0.0")
            )
            else "network_remote"
        )
        return NarrativeResponse(
            text=text,
            provider=self.name(),
            adapter_version=self.ADAPTER_VERSION,
            model=self._config.model,
            request_schema_hash=_REQUEST_SCHEMA_HASH,
            prompt_template_hash=_PROMPT_TEMPLATE_HASH,
            context_sha256=context.context_sha256(),
            response_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            decoding="api:temperature=0",
            seed_support_declared=False,
            egress_classification=egress,
            failure_status="none",
            output_class=OUTPUT_CLASS_GENERATIVE,
            visible_label=GENERATIVE_LABEL,
        )


class ProviderResponseError(ProviderConfigError.__mro__[1], Exception):  # noqa: N818
    """Typed, redacted provider failure: code + detail only."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ProviderExhaustedError(ProviderResponseError):
    """All bounded attempts failed; details remain redacted."""

    def __init__(self, message: str) -> None:
        super().__init__("attempts_exhausted", message)
