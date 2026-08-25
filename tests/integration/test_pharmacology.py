"""Pharmacology plugin: ack gate, fictional scenarios, disabled-by-default."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

from dreamforge.integrations.pharmacology import (  # noqa: E402
    FICTIONAL_SCENARIOS,
    Acknowledgement,
    PharmacologyError,
    PharmacologyPlugin,
)


def make_ack() -> Acknowledgement:
    return Acknowledgement(
        statement="I understand these are fictional scenarios with no real-world basis."
    )


class TestAcknowledgement:
    def test_missing_fictional_word_rejected(self) -> None:
        with pytest.raises(ValueError, match="fictional"):
            Acknowledgement(statement="I have read the documentation carefully.")

    def test_valid_acknowledgement_accepted(self) -> None:
        assert make_ack().acknowledged_at is not None


class TestPluginGate:
    def test_plugin_requires_acknowledgement(self) -> None:
        with pytest.raises(PharmacologyError):
            PharmacologyPlugin(None)  # type: ignore[arg-type]

    def test_scenarios_exist_and_are_fictional(self) -> None:
        keys = set(FICTIONAL_SCENARIOS)
        assert {"caffeine_like_evening", "sedative_like_night", "no_scenario"} <= keys
        for scenario in FICTIONAL_SCENARIOS.values():
            lowered = scenario.description.lower()
            assert "fictional" in lowered or scenario.key == "no_scenario"

    def test_apply_modifies_copy_not_original(self) -> None:
        plugin = PharmacologyPlugin(make_ack())
        original = {
            "baselines": {
                c: 0.5 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "stage_modulation": {
                c: {s: 0.0 for s in ("Wake", "N1", "N2", "N3", "REM")}
                for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
            "circadian_gain": {
                c: 0.0 for c in ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
            },
        }
        modified, record = plugin.apply(original, "caffeine_like_evening")
        # Original untouched.
        assert original["stage_modulation"]["noradrenaline"]["Wake"] == 0.0
        # Copy carries the delta and it stays inside a sane additive range.
        delta = modified["stage_modulation"]["noradrenaline"]["Wake"]
        assert delta == pytest.approx(0.08)
        assert record["event"] == "scenario_applied"

    def test_unknown_scenario_refused(self) -> None:
        plugin = PharmacologyPlugin(make_ack())
        with pytest.raises(PharmacologyError, match="unknown scenario"):
            plugin.apply({}, "ambient_polka")

    def test_audit_trail_grows(self) -> None:
        plugin = PharmacologyPlugin(make_ack())
        base = len(plugin.audit)
        plugin.apply({}, "no_scenario")
        assert len(plugin.audit) == base + 1

    def test_disabled_by_default_nothing_imports_plugin(self) -> None:
        """Demo + dashboard must not pull pharmacology in."""
        probe = (
            "import sys\n"
            f"sys.path.insert(0, r'{REPO / 'src'}')\n"
            "import dreamforge.demo\n"
            "hits = [m for m in sys.modules if 'pharmacology' in m]\n"
            "print('PULLED:' + ','.join(hits) if hits else 'NOT_PULLED')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert "NOT_PULLED" in completed.stdout, completed.stdout + completed.stderr
