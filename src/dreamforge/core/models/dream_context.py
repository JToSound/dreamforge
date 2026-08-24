"""Deterministic dream context and segments (MASTER_PROMPT.md §5.4, §6.1).

``DreamContext``/``DreamSegment`` are immutable and built ONLY from structured
state and selected synthetic node IDs — never prose. They are pure post-run
projections of emitted events; constructing one never mutates core state and
providers can never write back (ADR 0003).

Every feature documents its evidence variables, missing-data behaviour
(missing evidence ⇒ value 0.0), category distribution source, normalization,
and bounds. Values are structured numbers in [0, 1], never prose scores.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: DQCJ-1 quantization registry additions for context payloads. The score is
#: quantized to 0.01 (two-decimal percentage points) at the canonical boundary;
#: features keep 0.000001 like other engine floats.
CONTEXT_QUANTIZATIONS: dict[str, str] = {
    "features.scene_discontinuity": "0.000001",
    "features.entity_incongruity": "0.000001",
    "features.causal_implausibility": "0.000001",
    "features.temporal_distortion": "0.000001",
    "features.identity_instability": "0.000001",
    "features.memory_blending_entropy": "0.000001",
    "score_bizarreness_normalized": "0.000001",
}


class DreamSegment(BaseModel):
    """One contiguous stage episode with its replay selections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_index: int = Field(ge=0)
    stage: str
    start_tick: int = Field(ge=0)
    end_tick: int = Field(ge=0)  # inclusive epoch of the episode's last tick
    selected_node_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _order(self) -> DreamSegment:
        if self.end_tick < self.start_tick:
            msg = "end_tick must be >= start_tick"
            raise ValueError(msg)
        return self


class ContextFeatures(BaseModel):
    """The six bounded [0, 1] structured features (§5.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_discontinuity: float = Field(ge=0.0, le=1.0)
    entity_incongruity: float = Field(ge=0.0, le=1.0)
    causal_implausibility: float = Field(ge=0.0, le=1.0)
    temporal_distortion: float = Field(ge=0.0, le=1.0)
    identity_instability: float = Field(ge=0.0, le=1.0)
    memory_blending_entropy: float = Field(ge=0.0, le=1.0)


class DreamContext(BaseModel):
    """Immutable structured context over one completed run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    schema_version: str
    total_ticks: int = Field(ge=1)
    segments: tuple[DreamSegment, ...]
    features: ContextFeatures
    score_bizarreness_0_100: float = Field(ge=0.0, le=100.0)
    scorer_version: str
    output_class: str = "mechanistic_proxy"
    visible_label: str = "Simulated model proxy — not a biological measurement"

    @model_validator(mode="after")
    def _segments_ordered(self) -> DreamContext:
        previous_end = -1
        for seg in self.segments:
            if seg.start_tick <= previous_end:
                msg = "segments must be strictly ordered, non-overlapping"
                raise ValueError(msg)
            previous_end = seg.end_tick
        return self


def build_segments(events: list[Any], *, min_segment_ticks: int = 2) -> tuple[DreamSegment, ...]:
    """Group consecutive same-stage epochs into segments.

    Evidence: ``sleep_state.tick`` + ``stage`` per epoch; other event types
    carry no stage evidence and are ignored. Every stage episode — including
    short ones — is preserved as its own segment so the context never
    mislabels stages (``min_segment_ticks`` is retained for API stability and
    currently does not merge, documented honestly here).
    """
    if not events:
        return ()
    # Only sleep_state events carry stage evidence.
    state_events = [e for e in events if e.event_type == "sleep_state"]
    if not state_events:
        return ()
    episodes: list[tuple[str, int, int]] = []
    stage = str(state_events[0].payload.stage)
    start = int(state_events[0].tick)
    current = start
    for event in state_events[1:]:
        tick = int(event.tick)
        event_stage = str(event.payload.stage)
        if event_stage != stage or tick != current + 1:
            episodes.append((stage, start, current))
            stage, start = event_stage, tick
        current = tick
    episodes.append((stage, start, current))

    merged: list[list[int]] = []
    labels: list[str] = []
    for stage_name, ep_start, ep_end in episodes:
        merged.append([ep_start, ep_end])
        labels.append(stage_name)

    return tuple(
        DreamSegment(
            segment_index=index,
            stage=label,
            start_tick=span[0],
            end_tick=span[1],
        )
        for index, (label, span) in enumerate(zip(labels, merged, strict=True))
    )


# --- structured features (§5.4) --------------------------------------------
#
# Each feature documents: evidence variables, missing-data behaviour (missing
# evidence ⇒ 0.0), normalization (explicit denominator), and bounds. All are
# deterministic functions over emitted events/segments only.


def _replays_in(events: list[Any]) -> list[Any]:
    return [e for e in events if e.event_type == "memory_replay"]


def feature_scene_discontinuity(segments: tuple[DreamSegment, ...], total_ticks: int) -> float:
    """Stage-transition density per epoch, normalized by observed maximum.

    Evidence: segment boundaries. Missing data (no segments) ⇒ 0.0.
    Normalizer: 1 transition per 10 epochs is mapped to the full value — a
    declared calibration constant of this scorer version, not an empirical fit.
    """
    if len(segments) < 2 or total_ticks <= 0:
        return 0.0
    transitions = len(segments) - 1
    raw = transitions / max(total_ticks - 1, 1)
    return min(raw / 0.1, 1.0)


