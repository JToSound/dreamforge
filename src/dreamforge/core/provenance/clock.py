"""Clock port.

Timestamps enter the system exclusively through this protocol. They never
affect state transitions, event IDs, deterministic payload hashes, or the
core trace hash (MASTER_PROMPT.md section 4.2, ADR 0002).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Source of timezone-aware provenance timestamps."""

    def now(self) -> datetime:
        """Return the current provenance instant (timezone-aware)."""
        ...


class FixedClock:
    """Deterministic clock returning one fixed UTC instant.

    Used by tests and deterministic demos so that provenance timestamps are
    stable and can never perturb hashing.
    """

    def __init__(self, instant: datetime) -> None:
        """Store ``instant``, coercing naive datetimes is refused."""
        if instant.tzinfo is None:
            msg = "FixedClock requires a timezone-aware datetime"
            raise ValueError(msg)
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        """Return the fixed instant in UTC."""
        return self._instant
