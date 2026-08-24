"""Offline contract tests for the Anthropic-native adapter (ADR 0005)."""

from __future__ import annotations

import json

import pytest

from dreamforge.core.providers.narrative import (
    ContextBudgetExceededError,
    MinimizedContext,
    NarrativeRequest,
)
from dreamforge.integrations.anthropic_compat import (
    ANTHROPIC_VERSION,
    AnthropicCompatConfig,
    AnthropicCompatProvider,
)
from dreamforge.integrations.errors import ProviderExhaustedError, ProviderResponseError
from dreamforge.integrations.transport import HttpResponse, TransportError


def make_context() -> MinimizedContext:
    return MinimizedContext(
        run_id="anthropic-test-1",
        stage_labels=("N3", "REM"),
        simulated_minutes_span=90.0,
        features={"temporal_distortion": 0.4},
        selected_token_ids=("tok_05",),
        score_bizarreness_0_100=33.0,
    )


def make_request() -> NarrativeRequest:
    return NarrativeRequest(minimized_context=make_context(), style="poetic")


class FakeTransport:
    """Scripted transport: returns queued responses; records every call."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def post_json(self, url, *, headers, payload, timeout_seconds):
        self.calls.append(
            {"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout_seconds},
        )
        if not self.script:
            raise AssertionError("script exhausted")
        entry = self.script.pop(0)
        if entry[0] == "raise":
            raise entry[1]
        _kind, status, body = entry
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        return HttpResponse(status=status, body=raw)


def messages_body(text="A fictional simulated-night report.") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-3-5-haiku-latest",
        "stop_reason": "end_turn",
    }


def make_provider(transport: FakeTransport, **overrides):
    config = AnthropicCompatConfig(
        base_url=overrides.pop("base_url", "http://127.0.0.1:8080"),
        api_key=overrides.pop("api_key", ""),
        model=overrides.pop("model", "claude-3-5-haiku-latest"),
        max_tokens=overrides.pop("max_tokens", 256),
        timeout_seconds=overrides.pop("timeout_seconds", 5.0),
        max_retries=overrides.pop("max_retries", 2),
        retry_backoff_seconds=overrides.pop("retry_backoff_seconds", 0.0),
        **overrides,
    )
    return AnthropicCompatProvider(config, transport)


class TestWireShape:
    def test_url_headers_and_payload_shape(self) -> None:
        transport = FakeTransport([("response", 200, messages_body())])
        provider = make_provider(transport, api_key="sk-ant-test-not-a-secret")
        provider.generate(make_request())

        call = transport.calls[0]
        assert call["url"].endswith("/v1/messages")
        assert call["headers"]["x-api-key"] == "sk-ant-test-not-a-secret"
        assert call["headers"]["anthropic-version"] == ANTHROPIC_VERSION
        payload = call["payload"]
        # Messages-API requirements: system is top-level; max_tokens REQUIRED.
        assert "system" in payload and "max_tokens" in payload
        messages = payload["messages"]
        assert isinstance(messages, list) and len(messages) == 1
        assert messages[0]["role"] == "user"
        assert payload["temperature"] == 0
        prompt_text = str(messages[0]["content"])
        assert "Simulated night anthropic-test-1" in prompt_text
        assert "tok_05" in prompt_text  # allowlisted projection only

    def test_no_api_key_header_when_absent(self) -> None:
        transport = FakeTransport([("response", 200, messages_body())])
        make_provider(transport).generate(make_request())
        assert "x-api-key" not in transport.calls[0]["headers"]

    def test_max_tokens_from_config(self) -> None:
        transport = FakeTransport([("response", 200, messages_body())])
        make_provider(transport, max_tokens=64).generate(make_request())
        assert transport.calls[0]["payload"]["max_tokens"] == 64


class TestSuccessAndProvenance:
    def test_success_hashes_and_egress_loopback(self) -> None:
        transport = FakeTransport([("response", 200, messages_body())])
        response = make_provider(transport).generate(make_request())
        assert response.egress_classification == "network_loopback"
        assert response.failure_status == "none"
        assert len(response.response_sha256) == 64
        assert response.context_sha256
        assert response.output_class == "generative_interpretation"
        assert response.adapter_version == "anthropic-compat-v1"
        assert "claude" in response.model

    def test_remote_classification(self) -> None:
        transport = FakeTransport([("response", 200, messages_body())])
        provider = make_provider(transport, base_url="https://api.anthropic.com")
        response = provider.generate(make_request())
        assert response.egress_classification == "network_remote"

    def test_multi_block_text_concatenated(self) -> None:
        body = {
            "content": [
                {"type": "text", "text": "Part one. "},
                {"type": "tool_use", "id": "t1"},  # non-text block ignored
                {"type": "text", "text": "Part two."},
            ],
        }
        transport = FakeTransport([("response", 200, body)])
        response = make_provider(transport).generate(make_request())
        assert response.text == "Part one. Part two."


class TestFailures:
    def test_retry_then_success_within_bound(self) -> None:
        transport = FakeTransport(
            [
                ("response", 529, {}),  # Anthropic overloaded (non-standard code)
                ("response", 429, {}),
                ("response", 200, messages_body()),
            ]
        )
        response = make_provider(transport).generate(make_request())
        assert response.text.startswith("A fictional")
        assert len(transport.calls) == 3

    def test_exhaustion_after_exact_bound(self) -> None:
        script = [("response", 500, {}) for _ in range(6)]
        transport = FakeTransport(script)
        with pytest.raises(ProviderExhaustedError):
            make_provider(transport, max_retries=2).generate(make_request())
        assert len(transport.calls) == 3

    def test_transport_error_counts_toward_bound(self) -> None:
        redacted = TransportError("transport failure; details redacted")
        transport = FakeTransport([("raise", redacted)] * 3)
        with pytest.raises(ProviderExhaustedError):
            make_provider(transport, max_retries=2).generate(make_request())
        assert len(transport.calls) == 3

    def test_non_retryable_immediate_and_redacted(self) -> None:
        transport = FakeTransport([("response", 401, {"error": {"message": "invalid x-api-key"}})])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "http_error"
        assert "status=401" in excinfo.value.detail
        assert "invalid x-api-key" not in excinfo.value.detail
        assert len(transport.calls) == 1

    def test_malformed_body_redacted(self) -> None:
        transport = FakeTransport([("response", 200, b"<html>oops</html>")])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "response_schema_invalid"

    def test_empty_text_blocks_refused(self) -> None:
        transport = FakeTransport([("response", 200, {"content": [{"type": "text", "text": ""}]})])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "empty_completion"


class TestBudgetAndConfig:
    def test_budget_violation_zero_requests(self) -> None:
        transport = FakeTransport([])
        huge = MinimizedContext(
            run_id="budget-bomb-anthropic",
            stage_labels=tuple(),
            simulated_minutes_span=1.0,
            features={},
            selected_token_ids=tuple(f"tok_{i:04d}" for i in range(400)),
            score_bizarreness_0_100=1.0,
        )
        with pytest.raises(ContextBudgetExceededError):
            make_provider(transport).generate(NarrativeRequest(minimized_context=huge))
        assert transport.calls == []

    def test_frozen_config_immutable(self) -> None:
        config = AnthropicCompatConfig(base_url="http://127.0.0.1:9/v1", model="m")
        with pytest.raises(Exception):  # noqa: B017,PT011 - pydantic ValidationError
            config.model = "other"
