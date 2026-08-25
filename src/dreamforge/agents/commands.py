"""Layer B typed commands (§6.1): the ONLY way agents may affect state.

An agent never mutates engine state directly. It proposes a command; the
engine validates it against declared policy and either accepts it (recording
an audit event) or refuses it with a typed reason. Commands are frozen
models - immutable, hashable, canonicalizable.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from dreamforge.core.models.events import StageName


class CommandKind(StrEnum):
    """The complete set of agent-proposable actions (closed vocabulary)."""

    REQUEST_STAGE_TRANSITION = "request_stage_transition"
    SET_CHEMISTRY_BASELINE = "set_chemistry_baseline"
    TAG_EPISODE = "tag_episode"


class CommandRefusalReason(StrEnum):
    """Why a proposed command was refused (audit-safe vocabulary)."""

    POLICY_DISABLED = "policy_disabled"
    NOT_ALLOWED_TRANSITION = "not_allowed_transition"
    OUT_OF_BOUNDS = "out_of_bounds"
    UNKNOWN_FIELD = "unknown_field"
    WINDOW_CLOSED = "window_closed"


class AgentCommand(BaseModel):
    """A single typed proposal from one named agent."""

    model_config = ConfigDict(frozen=True)

    kind: CommandKind
    agent: str = Field(pattern=r"^[a-z][a-z0-9_]{2,31}$")
    tick: int = Field(ge=0)
    payload: dict[str, str | int | float] = Field(default_factory=dict)


class CommandOutcome(BaseModel):
    """Engine's verdict on one proposed command."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    reason: CommandRefusalReason | None = None
    detail: str = ""


class TypedCommandGate:
    """Validates proposals against declared policy; keeps an audit trail.

    The gate holds NO simulation state. Policy flags are supplied by the
    application layer; every decision (accepted or refused) is recorded.
    """

    def __init__(
        self,
        *,
        stage_transition_policy_enabled: bool = False,
        allowed_transitions: dict[StageName, tuple[StageName, ...]] | None = None,
        chemistry_bounds: tuple[float, float] = (0.0, 1.0),
    ) -> None:
        self._stage_policy_enabled = stage_transition_policy_enabled
        self._allowed_transitions = allowed_transitions or {}
        self._chemistry_lo, self._chemistry_hi = chemistry_bounds
        self.audit: list[tuple[AgentCommand, CommandOutcome]] = []

    def propose(self, command: AgentCommand) -> CommandOutcome:
        """Validate one proposal; append the decision to the audit trail."""
        outcome = self._evaluate(command)
        self.audit.append((command, outcome))
        return outcome

    def _evaluate(self, command: AgentCommand) -> CommandOutcome:
        if command.kind is CommandKind.REQUEST_STAGE_TRANSITION:
            return self._eval_stage(command)
        if command.kind is CommandKind.SET_CHEMISTRY_BASELINE:
            return self._eval_chemistry(command)
        if command.kind is CommandKind.TAG_EPISODE:
            return CommandOutcome(accepted=True)
        msg = f"unhandled command kind {command.kind}"
        raise ValueError(msg)  # pragma: no cover - closed enum

    def _eval_stage(self, command: AgentCommand) -> CommandOutcome:
        if not self._stage_policy_enabled:
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.POLICY_DISABLED,
                detail="stage-transition policy is disabled by default",
            )
        frm = str(command.payload.get("from_stage", ""))
        to = str(command.payload.get("to_stage", ""))
        allowed = self._allowed_transitions.get(frm, ())  # type: ignore[union-attr]
        if to not in allowed:
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.NOT_ALLOWED_TRANSITION,
                detail=f"{frm}->{to} outside declared allowed pairs",
            )
        return CommandOutcome(accepted=True)

    def _eval_chemistry(self, command: AgentCommand) -> CommandOutcome:
        unknown = set(command.payload) - {"channel", "value"}
        if unknown:
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.UNKNOWN_FIELD,
                detail=f"unexpected keys {sorted(unknown)}",
            )
        channel = str(command.payload.get("channel", ""))
        try:
            value = float(command.payload.get("value", float("nan")))
        except (TypeError, ValueError):
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.OUT_OF_BOUNDS,
                detail="value not numeric",
            )
        if channel not in ("acetylcholine", "serotonin", "noradrenaline", "cortisol"):
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.UNKNOWN_FIELD,
                detail=f"unknown channel {channel!r}",
            )
        if not (self._chemistry_lo <= value <= self._chemistry_hi):
            return CommandOutcome(
                accepted=False,
                reason=CommandRefusalReason.OUT_OF_BOUNDS,
                detail=f"{value} outside [{self._chemistry_lo}, {self._chemistry_hi}]",
            )
        return CommandOutcome(accepted=True)
