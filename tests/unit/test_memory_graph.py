"""Synthetic graph and replay-selection units (section 5.3)."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from dreamforge.core.models.memory_graph import (
    GraphSerializerV1,
    GraphSpecConfig,
    ReplayEventScheduler,
    ReplaySelectorConfig,
    build_synthetic_graph,
)


def make_graph(seed: int = 11):
    spec = GraphSpecConfig(node_count=12, edge_count=20)
    rng = np.random.Generator(np.random.PCG64(seed))
    return build_synthetic_graph(spec, rng)


class TestGraphBuild:
    def test_deterministic_given_same_stream_state(self) -> None:
        spec = GraphSpecConfig(node_count=10, edge_count=15)
        g1 = build_synthetic_graph(spec, np.random.Generator(np.random.PCG64(5)))
        g2 = build_synthetic_graph(spec, np.random.Generator(np.random.PCG64(5)))
        assert list(g1.nodes(data=True)) == list(g2.nodes(data=True))
        assert list(g1.edges(data=True, keys=True)) == list(
            g2.edges(data=True, keys=True),
        )

    def test_labels_are_controlled_tokens(self) -> None:
        graph = make_graph()
        for _node, data in graph.nodes(data=True):
            label = str(data["label"])
            assert label.startswith("tok_")
            assert data["privacy"] == "public_synthetic"

    def test_edge_capacity_validated(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            GraphSpecConfig(node_count=3, edge_count=10)


class TestReplaySelection:
    def test_selected_ids_and_contributions_consistent(self) -> None:
        scheduler = ReplayEventScheduler(
            make_graph(),
            ReplaySelectorConfig(top_k=3),
            rng=np.random.Generator(np.random.PCG64(3)),
        )
        selection = scheduler.select(tick=0, stage="N2")
        ids = selection["selected_node_ids"]
        assert len(ids) == 3
        contrib_ids = [row["node_id"] for row in selection["contributions"]]
        assert sorted(contrib_ids) == sorted(ids)
        for row in selection["contributions"]:
            total = sum(
                row[k]
                for k in (
                    "activation_share",
                    "recency_share",
                    "salience_share",
                    "stage_share",
                    "novelty_share",
                )
            )
            assert total == pytest.approx(1.0, abs=1e-9)

    def test_deterministic_same_seed(self) -> None:
        def run() -> tuple[str, ...]:
            scheduler = ReplayEventScheduler(
                make_graph(),
                ReplaySelectorConfig(),
                rng=np.random.Generator(np.random.PCG64(9)),
            )
            return scheduler.select(tick=4, stage="REM")["selected_node_ids"]

        assert run() == run()

    def test_rejected_prefixes_match_candidates(self) -> None:
        graph = make_graph()
        scheduler = ReplayEventScheduler(
            graph,
            ReplaySelectorConfig(top_k=3),
            rng=np.random.Generator(np.random.PCG64(3)),
        )
        selection = scheduler.select(tick=0, stage="Wake")
        n_nodes = graph.number_of_nodes()
        assert len(selection["rejected_ids_sha256_prefixes"]) == n_nodes - 3
        node_prefixes = {hashlib.sha256(n.encode()).hexdigest()[:8] for n in graph.nodes}
        assert set(selection["rejected_ids_sha256_prefixes"]) <= node_prefixes

    def test_policy_reason_records_configuration(self) -> None:
        scheduler = ReplayEventScheduler(
            make_graph(),
            ReplaySelectorConfig(novelty_weight_enabled=False),
            rng=np.random.Generator(np.random.PCG64(3)),
        )
        reason = str(scheduler.select(tick=0, stage="Wake")["policy_reason"])
        assert "novelty=off" in reason

    def test_non_public_node_rejected(self) -> None:
        graph = make_graph()
        first = sorted(graph.nodes)[0]
        graph.nodes[first]["privacy"] = "local_sensitive"
        with pytest.raises(ValueError, match="public_synthetic"):
            ReplayEventScheduler(
                graph,
                ReplaySelectorConfig(),
                rng=np.random.Generator(np.random.PCG64(1)),
            )


class TestGraphSerializer:
    def test_round_trip_lossless(self) -> None:
        graph = make_graph()
        payload = GraphSerializerV1.serialize(graph)
        restored = GraphSerializerV1.deserialize(payload)
        assert GraphSerializerV1.serialize(restored) == payload

    def test_version_mismatch_refused(self) -> None:
        payload = GraphSerializerV1.serialize(make_graph())
        payload["version"] = "memory-graph-v0"
        with pytest.raises(ValueError, match="version"):
            GraphSerializerV1.deserialize(payload)
