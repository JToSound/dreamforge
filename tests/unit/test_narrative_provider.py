"""Provider protocol, mock narrative determinism, and outage isolation (§6.2)."""

from __future__ import annotations

import pytest

from dreamforge.core.models.dream_context import ContextFeatures, DreamContext, DreamSegment
from dreamforge.core.providers.narrative import (
    GENERATIVE_LABEL,
    OUTPUT_CLASS_GENERATIVE,
    ContextBudgetExceededError,
    MinimizedContext,
    MockNarrativeProvider,
    NarrativeRequest,
    ProviderConfigError,
    minimize_context,
)
from dreamforge.simulation.report import (
    MECHANISTIC_LABEL,
    attach_narrative,
    build_report,
)


def make_context(**overrides) -> DreamContext:
    features = ContextFeatures(
        scene_discontinuity=0.4,
        entity_incongruity=0.5,
        causal_implausibility=0.2,
        temporal_distortion=0.3,
        identity_instability=0.1,
        memory_blending_entropy=0.7,
    )
    segments = (
        DreamSegment(
            segment_index=0,
            stage="Wake",
            start_tick=0,
            end_tick=5,
            selected_node_ids=("tok_00", "tok_05"),
        ),
        DreamSegment(
            segment_index=1, stage="N2", start_tick=6, end_tick=15, selected_node_ids=("tok_02",)
        ),
    )
    values = {
        "run_id": "run-narr-0001",
        "schema_version": "1.0",
        "total_ticks": 16,
        "segments": segments,
        "features": features,
        "score_bizarreness_0_100": 37.5,
        "scorer_version": "bizarreness-v1",
    }
    values.update(overrides)
    return DreamContext(**values)


class TestMockProvider:
    def test_deterministic_identical_requests(self) -> None:
        provider = MockNarrativeProvider()
        request = NarrativeRequest(minimized_context=minimize_context(make_context()))
        r1 = provider.generate(request)
        r2 = provider.generate(request)
        assert r1.text == r2.text
        assert r1.response_sha256 == r2.response_sha256

    def test_labels_exact(self) -> None:
        provider = MockNarrativeProvider()
        response = provider.generate(
            NarrativeRequest(minimized_context=minimize_context(make_context())),
        )
        assert response.output_class == OUTPUT_CLASS_GENERATIVE
        assert response.visible_label == GENERATIVE_LABEL

    def test_unknown_style_rejected(self) -> None:
        provider = MockNarrativeProvider()
        with pytest.raises(ProviderConfigError):
            provider.generate(
                NarrativeRequest(minimized_context=minimize_context(make_context()), style="haiku"),
            )

    def test_budget_exceeded_not_truncated(self) -> None:
        context = make_context(
            segments=tuple(
                DreamSegment(
                    segment_index=i,
                    stage="N3",
                    start_tick=i * 10,
                    end_tick=i * 10 + 9,
                    selected_node_ids=tuple(f"tok_{j:04d}" for j in range(i * 10, i * 10 + 10)),
                )
                for i in range(60)
            ),
        )
        minimized = minimize_context(context, max_tokens=400)
        with pytest.raises(ContextBudgetExceededError):
            minimized.enforce_budget()

    def test_no_free_text_only_controlled_tokens(self) -> None:
        minimized = minimize_context(make_context())
        for token in minimized.selected_token_ids:
            assert token.startswith("tok_")


class TestOutageIsolation:
    def test_provider_failure_leaves_core_and_report_intact(
        self,
        demo_config_dict,
        fixed_clock,
    ) -> None:
        from dreamforge.core.config import load_config
        from dreamforge.core.serialization.dqcj import dumps_canonical
        from dreamforge.simulation.engine import run_simulation

        payload = dict(demo_config_dict)
        payload["total_ticks"] = 40
        config = load_config(payload)
        result = run_simulation(config, fixed_clock)
        hash_before = result.core_trace_hash

        context = build_context_of(result, 40)
        report = build_report(
            context=context,
            event_counts={"sleep_state": 40},
            core_trace_hash=hash_before,
        )
        canonical_before = dumps_canonical(report.model_dump())

        class ExplodingProvider(MockNarrativeProvider):
            def generate(self, request):  # noqa: ANN001, ANN202
                raise RuntimeError("provider outage")

        with pytest.raises(RuntimeError, match="outage"):
            attach_narrative(context, report, ExplodingProvider(), style="plain")
        # deterministic blocks unchanged; trace unchanged
        assert result.core_trace_hash == hash_before
        assert dumps_canonical(report.model_dump()) == canonical_before
        assert report.narrative is None
        assert report.summary.visible_label == MECHANISTIC_LABEL

    def test_attach_narrative_labeled_generative(self) -> None:
        context = make_context()
        report = build_report(
            context=context,
            event_counts={"sleep_state": 16},
            core_trace_hash="x",
        )
        updated, _response = attach_narrative(
            context,
            report,
            MockNarrativeProvider(),
            style="plain",
        )
        assert updated.narrative is not None
        assert updated.narrative.output_class == OUTPUT_CLASS_GENERATIVE
        assert updated.summary.output_class == "mechanistic_proxy"


def build_context_of(result, ticks: int):
    from dreamforge.core.models.dream_context import build_dream_context

    node_types = {
        str(n["id"]): str(n.get("node_type", "unknown")) for n in result.graph_snapshot["nodes"]
    }
    return build_dream_context(
        run_id=result.manifest.run_id,
        schema_version="1.0",
        total_ticks=ticks,
        events=list(result.events),
        node_type_lookup=node_types,
    )


class TestMinimizedProjection:
    def test_projection_hashes_stable(self) -> None:
        a = minimize_context(make_context()).context_sha256()
        b = minimize_context(make_context()).context_sha256()
        assert a == b

    def test_projection_never_contains_scoreless_prose(self) -> None:
        minimized = minimize_context(make_context())
        dumped = minimized.model_dump()
        text_fields = [value for value in dumped.values() if isinstance(value, str)]
        for field_value in text_fields:
            assert len(field_value) < 200  # labels/ids only, never prose bodies


def test_minimized_class_exists_exportable() -> None:
    assert MinimizedContext.model_fields["output_class"].default == OUTPUT_CLASS_GENERATIVE
