"""Shared typed errors and egress classification for integrations (ADR 0005)."""

from __future__ import annotations

from dreamforge.core.providers.narrative import ProviderConfigError


class ProviderResponseError(ProviderConfigError, Exception):  # noqa: N818
    """Typed, redacted provider failure: code + detail only.

    Detail carries at most a status code and a response digest - never raw
    response bodies or provider payloads.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ProviderExhaustedError(ProviderResponseError):
    """All bounded attempts failed; details remain redacted."""

    def __init__(self, message: str) -> None:
        super().__init__("attempts_exhausted", message)


def classify_egress(base_url: str) -> str:
    """Honest egress label from the configured endpoint URL."""
    loopback_hosts = ("127.0.0.1", "localhost", "[::1]", "0.0.0.0")
    return (
        "network_loopback" if any(host in base_url for host in loopback_hosts) else "network_remote"
    )
