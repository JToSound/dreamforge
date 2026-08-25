"""Streaming (SSE) and tool-use adapter tests — offline scripted transports."""

from __future__ import annotations

import json

import pytest

from dreamforge.integrations.errors import ProviderResponseError
from dreamforge.integrations.streaming import (
    stream_anthropic_compat,
    stream_openai_compat,
)
from dreamforge.integrations.transport import HttpResponse


def sse_body(frames: list[dict | str]) -> bytes:
    parts = []
    for frame in frames:
        if isinstance(frame, str):
            parts.append(f"data: {frame}\n\n".encode())
        else:
            parts.append(f"data: {json.dumps(frame)}\n\n".encode())
    return b"".join(parts)


class FakeTransport:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self.body = body
        self.last_payload: dict | None = None

    def post_json(self, url, *, headers, payload, timeout_seconds):
        self.last_payload = payload
        return HttpResponse(status=self.status, body=self.body)


OPENAI_FRAMES = [
    {"choices": [{"delta": {"role": "assistant"}}]},
    {"choices": [{"delta": {"content": "Hello "}}]},
    {"choices": [{"delta": {"content": "simulated world."}}]},
    "[DONE]",
]

ANTHROPIC_FRAMES = [
    {"type": "message_start"},
    {"type": "content_block_start", "content_block": {"type": "text"}},
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Fictional "}},
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "night report."}},
    {"type": "content_block_stop"},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
]


class TestOpenAIStreaming:
    def test_stream_flag_sent_and_text_aggregated(self) -> None:
        transport = FakeTransport(body=sse_body(OPENAI_FRAMES))
        result = stream_openai_compat(
            transport=transport,
            url="http://127.0.0.1:9/v1/chat/completions",
            headers={},
            payload={"model": "m", "messages": []},
            timeout_seconds=5,
        )
        assert transport.last_payload["stream"] is True
        assert result.text == "Hello simulated world."
        assert result.chunk_count == 2
        assert len(result.response_sha256) == 64

    def test_on_chunk_callback_receives_incremental_pieces(self) -> None:
        seen: list[str] = []
        transport = FakeTransport(body=sse_body(OPENAI_FRAMES))
        stream_openai_compat(
            transport=transport,
            url="u",
            headers={},
            payload={},
            timeout_seconds=5,
            on_chunk=seen.append,
        )
        assert seen == ["Hello ", "simulated world."]

    def test_tool_call_deltas_surfaced(self) -> None:
        call = {"index": 0, "id": "call_1", "function": {"name": "noop"}}
        frames = [{"choices": [{"delta": {"tool_calls": [call]}}]}]
        transport = FakeTransport(body=sse_body(frames))
        result = stream_openai_compat(
            transport=transport,
            url="u",
            headers={},
            payload={},
            timeout_seconds=5,
        )
        assert result.tool_calls[0]["id"] == "call_1"

    def test_malformed_frame_redacted(self) -> None:
        transport = FakeTransport(body=b"data: <not-json>\n\n")
        with pytest.raises(ProviderResponseError) as excinfo:
            stream_openai_compat(
                transport=transport,
                url="u",
                headers={},
                payload={},
                timeout_seconds=5,
            )
        assert excinfo.value.code == "stream_frame_invalid"
        assert "<not-json>" not in excinfo.value.detail

    def test_non_200_redacted(self) -> None:
        transport = FakeTransport(status=503, body=b'{"e":"overloaded"}')
        with pytest.raises(ProviderResponseError) as excinfo:
            stream_openai_compat(
                transport=transport,
                url="u",
                headers={},
                payload={},
                timeout_seconds=5,
            )
        assert excinfo.value.code == "http_error"


class TestAnthropicStreaming:
    def test_stream_flag_and_text_aggregated(self) -> None:
        transport = FakeTransport(body=sse_body(ANTHROPIC_FRAMES))
        result = stream_anthropic_compat(
            transport=transport,
            url="http://127.0.0.1:9/v1/messages",
            headers={},
            payload={"model": "m", "max_tokens": 8},
            timeout_seconds=5,
        )
        assert transport.last_payload["stream"] is True
        assert result.text == "Fictional night report."
        assert result.stop_reason == "end_turn"

    def test_tool_use_block_surfaced(self) -> None:
        block = {"type": "tool_use", "id": "tu_1", "name": "lookup"}
        frames = [
            {"type": "content_block_start", "content_block": block},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        ]
        transport = FakeTransport(body=sse_body(frames))
        result = stream_anthropic_compat(
            transport=transport,
            url="u",
            headers={},
            payload={},
            timeout_seconds=5,
        )
        assert result.tool_use_blocks[0]["name"] == "lookup"
        assert result.stop_reason == "tool_use"

    def test_empty_stream_yields_empty_text_with_hash(self) -> None:
        transport = FakeTransport(body=sse_body([]))
        result = stream_anthropic_compat(
            transport=transport,
            url="u",
            headers={},
            payload={},
            timeout_seconds=5,
        )
        assert result.text == ""
        assert result.response_sha256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
