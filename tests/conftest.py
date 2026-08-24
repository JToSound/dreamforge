"""Shared fixtures for the DreamForge test suite."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dreamforge.core.config import SimulationConfig, load_config
from dreamforge.core.provenance.clock import FixedClock

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "configs"


@pytest.fixture()
def demo_config_dict() -> dict[str, Any]:
    """The bundled demo config as a mutable deep copy."""
    raw = json.loads((EXAMPLES / "demo_8h.json").read_text(encoding="utf-8"))
    return deepcopy(raw)


@pytest.fixture()
def demo_config(demo_config_dict: dict[str, Any]) -> SimulationConfig:
    """Validated small config (60 ticks) for fast deterministic tests."""
    payload = deepcopy(demo_config_dict)
    payload["total_ticks"] = 60
    return load_config(payload)


@pytest.fixture()
def fixed_clock() -> FixedClock:
    """Fixed provenance instant used by every deterministic test."""
    return FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC))
