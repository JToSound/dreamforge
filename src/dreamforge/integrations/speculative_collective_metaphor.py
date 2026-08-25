"""Speculative plugin placeholder - DISABLED and excluded from exports.

MASTER_PROMPT.md §5.5 requires ``plugins/speculative/collective_metaphor.py``
to stay disabled and excluded from core exports, scientific claims, and
default installs. This module is the honest placeholder: importing it is
harmless, constructing it always refuses, and it participates in nothing.
"""

from __future__ import annotations


class CollectiveMetaphorDisabledError(RuntimeError):
    """Raised on any construction attempt - the plugin has no implementation."""


class CollectiveMetaphorPlugin:
    """Permanently disabled speculative surface (§5.5 non-goal)."""

    ENABLED = False
    _REFUSAL = (
        "collective_metaphor is a disabled speculative plugin "
        "(MASTER_PROMPT.md §5.5); it has no implementation and makes no claims"
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise CollectiveMetaphorDisabledError(self._REFUSAL)

    @staticmethod
    def status() -> str:
        return "disabled_by_spec: no implementation, excluded from exports/claims"