def feature_entity_incongruity(
    type_sets: list[set[str]],
) -> float:
    """Mean type-mix breadth across replay selections.

    Evidence: the set of distinct node types in each replay's selected IDs
    (types joined from the graph snapshot). Normalization: selections drawing
    from all 6 node types map to 1.0 (declared constant of this scorer
    version); missing selections ⇒ 0.0.
    """
    if not type_sets:
        return 0.0
    mixes = [min(len(types) / 6.0, 1.0) for types in type_sets]
    return sum(mixes) / len(mixes)


def feature_causal_implausibility(events: list[Any]) -> float:
    """Rate of N3→REM direct transitions among all stage transitions.

    Declared hypothesis-tagged proxy pattern: deep-slowed cortex followed
    immediately by REM-like activity is the configured 'implausible' pair for
    this toy grammar. Missing transitions ⇒ 0.0.
    """
    transitions = [e for e in events if e.event_type == "stage_transition"]
    if not transitions:
        return 0.0
    implausible = sum(
        1 for e in transitions if e.payload.from_stage == "N3" and e.payload.to_stage == "REM"
    )
    return min(implausible / len(transitions), 1.0)


def feature_temporal_distortion(segments: tuple[DreamSegment, ...]) -> float:
    """Coefficient of variation of segment lengths, squashed to [0, 1].

    Evidence: epoch spans of segments. A perfectly regular structure maps
    toward 0; wildly irregular lengths map toward 1 (bounded via
    CV/(1+CV)). Fewer than two segments ⇒ missing evidence ⇒ 0.0.
    """
    if len(segments) < 2:
        return 0.0
    lengths = [s.end_tick - s.start_tick + 1 for s in segments]
    mean_length = sum(lengths) / len(lengths)
    if mean_length <= 0:
        return 0.0
    variance = sum((n - mean_length) ** 2 for n in lengths) / len(lengths)
    cv = (variance**0.5) / mean_length
    return float(min(cv / (1.0 + cv), 1.0))


def feature_identity_instability(replays: list[Any]) -> float:
    """Mean fraction of newly-introduced nodes across consecutive selections.

    Evidence: consecutive ``selected_node_ids`` sets. One selection or none
    ⇒ missing evidence ⇒ 0.0. Identical successive selections ⇒ 0.0.
    """
    if len(replays) < 2:
        return 0.0
    fractions: list[float] = []
    previous: frozenset[str] | None = None
    for event in replays:
        current = frozenset(event.payload.selected_node_ids)
        if previous is not None and previous:
            fresh = len(current - previous)
            fractions.append(fresh / len(previous))
        previous = current
    if not fractions:
        return 0.0
    return min(sum(fractions) / len(fractions), 1.0)


def feature_memory_blending_entropy(replays: list[Any]) -> float:
    """Shannon entropy of node-selection frequencies over the run.

    Evidence: every selected ID across replays. Normalized by ln(k) where k =
    number of DISTINCT nodes observed (documented denominator); k < 2 ⇒ 0.0.
    Uniform coverage of all observed nodes approaches 1.0.
    """
    import math

    counts: dict[str, int] = {}
    for event in replays:
        for node_id in event.payload.selected_node_ids:
            counts[node_id] = counts.get(node_id, 0) + 1
    total_selections = sum(counts.values())
    if total_selections == 0 or len(counts) < 2:
        return 0.0
    entropy = -sum(
        (count / total_selections) * math.log(count / total_selections, math.e)
        for count in counts.values()
    )
    return min(entropy / math.log(len(counts), math.e), 1.0)


def build_dream_context(
    *,
    run_id: str,
    schema_version: str,
    total_ticks: int,
    events: list[Any],
    node_type_lookup: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
) -> DreamContext:
    """Construct the immutable context from emitted events (pure function)."""
    from dreamforge.core.scoring.bizarreness import score_bizarreness

    segments = build_segments(events)
    replays = _replays_in(events)

    # Attach each epoch's replay selections to the segment containing it so
    # downstream consumers (provider projection) see tokens per episode.
    if segments and replays:
        selections_by_tick: dict[int, tuple[str, ...]] = {
            int(event.tick): tuple(event.payload.selected_node_ids) for event in replays
        }
        attached: list[DreamSegment] = []
        for segment in segments:
            token_ids: list[str] = []
            for tick in range(segment.start_tick, segment.end_tick + 1):
                for node_id in selections_by_tick.get(tick, ()):
                    if node_id not in token_ids:
                        token_ids.append(node_id)
            if token_ids:
                attached.append(
                    segment.model_copy(update={"selected_node_ids": tuple(token_ids)}),
                )
            else:
                attached.append(segment)
        segments = tuple(attached)

    # Entity incongruity joins node types from the caller-supplied lookup
    # (built from the graph snapshot); without it, documented missing-data
    # behaviour applies (0.0).
    type_sets: list[set[str]] = []
    if node_type_lookup:
        type_sets = [
            {
                node_type_lookup.get(node_id, "unknown")
                for node_id in event.payload.selected_node_ids
            }
            for event in replays
        ]
    entity_value = feature_entity_incongruity(type_sets)

    features = ContextFeatures(
        scene_discontinuity=feature_scene_discontinuity(segments, total_ticks),
        entity_incongruity=entity_value,
        causal_implausibility=feature_causal_implausibility(events),
        temporal_distortion=feature_temporal_distortion(segments),
        identity_instability=feature_identity_instability(replays),
        memory_blending_entropy=feature_memory_blending_entropy(replays),
    )

    normalized, absolute = score_bizarreness(features, weights=weights)
    return DreamContext(
        run_id=run_id,
        schema_version=schema_version,
        total_ticks=max(total_ticks, 1),
        segments=segments,
        features=features,
        score_bizarreness_0_100=absolute,
        scorer_version="bizarreness-v1",
    )
