"""Shared bounded-retry send path for narrative adapters (ADR 0005).

One vetted implementation both adapters use: per-attempt timeout owned by the
transport, retries only on transient outcomes (transport failures and
retryable HTTP statuses), injectable backoff sleep for deterministic tests,
typed redacted failure after the bound.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from dreamforge.integrations.errors import (
    ProviderExhaustedError,
    ProviderResponseError,
)
from dreamforge.integrations.transport import HttpResponse, HttpTransport, TransportError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


def send_with_retry(
    *,
    transport: HttpTransport,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: float,
    max_retries: int,
    backoff_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """POST with bounded retries; returns the final non-retryable response.

    Raises :class:`ProviderExhaustedError` when every attempt was transient;
    never retries non-retryable statuses (they return immediately).
    """
    attempts_allowed = max_retries + 1
    last_code = "unknown"
    last_detail = ""

    for attempt in range(attempts_allowed):
        try:
            response = transport.post_json(
                url,
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except TransportError:
            # Already redacted at the transport seam; counts toward the bound.
            last_code, last_detail = "transport_error", "redacted"
        else:
            if response.status not in _RETRYABLE_STATUS:
                return response
            last_code = "retryable_status"
            last_detail = f"status={response.status}"
        if attempt < attempts_allowed - 1 and backoff_seconds > 0:
            sleeper(backoff_seconds)

    msg = f"provider failed after {attempts_allowed} attempt(s): {last_code} {last_detail}"
    raise ProviderExhaustedError(msg)


def redacted_error(code: str, status: int | None, body: bytes | None) -> ProviderResponseError:
    """Build a redacted error naming status + body digest only."""
    import hashlib

    digest = hashlib.sha256(body or b"").hexdigest()[:16]
    detail = f"status={status if status is not None else 'none'} sha256={digest}"
    return ProviderResponseError(code, detail)
