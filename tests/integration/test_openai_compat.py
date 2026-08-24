"""Offline contract tests for the OpenAI-compat adapter (ADR 0005)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dreamforge.core.providers.narrative import (
    ContextBudgetExceededError,
    MinimizedContext,
    NarrativeRequest,
)
from dreamforge.integrations.openai_compat import (
    OpenAICompatConfig,
    OpenAICompatProvider,
    ProviderExhaustedError,
    ProviderResponseError,
)
from dreamforge.integrations.transport import TransportError


def make_context() -> MinimizedContext:
    return MinimizedContext(
        run_id="adapter-test-1",
        stage_labels=("N2", "REM"),
        simulated_minutes_span=120.0,
        features={"scene_discontinuity": 0.5},
        selected_token_ids=("tok_01", "tok_02"),
        score_bizarreness_0_100=42.0,
    )


def make_request() -> NarrativeRequest:
    return NarrativeRequest(minimized_context=make_context(), style="plain")


class FakeTransport:
    """Scripted transport: returns queued responses; records every call."""

    def __init__(self, script: list) -> None:
        # each entry: ("response", status, body_dict_or_bytes) | ("raise", exc)
        self.script = list(script)
        self.calls: list[dict] = []

    def post_json(self, url, *, headers, payload, timeout_seconds):
        self.calls.append(
            {"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout_seconds},
        )
        if not self.script:
            raise AssertionError("script exhausted")
        entry = self.script.pop(0)
        kind = entry[0]
        if kind == "raise":
            raise entry[1]
        _kind, status, body = entry
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        from dreamforge.integrations.transport import HttpResponse

        return HttpResponse(status=status, body=raw)


def completion_body(text="A fictional simulated-night report.") -> dict:
    return {
        "id": "x",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }


def make_provider(transport: FakeTransport, **overrides):
    config = OpenAICompatConfig(
        base_url=overrides.pop("base_url", "http://127.0.0.1:11434/v1"),
        api_key=overrides.pop("api_key", ""),
        model=overrides.pop("model", "llama3.2:3b"),
        timeout_seconds=overrides.pop("timeout_seconds", 5.0),
        max_retries=overrides.pop("max_retries", 2),
        retry_backoff_seconds=overrides.pop("retry_backoff_seconds", 0.0),
        **overrides,
    )
    return OpenAICompatProvider(config, transport)


class TestSuccess:
    def test_success_loopback_classification_and_hashes(self) -> None:
        transport = FakeTransport([("response", 200, completion_body())])
        response = make_provider(transport).generate(make_request())
        assert response.egress_classification == "network_loopback"
        assert response.failure_status == "none"
        assert len(response.response_sha256) == 64
        assert response.request_schema_hash and response.prompt_template_hash
        assert response.context_sha256
        assert response.output_class == "generative_interpretation"
        assert len(transport.calls) == 1

    def test_remote_url_classified_remote(self) -> None:
        transport = FakeTransport([("response", 200, completion_body())])
        provider = make_provider(transport, base_url="https://api.example.com/v1")
        response = provider.generate(make_request())
        assert response.egress_classification == "network_remote"

    def test_api_key_sent_when_configured(self) -> None:
        transport = FakeTransport([("response", 200, completion_body())])
        provider = make_provider(transport, api_key="test-key-not-a-secret")
        provider.generate(make_request())
        assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-key-not-a-secret"

    def test_no_auth_header_when_key_absent(self) -> None:
        transport = FakeTransport([("response", 200, completion_body())])
        make_provider(transport).generate(make_request())
        assert "Authorization" not in transport.calls[0]["headers"]


class TestRetries:
    def test_transient_then_success_within_bounds(self) -> None:
        transport = FakeTransport(
            [
                ("response", 503, {"error": "overloaded"}),
                ("response", 429, {"error": "slow down"}),
                ("response", 200, completion_body()),
            ]
        )
        response = make_provider(transport).generate(make_request())
        assert response.text.startswith("A fictional")
        assert len(transport.calls) == 3

    def test_exhaustion_raises_typed_after_bound(self) -> None:
        transport = FakeTransport([("response", 500, {}) for _ in range(5)])
        with pytest.raises(ProviderExhaustedError) as excinfo:
            make_provider(transport, max_retries=2).generate(make_request())
        assert excinfo.value.code == "attempts_exhausted"
        assert len(transport.calls) == 3  # 1 + max_retries exactly

    def test_transport_error_counts_toward_retry_bound(self) -> None:
        transport = FakeTransport(
            [
                ("raise", TransportError("transport failure; details redacted")),
                ("raise", TransportError("transport failure; details redacted")),
                ("raise", TransportError("transport failure; details redacted")),
            ]
        )
        with pytest.raises(ProviderExhaustedError):
            make_provider(transport, max_retries=2).generate(make_request())
        assert len(transport.calls) == 3

    def test_non_retryable_status_fails_immediately(self) -> None:
        transport = FakeTransport([("response", 401, {"error": "bad key"})])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "http_error"
        detail = excinfo.value.detail
        assert "status=401" in detail and "sha256=" in detail
        assert "bad key" not in detail  # redacted
        assert len(transport.calls) == 1


class TestRedaction:
    def test_malformed_json_redacted_with_hash_only(self) -> None:
        transport = FakeTransport([("response", 200, b"<html>not json</html>")])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "response_schema_invalid"
        assert "not json" not in excinfo.value.detail

    def test_wrong_shape_redacted(self) -> None:
        transport = FakeTransport([("response", 200, {"choices": []})])
        with pytest.raises(ProviderResponseError):
            make_provider(transport).generate(make_request())

    def test_empty_completion_refused(self) -> None:
        transport = FakeTransport([("response", 200, completion_body(text=""))])
        with pytest.raises(ProviderResponseError) as excinfo:
            make_provider(transport).generate(make_request())
        assert excinfo.value.code == "empty_completion"


class TestBudgetAndDefaults:
    def test_budget_violation_makes_zero_requests(self) -> None:
        transport = FakeTransport([])
        huge_context = MinimizedContext(
            run_id="budget-bomb",
            stage_labels=("N2" * 300,),
            simulated_minutes_span=1.0,
            features={},
            selected_token_ids=tuple(f"tok_{i:04d}" for i in range(400)),
            score_bizarreness_0_100=1.0,
        )
        request = NarrativeRequest(minimized_context=huge_context)
        with pytest.raises(ContextBudgetExceededError):
            make_provider(transport).generate(request)
        assert transport.calls == []

    def test_disabled_by_default_nothing_constructs_at_import(self) -> None:
        """The demo must never pull the networked adapters in.

        Checked in a clean subprocess because this test module itself (and
        pytest's collection) legitimately imports the integration package.
        (The dashboard is streamlit-gated and covered by its own tests.)
        """
        import subprocess
        import sys

        repo_src = str(Path(__file__).resolve().parents[2] / "src")
        probe = (
            "import sys;\n"
            f"sys.path.insert(0, {repo_src!r});\n"
            "import dreamforge.demo;\n"
            "hits = [m for m in sys.modules if m.startswith('dreamforge.integrations')];\n"
            "print('PULLED:' + ','.join(hits) if hits else 'NOT_PULLED')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert "NOT_PULLED" in completed.stdout, completed.stdout + completed.stderr

    def test_frozen_config_immutable(self) -> None:
        config = OpenAICompatConfig(base_url="http://127.0.0.1:1/v1", model="m")
        with pytest.raises(Exception):  # noqa: B017,PT011 - pydantic ValidationError
            config.model = "other"
