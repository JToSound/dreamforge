"""Fictional pharmacology scenarios — disabled by default (§5.5, M4).

Hard boundaries enforced by construction and by tests:

- Every scenario is a FICTIONAL qualitative label. No doses, no identities,
  no diagnoses, no interactions, no efficacy prediction, no advice.
- The module is INERT until the caller passes an explicit acknowledgement
  event (an identity-free string recorded in the audit trail). Importing
  this package enables nothing; constructing ``PharmacologyPlugin`` without
  an acknowledgement raises immediately.
- Scenario effects are bounded qualitative multipliers applied to the
  chemistry proxies' stage-modulation table - declared, deterministic,
  and exported with the run for full auditability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dreamforge.core.models.events import StageName

CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")

STAGES_ALL: tuple[StageName, ...] = ("Wake", "N1", "N2", "N3", "REM")


class PharmacologyError(RuntimeError):
    """Refusal reason for any use outside the acknowledged fictional frame."""


class Acknowledgement(BaseModel):
    """Identity-free user acknowledgement (§5.5). Recorded, never de-anonymised."""

    model_config = ConfigDict(frozen=True)

    statement: str = Field(min_length=16)
    acknowledged_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _check(self) -> Acknowledgement:
        if "fictional" not in self.statement.lower():
            raise ValueError("acknowledgement must contain the word 'fictional'")
        return self


@dataclass(frozen=True)
class FictionalScenario:
    """A named qualitative scenario: per-channel/stage multiplier deltas.

    All values are dimensionless additive deltas on the [0,1] proxy scale,
    clipped at application time. Nothing here maps to a real substance.
    """

    key: str
    description: str
    # channel -> stage -> delta
    modulation_delta: dict[str, dict[str, float]] = field(default_factory=dict)

    def channels(self) -> tuple[str, ...]:
        return tuple(sorted(self.modulation_delta))


def _deltas(spec: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {
        channel: {str(stage): float(delta) for stage, delta in stages.items()}
        for channel, stages in spec.items()
    }


FICTIONAL_SCENARIOS: dict[str, FictionalScenario] = {
    "caffeine_like_evening": FictionalScenario(
        key="caffeine_like_evening",
        description=(
            "Fictional 'stimulant-like evening': raised arousal-proxy tone "
            "(noradrenaline +) and reduced sleep pressure relief during N3. "
            "Purely a narrative device; resembles no real dosing."
        ),
        modulation_delta=_deltas(
            {
                "noradrenaline": {"Wake": 0.08, "N1": 0.04},
                "serotonin": {"N3": -0.03},
            }
        ),
    ),
    "sedative_like_night": FictionalScenario(
        key="sedative_like_night",
        description=(
            "Fictional 'sedative-like night': deeper, longer N3-biased tone "
            "with blunted REM-proxy. Narrative only; not a medication."
        ),
        modulation_delta=_deltas(
            {
                "cortisol": {"N3": -0.05},
                "acetylcholine": {"REM": -0.06},
            }
        ),
    ),
    "no_scenario": FictionalScenario(
        key="no_scenario",
        description="Baseline: zero deltas; the scenario system is a no-op.",
        modulation_delta={},
    ),
}


class PharmacologyPlugin:
    """Ack-gated applier of ONE fictional scenario to chemistry config dicts."""

    DISABLED_BY_DEFAULT = True

    def __init__(self, acknowledgement: Acknowledgement | None) -> None:
        if acknowledgement is None:
            raise PharmacologyError(
                "pharmacology requires an explicit acknowledgement event; "
                "the plugin is disabled by default"
            )
        if acknowledgement.statement.strip() == "":
            raise PharmacologyError("empty acknowledgement")
        self._ack = acknowledgement
        self.audit: list[dict[str, str]] = [
            {
                "event": "pharmacology_acknowledged",
                "statement": acknowledgement.statement,
                "at": acknowledgement.acknowledged_at.isoformat(timespec="seconds"),
            },
        ]

    @property
    def acknowledged(self) -> bool:
        return True

    def apply(
        self,
        chemistry_cfg: dict[str, Any],
        scenario_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (modified_chemistry, audit_record) for ONE scenario.

        ``chemistry_cfg`` is the plain-dict chemistry block from a payload;
        it is copied, never mutated in place.
        """
        scenario = FICTIONAL_SCENARIOS.get(scenario_key)
        if scenario is None:
            raise PharmacologyError(f"unknown scenario {scenario_key!r}")

        modified = {
            "baselines": dict(chemistry_cfg.get("baselines", {})),
            "stage_modulation": {
                channel: dict(stages)
                for channel, stages in chemistry_cfg.get("stage_modulation", {}).items()
            },
            "circadian_gain": dict(chemistry_cfg.get("circadian_gain", {})),
        }
        for channel, stages in scenario.modulation_delta.items():
            target = modified["stage_modulation"].setdefault(channel, {})
            for stage_name, delta in stages.items():
                key = str(stage_name)
                target[key] = round(target.get(key, 0.0) + delta, 6)

        record: dict[str, Any] = {
            "event": "scenario_applied",
            "scenario": scenario.key,
            "deltas": {
                ch: {str(s): d for s, d in stages.items()}
                for ch, stages in scenario.modulation_delta.items()
            },
        }
        self.audit.append(record)
        return modified, record
