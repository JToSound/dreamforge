"""Dream context, features, and bizarreness score units (§5.4)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamforge.core.models.dream_context import (
    ContextFeatures,
    DreamContext,
    DreamSegment,
    build_dream_context,
    build_segments,
    feature_causal_implausibility,
    feature_entity_incongruity,
    feature_identity_instability,
    feature_memory_blending_entropy,
    feature_scene_discontinuity,
    feature_temporal_distortion,
)
from dreamforge.core.scoring.bizarreness import (
    DEFAULT_BIZARRENESS_WEIGHTS,
    BizarrenessWeights,
    quantize_score_for_export,
    score_bizarreness,
)


def make_event(event_type: str, payload, tick: int):
    from dreamforge.core.models.events import make_event

    return make_event(
        run_id="run-context-01",
        event_type=event_type,  # type: ignore[arg-type]
        event_sequence=1,  # sequences not asserted in these unit fixtures
        epoch_seconds=30.0,
        tick=tick,
        source_component="x",
        schema_version="1.0",
        correlation_id="c",
        emitted_at="2026-08-24T21:00:00+00:00",
        payload=payload,
    )


def sleep_state(stage: str, tick: int):
    from dreamforge.core.models.events import SleepStatePayload

    return make_event(
        "sleep_state",
        SleepStatePayload(stage=stage, s_value=0.5, c_value=0.5, ticks_in_stage=1),
        tick,
    )


class TestBuildSegments:
    def test_groups_consecutive_same_stage(self) -> None:
        events = (
            [sleep_state("Wake", t) for t in range(4)]
            + [sleep_state("N2", t) for t in range(4, 10)]
            + [sleep_state("Wake", 10)]
        )
        segments = build_segments(list(events))
        assert len(segments) == 3
        assert (segments[0].stage, segments[0].start_tick, segments[0].end_tick) == ("Wake", 0, 3)
        assert (segments[1].stage, segments[1].start_tick, segments[1].end_tick) == ("N2", 4, 9)

    def test_short_trailing_segment_kept_truthfully(self) -> None:
        events = [sleep_state("Wake", t) for t in range(6)] + [sleep_state("REM", 6)]
        segments = build_segments(list(events), min_segment_ticks=2)
        assert len(segments) == 2
        assert (segments[1].stage, segments[1].start_tick) == ("REM", 6)

    def test_empty_events_no_segments(self) -> None:
        assert build_segments([]) == ()

    def test_gap_starts_new_segment(self) -> None:
        events = [sleep_state("Wake", 0), sleep_state("Wake", 5)]
        segments = build_segments(events)
        assert len(segments) == 2


class TestFeatures:
    def test_scene_discontinuity_bounds_and_missing(self) -> None:
        assert feature_scene_discontinuity((), 100) == 0.0
        segs = (
            DreamSegment(segment_index=0, stage="Wake", start_tick=0, end_tick=4),
            DreamSegment(segment_index=1, stage="N2", start_tick=5, end_tick=14),
        )
        value = feature_scene_discontinuity(segs, 15)
        assert 0.0 <= value <= 1.0

    def test_causal_implausibility_counts_n3_rem_only(self) -> None:
        from dreamforge.core.models.events import StageTransitionPayload

        events = [
            make_event(
                "stage_transition",
                StageTransitionPayload(
                    from_stage=f,
                    to_stage=t,
                    completed_dwell_epochs=3,
                    next_dwell_epochs=4,
                ),
                i,
            )
            for i, (f, t) in enumerate(
                [("N3", "REM"), ("N2", "N3"), ("N3", "REM"), ("Wake", "N1")],
            )
        ]
        assert feature_causal_implausibility(events) == pytest.approx(0.5)
        assert feature_causal_implausibility([]) == 0.0

    def test_temporal_distortion_zero_for_uniform(self) -> None:
        segs = tuple(
            DreamSegment(segment_index=i, stage="N2", start_tick=i * 10, end_tick=i * 10 + 9)
            for i in range(4)
        )
        assert feature_temporal_distortion(segs) == 0.0

    def test_identity_instability_identical_selections_zero(self) -> None:
        from dreamforge.core.models.events import MemoryReplayPayload, ReplayContribution

        contribution = ReplayContribution(
            node_id="tok_0",
            activation_share=1.0,
            recency_share=0.0,
            salience_share=0.0,
            stage_share=0.0,
            novelty_share=0.0,
        )
        replays = [
            make_event(
                "memory_replay",
                MemoryReplayPayload(
                    selected_node_ids=("tok_0",),
                    contributions=(contribution,),
                    candidate_count=1,
                    rejected_ids_sha256_prefixes=(),
                    policy_reason="r",
                ),
                tick,
            )
            for tick in (0, 8)
        ]
        assert feature_identity_instability(replays) == 0.0

    def test_entropy_uniform_selections_high(self) -> None:
        from dreamforge.core.models.events import MemoryReplayPayload, ReplayContribution

        def replay(nodes: tuple[str, ...], tick: int):
            contrib = ReplayContribution(
                node_id=nodes[0],
                activation_share=1.0,
                recency_share=0.0,
                salience_share=0.0,
                stage_share=0.0,
                novelty_share=0.0,
            )
            return make_event(
                "memory_replay",
                MemoryReplayPayload(
                    selected_node_ids=nodes,
                    contributions=(contrib,),
                    candidate_count=4,
                    rejected_ids_sha256_prefixes=(),
                    policy_reason="r",
                ),
                tick,
            )

        replays = [
            replay(("a", "b"), 0),
            replay(("b", "c"), 8),
            replay(("c", "d"), 16),
            replay(("d", "a"), 24),
        ]
        value = feature_memory_blending_entropy(replays)
        assert value > 0.9
        assert feature_memory_blending_entropy([]) == 0.0

    def test_entity_incongruity_normalization(self) -> None:
        assert feature_entity_incongruity([]) == 0.0
        full_mix = [{"episode", "emotion", "place", "object", "concept", "person"}]
        assert feature_entity_incongruity(full_mix) == pytest.approx(1.0)


class TestScore:
    def test_score_bounds_and_weight_validation(self) -> None:
        feats = ContextFeatures(
            scene_discontinuity=1.0,
            entity_incongruity=1.0,
            causal_implausibility=1.0,
            temporal_distortion=1.0,
            identity_instability=1.0,
            memory_blending_entropy=1.0,
        )
        normalized, absolute = score_bizarreness(feats)
        assert normalized == pytest.approx(1.0)
        assert absolute == pytest.approx(100.0)

        zero = ContextFeatures(
            scene_discontinuity=0.0,
            entity_incongruity=0.0,
            causal_implausibility=0.0,
            temporal_distortion=0.0,
            identity_instability=0.0,
            memory_blending_entropy=0.0,
        )
        _, zero_absolute = score_bizarreness(zero)
        assert zero_absolute == 0.0

    def test_weights_must_sum_to_one(self) -> None:
        bad = dict(DEFAULT_BIZARRENESS_WEIGHTS)
        bad["scene_discontinuity"] = 0.9
        with pytest.raises(ValueError, match="sum to"):
            BizarrenessWeights(values=bad)

    def test_out_of_range_feature_raises(self) -> None:
        class Bad:
            scene_discontinuity = 1.5
            entity_incongruity = 0.0
            causal_implausibility = 0.0
            temporal_distortion = 0.0
            identity_instability = 0.0
            memory_blending_entropy = 0.0

        with pytest.raises(ValueError, match="out of"):
            score_bizarreness(Bad())

    def test_quantize_export_two_decimals(self) -> None:
        assert quantize_score_for_export(73.4567) == pytest.approx(73.46)
        # HALF_EVEN: 0.005 sits exactly between 0.00 and 0.01 -> ties go to even.
        assert quantize_score_for_export(0.005) == pytest.approx(0.0)


class TestBuildContext:
    def test_full_run_context_bounded_and_labeled(self, demo_config_dict) -> None:
        from datetime import UTC, datetime

        from dreamforge.core.config import load_config
        from dreamforge.core.provenance.clock import FixedClock
        from dreamforge.simulation.engine import run_simulation

        payload = dict(demo_config_dict)
        payload["total_ticks"] = 90
        result = run_simulation(load_config(payload), FixedClock(datetime(2026, 8, 24, tzinfo=UTC)))
        node_types = {
            str(n["id"]): str(n.get("node_type", "unknown")) for n in result.graph_snapshot["nodes"]
        }
        context = build_dream_context(
            run_id=payload["run_id"],
            schema_version="1.0",
            total_ticks=90,
            events=list(result.events),
            node_type_lookup=node_types,
        )
        assert isinstance(context, DreamContext)
        for name in ContextFeatures.model_fields:
            value = getattr(context.features, name)
            assert 0.0 <= value <= 1.0
        assert 0.0 <= context.score_bizarreness_0_100 <= 100.0
        assert len(context.segments) >= 2
        # determinism: identical inputs -> identical canonical bytes
        again = build_dream_context(
            run_id=payload["run_id"],
            schema_version="1.0",
            total_ticks=90,
            events=list(result.events),
            node_type_lookup=node_types,
        )
        from dreamforge.core.serialization.dqcj import dumps_canonical

        assert dumps_canonical(context.model_dump()) == dumps_canonical(again.model_dump())

    def test_property_features_bounded_for_random_runs(self) -> None:
        rng = np.random.default_rng(11)
        for _ in range(5):
            stages = rng.choice(["Wake", "N1", "N2", "N3", "REM"], size=30)
            events = [sleep_state(str(s), t) for t, s in enumerate(stages)]
            segments = build_segments(events)
            value = feature_scene_discontinuity(segments, 30)
            assert 0.0 <= value <= 1.0
