"""Streaming (SSE) and tool-use support for narrative adapters (ADR 0005+).

Scope, honestly stated:

- **OpenAI-compatible**: ``stream=True`` chat completions via SSE chunks
  (``choices[].delta.content``); tool-call deltas are surfaced raw.
- **Anthropic-native**: ``stream: true`` messages API events
  (``content_block_delta`` with ``text_delta``); ``tool_use`` blocks surfaced.
- Streaming callbacks receive incremental text; nothing is buffered longer
  than one chunk. The final aggregated text is hash-recorded like any other
  response. Tool-use requests are STRUCTURAL only - DreamForge defines no
  tools and never instructs the model to act; callers own the tool loop.

All transport stays behind :class:`HttpTransport` so everything is tested
offline with scripted fakes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dreamforge.integrations.retry import redacted_error
from dreamforge.integrations.transport import HttpTransport, TransportError

ChunkCallback = Callable[[str], None]

_SSE_DONE = object()


def _iter_sse_events(body: bytes) -> list[dict[str, Any]]:
    """Parse an SSE byte stream into data-event JSON objects.

    Raises a redacted error on malformed frames; the raw body is never
    included in the exception.
    """
    events: list[dict[str, Any]] = []
    for frame in body.split(b"\n\n"):
        for line in frame.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            payload = line[len(b"data:") :].strip()
            if not payload or payload == b"[DONE]":
                continue
            try:
                events.append(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise redacted_error("stream_frame_invalid", 200, payload) from None
    return events


class StreamedNarrative(BaseModel):
    """Aggregated result of one streamed completion."""

    model_config = ConfigDict(frozen=True)

    text: str
    chunk_count: int
    tool_calls: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    response_sha256: str


def stream_openai_compat(
    *,
    transport: HttpTransport,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: float,
    on_chunk: ChunkCallback | None = None,
) -> StreamedNarrative:
    """POST with stream=true and aggregate SSE deltas into text."""
    wire_payload = dict(payload)
    wire_payload["stream"] = True
    try:
        response = transport.post_json(
            url,
            headers=headers,
            payload=wire_payload,
            timeout_seconds=timeout_seconds,
        )
    except TransportError:
        raise
    if response.status != 200:
        raise redacted_error("http_error", response.status, response.body)

    parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    chunks = 0
    for event in _iter_sse_events(response.body):
        choices = event.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if isinstance(piece, str):
            parts.append(piece)
            chunks += 1
            if on_chunk is not None:
                on_chunk(piece)
        calls = delta.get("tool_calls")
        if isinstance(calls, list):
            tool_calls.extend(call for call in calls if isinstance(call, dict))
    text = "".join(parts)
    return StreamedNarrative(
        text=text,
        chunk_count=chunks,
        tool_calls=tuple(tool_calls),
        response_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


class AnthropicStreamResult(BaseModel):
    """Aggregated result of one streamed Anthropic messages call."""

    model_config = ConfigDict(frozen=True)

    text: str
    event_count: int
    tool_use_blocks: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    stop_reason: str = ""
    response_sha256: str


def stream_anthropic_compat(
    *,
    transport: HttpTransport,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: float,
    on_chunk: ChunkCallback | None = None,
) -> AnthropicStreamResult:
    """POST with stream:true and aggregate content_block_delta texts."""
    wire_payload = dict(payload)
    wire_payload["stream"] = True
    try:
        response = transport.post_json(
            url,
            headers=headers,
            payload=wire_payload,
            timeout_seconds=timeout_seconds,
        )
    except TransportError:
        raise
    if response.status != 200:
        raise redacted_error("http_error", response.status, response.body)

    parts: list[str] = []
    tool_blocks: list[dict[str, Any]] = []
    events_seen = 0
    stop_reason = ""
    for event in _iter_sse_events(response.body):
        events_seen += 1
        etype = event.get("type")
        if etype == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                piece = str(delta.get("text", ""))
                parts.append(piece)
                if on_chunk is not None:
                    on_chunk(piece)
        elif etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                tool_blocks.append(block)
        elif etype == "message_delta":
            delta = event.get("delta") or {}
            stop_reason = str(delta.get("stop_reason", stop_reason))
    text = "".join(parts)
    return AnthropicStreamResult(
        text=text,
        event_count=events_seen,
        tool_use_blocks=tuple(tool_blocks),
        stop_reason=stop_reason,
        response_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
