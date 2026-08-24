"""HTTP transports for optional narrative providers (ADR 0005).

``HttpTransport`` is the seam that makes every networked provider offline-
testable: production code injects :class:`UrllibTransport` (stdlib only),
tests inject scripted fakes. Transports own timeouts and return raw status +
body; they never interpret payloads.
"""

from __future__ import annotations

import json as _json
import urllib.error
import urllib.request
from typing import Protocol

from dreamforge.core.providers.narrative import ProviderError


class TransportError(ProviderError):
    """A transport-level failure (timeout, DNS, refused connection)."""


class HttpResponse:
    """Raw response envelope; body bytes are NOT logged anywhere."""

    __slots__ = ("status", "body")

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body


class HttpTransport(Protocol):
    """Minimal blocking HTTP surface providers depend on."""

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> HttpResponse:
        """POST a JSON object, returning status + raw body bytes."""
        ...


class UrllibTransport:
    """Stdlib transport with strict per-attempt timeouts. No retries here."""

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> HttpResponse:
        data = _json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return HttpResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as exc:
            # HTTP errors still carry a response body worth validating.
            return HttpResponse(status=exc.code, body=exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            msg = f"transport failure ({type(exc).__name__}); details redacted"
            raise TransportError(msg) from None
