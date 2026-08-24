"""Composite run report with per-block output_class labels (§1.2, §6.1).

Every block carries exactly one primary ``output_class`` and the exact visible
label from the taxonomy. The report is a pure post-run projection: building it
never re-runs the simulator or a provider beyond the explicit render step the
caller chooses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from dreamforge.core.models.dream_context import DreamContext
from dreamforge.core.providers.narrative import (
    GENERATIVE_LABEL,
    OUTPUT_CLASS_GENERATIVE,
    NarrativeRequest,
    NarrativeResponse,
)
from dreamforge.core.serialization.dqcj import dumps_canonical

MECHANISTIC_LABEL = "Simulated model proxy — not a biological measurement"
OUTPUT_CLASS_MECHANISTIC = "mechanistic_proxy"

REPORT_VERSION = "run-report-v1"


class RunSummaryBlock(BaseModel):
    """Deterministic run statistics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = OUTPUT_CLASS_MECHANISTIC
    visible_label: str = MECHANISTIC_LABEL
    run_id: str
    total_ticks: int
    event_count: int
    stage_transition_count: int
    replay_count: int


class FeaturesBlock(BaseModel):
    """The six structured features plus the weighted score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = OUTPUT_CLASS_MECHANISTIC
    visible_label: str = MECHANISTIC_LABEL
    features: dict[str, float]
    score_bizarreness_0_100: float
    scorer_version: str


class NarrativeBlock(BaseModel):
    """Provider-rendered block; labeled generative, never mechanistic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = OUTPUT_CLASS_GENERATIVE
    visible_label: str = GENERATIVE_LABEL
    text: str
    provider: str
    context_sha256: str
    response_sha256: str


class RunReport(BaseModel):
    """Composite report; every block labeled separately (§1.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: str = REPORT_VERSION
    run_id: str
    summary: RunSummaryBlock
    features_block: FeaturesBlock
    narrative: NarrativeBlock | None = None

    def to_canonical_bytes(self) -> bytes:
        """DQCJ-1 canonical bytes of the whole labeled report."""
        return dumps_canonical(self.model_dump())


def build_report(
    *,
    context: DreamContext,
    event_counts: dict[str, int],
    core_trace_hash: str,
) -> RunReport:
    """Assemble the deterministic blocks of the report.

    ``narrative`` stays None unless :meth:`attach_narrative` is called with an
    explicit provider request — a provider outage therefore yields a complete
    labeled report without any invented content.
    """
    del core_trace_hash  # recorded by callers in export manifests
    summary = RunSummaryBlock(
        run_id=context.run_id,
        total_ticks=context.total_ticks,
        event_count=sum(event_counts.values()),
        stage_transition_count=event_counts.get("stage_transition", 0),
        replay_count=event_counts.get("memory_replay", 0),
    )
    features_block = FeaturesBlock(
        features={
            "scene_discontinuity": context.features.scene_discontinuity,
            "entity_incongruity": context.features.entity_incongruity,
            "causal_implausibility": context.features.causal_implausibility,
            "temporal_distortion": context.features.temporal_distortion,
            "identity_instability": context.features.identity_instability,
            "memory_blending_entropy": context.features.memory_blending_entropy,
        },
        score_bizarreness_0_100=context.score_bizarreness_0_100,
        scorer_version=context.scorer_version,
    )
    return RunReport(
        run_id=context.run_id,
        summary=summary,
        features_block=features_block,
    )


def attach_narrative(
    context: DreamContext,
    report: RunReport,
    provider: Any,
    style: str,
) -> tuple[RunReport, NarrativeResponse]:
    """Render via ``provider`` from the minimized projection of ``context``.

    Returns the updated report plus the validated response. Failure semantics:
    exceptions propagate AFTER the deterministic report exists — callers keep a
    valid, fully labeled report by constructing it first (outage isolation).
    """
    from dreamforge.core.providers.narrative import (
        minimize_context,
    )

    minimized = minimize_context(context)
    response = provider.generate(
        NarrativeRequest(minimized_context=minimized, style=style),
    )
    if response.output_class != OUTPUT_CLASS_GENERATIVE:
        msg = "provider response must carry generative output class"
        raise ValueError(msg)
    block = NarrativeBlock(
        text=response.text,
        provider=response.provider,
        context_sha256=response.context_sha256,
        response_sha256=response.response_sha256,
    )
    return report.model_copy(update={"narrative": block}), response
