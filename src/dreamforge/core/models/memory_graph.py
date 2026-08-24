"""Synthetic memory graph and replay-selection policy (section 5.3).

The graph is a directed weighted NetworkX MultiDiGraph over **controlled
synthetic tokens** (never diary or free text). Default input is synthetic
structured JSON only. Replay is *graph selection*, not neural firing: each
selection exposes normalized per-factor contributions, the candidate
population summary, privacy-safe rejected-ID hash prefixes, RNG stream
version, and a policy reason.

Edge direction semantics: an edge ``u -> v`` means "u's content is associated
toward v" (co-occurrence direction chosen at authoring time); selection scores
nodes, and edges contribute to a node via its incoming edges.

Determinism contract: node/edge iteration is always sorted by ID before any
sampling; all randomness flows through the injected Generator owned by the
engine's isolated ``replay`` stream.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import networkx as nx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_TYPES = (
    "episode",
    "person",
    "place",
    "object",
    "concept",
    "emotion",
    "sensory_cue",
)

PRIVACY_CLASSES = ("public_synthetic",)


class _ValidatedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


#: Replay factor weights (declared policy; exposed in exports).
DEFAULT_REPLAY_WEIGHTS = {
    "activation": 0.45,
    "recency": 0.20,
    "salience": 0.15,
    "stage": 0.10,
    "novelty": 0.10,
}

STAGE_BONUS = {
    # Declared probabilistic policy — hypothesis-tagged, not biology.
    "N2": {"episode": 0.6, "emotion": 0.4},
    "REM": {"emotion": 0.7, "sensory_cue": 0.5},
}


class GraphSpecConfig(_ValidatedModel):
    """Configuration for building the default synthetic demo graph."""

    node_count: int = Field(default=24, ge=2)
    edge_count: int = Field(default=48, ge=1)
    seed_token_prefix: str = "tok"

    @model_validator(mode="after")
    def _check(self) -> GraphSpecConfig:
        if self.edge_count > self.node_count * (self.node_count - 1):
            msg = "edge_count exceeds simple-digraph capacity"
            raise ValueError(msg)
        return self


class ReplaySelectorConfig(_ValidatedModel):
    """Validated replay policy: weights, budget, anti-repetition."""

    weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_REPLAY_WEIGHTS),
    )
    top_k: int = Field(default=3, ge=1)
    novelty_weight_enabled: bool = True
    recent_window: int = Field(default=12, ge=1)  # anti-repetition window
    min_candidates: int = Field(default=1, ge=1)

    @field_validator("weights")
    @classmethod
    def _weights_valid(cls, value: dict[str, float]) -> dict[str, float]:
        expected = set(DEFAULT_REPLAY_WEIGHTS)
        if set(value) != expected:
            msg = f"replay weights must key exactly {sorted(expected)}"
            raise ValueError(msg)
        for name, weight in value.items():
            if not math.isfinite(weight) or weight < 0.0:
                msg = f"weight {name} must be finite and non-negative"
                raise ValueError(msg)
        total = sum(value.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            msg = f"replay weights sum to {total!r}, expected 1.0"
            raise ValueError(msg)
        return value


class MemoryNodeState(_ValidatedModel):
    """Mutable-per-run state carried by a node (kept out of event payloads)."""

    activation: float = Field(default=0.0, ge=0.0, le=1.0)
    decay_rate_per_hour: float = Field(default=0.5, gt=0.0)
    last_replay_tick: int | None = None
    creation_tick: int = 0


def build_synthetic_graph(
    spec: GraphSpecConfig,
    rng: np.random.Generator,
) -> nx.MultiDiGraph:
    """Build the default synthetic token graph from an isolated RNG stream.

    Deterministic given ``(spec, rng state)``. Node IDs are zero-padded stable
    tokens; labels are controlled synthetic tokens only. Every node carries a
    ``privacy`` classification of ``public_synthetic``.
    """
    graph = nx.MultiDiGraph()
    width = len(str(spec.node_count - 1))
    types_cycle = NODE_TYPES
    for i in range(spec.node_count):
        node_id = f"{spec.seed_token_prefix}_{i:0{width}d}"
        graph.add_node(
            node_id,
            label=f"{node_id}#{types_cycle[i % len(types_cycle)]}",
            node_type=types_cycle[i % len(types_cycle)],
            privacy="public_synthetic",
            salience=round(float(rng.uniform(0.1, 1.0)), 6),
            creation_tick=0,
        )
    possible = [(a, b) for a in sorted(graph.nodes) for b in sorted(graph.nodes) if a != b]
    chosen = rng.choice(len(possible), size=spec.edge_count, replace=False)
    for idx in np.sort(np.asarray(chosen)):
        src, dst = possible[int(idx)]
        graph.add_edge(
            src,
            dst,
            relation="assoc",
            strength=round(float(rng.uniform(0.05, 1.0)), 6),
            recency=round(float(rng.uniform(0.0, 1.0)), 6),
            emotional_salience=round(float(rng.uniform(0.0, 1.0)), 6),
            cooccurrence=int(rng.integers(0, 5)),
            source_confidence=round(float(rng.uniform(0.5, 1.0)), 6),
        )
    return graph


class ReplayEventScheduler:
    """Weighted deterministic replay selection over the synthetic graph."""

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        config: ReplaySelectorConfig,
        rng: np.random.Generator,
        decay_half_life_epochs: float = 60.0,
    ) -> None:
        """Freeze graph/policy/stream; validate nodes minimally."""
        if graph.number_of_nodes() == 0:
            msg = "graph must contain at least one node"
            raise ValueError(msg)
        for node, data in graph.nodes(data=True):
            if data.get("privacy") != "public_synthetic":
                msg = f"node {node!r} lacks public_synthetic classification"
                raise ValueError(msg)
            if not isinstance(data.get("salience"), (int, float)):
                msg = f"node {node!r} missing numeric salience"
                raise ValueError(msg)
        self._graph = graph
        self._cfg = config
        self._rng = rng
        self._half_life = float(decay_half_life_epochs)
        self._state: dict[str, MemoryNodeState] = {
            node: MemoryNodeState() for node in sorted(graph.nodes)
        }
        self._recent: list[str] = []
        self._novelty: dict[str, float] = {}

    def _decay(self, tick: int) -> None:
        if tick <= 0:
            return
        factor = math.exp(-math.log(2.0) / max(self._half_life, 1e-9))
        # Frozen models are replaced, never mutated in place.
        for node, state in self._state.items():
            if state.activation != 0.0:
                self._state[node] = state.model_copy(
                    update={"activation": state.activation * factor},
                )

    def _incoming_strength(self, node: str) -> float:
        total = 0.0
        for _, _, data in self._graph.in_edges(node, data=True):
            total += float(data.get("strength", 0.0)) * float(
                data.get("emotional_salience", 0.0),
            )
        return total

    def select(
        self,
        tick: int,
        stage: str,
    ) -> dict[str, Any]:
        """Select up to ``top_k`` nodes this epoch.

        Returns a dict with ``selected_node_ids``, per-node contribution rows
        (each row's shares summing to ~1 across factors), candidate count,
        rejected-ID SHA-256 8-hex-char prefixes (privacy-safe), and a policy
        reason string. Zero-candidate behaviour: with a nonempty graph there
        is always >= 1 candidate, so selection never returns empty here;
        empty-graph construction is refused at init.
        """
        self._decay(tick)
        cfg = self._cfg
        candidates = sorted(self._graph.nodes)  # stable comparator
        n_cand = len(candidates)
        raw_scores: dict[str, float] = {}
        contrib_rows: list[dict[str, Any]] = []

        stage_bonus_map = STAGE_BONUS.get(stage, {})
        # Anti-repetition is carried by `novelty` (accumulating prior-selection
        # counts) rather than a hard window exclusion; both stay deterministic.

        for node in candidates:
            state = self._state[node]
            salience = float(self._graph.nodes[node]["salience"])
            incoming = self._incoming_strength(node)

            act_term = min(1.0, state.activation + 0.15 * salience + 0.05 * incoming)

            if state.last_replay_tick is None:
                age_epochs = float(tick)
            else:
                age_epochs = float(max(tick - state.last_replay_tick, 0))
            denom = 1.0 + age_epochs / max(cfg.recent_window, 1)
            rec_term = 1.0 / denom

            sal_term = salience

            type_bonus = stage_bonus_map.get(
                str(self._graph.nodes[node].get("node_type", "")),
                0.0,
            )
            stage_term = min(1.0, type_bonus)

            prior = self._novelty.get(node, 0.0)
            nov_term = 1.0 / (1.0 + 2.0 * prior)

            parts = {
                "activation": act_term,
                "recency": rec_term,
                "salience": sal_term,
                "stage": stage_term,
                "novelty": nov_term if cfg.novelty_weight_enabled else 0.0,
            }
            total_part = sum(parts.values())
            shares = {k: (v / total_part if total_part > 0 else 0.0) for k, v in parts.items()}
            score = sum(float(cfg.weights[k]) * shares[k] for k in parts)

            noise_scale = 0.02
            jitter = float(self._rng.normal(0.0, noise_scale))
            raw_scores[node] = max(score + jitter, 0.0)

            contrib_rows.append(
                {
                    "node_id": node,
                    "activation_share": shares["activation"],
                    "recency_share": shares["recency"],
                    "salience_share": shares["salience"],
                    "stage_share": shares["stage"],
                    "novelty_share": shares["novelty"],
                },
            )

        order = sorted(
            range(len(candidates)),
            key=lambda i: (-raw_scores[candidates[i]], candidates[i]),
        )
        k = min(cfg.top_k, n_cand)
        selected_idx = order[:k]
        selected = [candidates[i] for i in selected_idx]
        selected_set = set(selected)

        contributions = sorted(
            (contrib_rows[i] for i in range(len(candidates)) if candidates[i] in selected_set),
            key=lambda row: row["node_id"],
        )

        rejected_prefixes = tuple(
            hashlib.sha256(node.encode("utf-8")).hexdigest()[:8]
            for i, node in enumerate(candidates)
            if node not in selected_set
        )

        reason = (
            f"policy=weighted_contribution top_k={k} stage={stage} "
            f"window={cfg.recent_window} novelty={'on' if cfg.novelty_weight_enabled else 'off'}"
        )

        # State updates: activation boost on selection, novelty accumulation.
        # Frozen models are replaced, never mutated in place.
        for node in selected:
            st = self._state[node]
            boost = min(1.0, st.activation + 0.35)
            self._state[node] = st.model_copy(
                update={"last_replay_tick": tick, "activation": boost},
            )
            self._novelty[node] = self._novelty.get(node, 0.0) + 1.0
        self._recent.extend(selected)
        del self._recent[: -(max(cfg.recent_window * 4, 16))]

        return {
            "selected_node_ids": tuple(selected),
            "contributions": contributions,
            "candidate_count": n_cand,
            "rejected_ids_sha256_prefixes": rejected_prefixes,
            "policy_reason": reason,
        }

    def export_policy(self) -> dict[str, Any]:
        """Return declared policy for exports/tests."""
        return {
            "weights": dict(sorted(self._cfg.weights.items())),
            "top_k": self._cfg.top_k,
            "recent_window": self._cfg.recent_window,
            "novelty_enabled": self._cfg.novelty_weight_enabled,
            "decay_half_life_epochs": self._half_life,
            "stage_bonus": {s: dict(sorted(m.items())) for s, m in sorted(STAGE_BONUS.items())},
        }


class GraphSerializerV1:
    """Versioned lossless serializer for synthetic token graphs (JSON-safe)."""

    VERSION = "memory-graph-v1"

    @staticmethod
    def serialize(graph: nx.MultiDiGraph) -> dict[str, Any]:
        """Serialize nodes/edges losslessly into a plain dict."""
        nodes = []
        for node in sorted(graph.nodes):
            data = dict(graph.nodes[node])
            nodes.append({"id": node, **data})
        edges = []
        for u, v, keys, data in sorted(
            graph.edges(keys=True, data=True),
            key=lambda e: (e[0], e[1], str(e[2])),
        ):
            edges.append({"source": u, "target": v, "key": keys, **data})
        return {
            "version": GraphSerializerV1.VERSION,
            "directed": True,
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def deserialize(payload: dict[str, Any]) -> nx.MultiDiGraph:
        """Reconstruct a graph; refuses wrong versions or malformed shapes."""
        version = payload.get("version")
        if version != GraphSerializerV1.VERSION:
            msg = f"unsupported graph serializer version: {version!r}"
            raise ValueError(msg)
        graph = nx.MultiDiGraph()
        for node in payload["nodes"]:
            node_id = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            graph.add_node(node_id, **attrs)
        for edge in payload["edges"]:
            src, dst = edge["source"], edge["target"]
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target", "key")}
            key = edge.get("key", 0)
            graph.add_edge(src, dst, key=key, **attrs)
        if set(sorted(map(str, graph.nodes))) != set(
            sorted(str(n["id"]) for n in payload["nodes"]),
        ):
            msg = "lossless round-trip failed: node sets differ"
            raise ValueError(msg)
        return graph
