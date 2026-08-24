"""Bizarreness score: deterministic weighted feature aggregate (§5.4).

    B = 100 × clip(Σᵢ wᵢ·fᵢ, 0, 1),   wᵢ ≥ 0, Σwᵢ = 1

The score is a structured number over structured features — never prose, and
never a clinical or psychological measure. Weights are validated (non-negative,
sum-to-one) and recorded with the scorer version. An LLM rater
(``unvalidated_secondary_rater``) is NOT implemented; it stays disabled by
default per MASTER_PROMPT.md §5.4.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

#: Declared default weights for bizarreness-v1 (assumption-grade policy).
DEFAULT_BIZARRENESS_WEIGHTS: dict[str, float] = {
    "scene_discontinuity": 0.20,
    "entity_incongruity": 0.20,
    "causal_implausibility": 0.15,
    "temporal_distortion": 0.15,
    "identity_instability": 0.10,
    "memory_blending_entropy": 0.20,
}

SCORER_VERSION = "bizarreness-v1"


class BizarrenessWeights(BaseModel):
    """Validated non-negative sum-to-one weight vector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, float]

    @field_validator("values")
    @classmethod
    def _valid(cls, value: dict[str, float]) -> dict[str, float]:
        expected = set(DEFAULT_BIZARRENESS_WEIGHTS)
        if set(value) != expected:
            msg = f"weights must key exactly {sorted(expected)}"
            raise ValueError(msg)
        for name, weight in value.items():
            if not math.isfinite(weight) or weight < 0.0:
                msg = f"weight {name} must be finite and non-negative"
                raise ValueError(msg)
        total = sum(value.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            msg = f"weights sum to {total!r}, expected 1.0"
            raise ValueError(msg)
        return value


def score_bizarreness(
    features: Any,
    *,
    weights: dict[str, float] | None = None,
) -> tuple[float, float]:
    """Return ``(normalized_0_1, absolute_0_100)``.

    Clipping order (documented): the weighted sum is clipped once to [0, 1]
    before scaling to percentage points. Features must expose the six named
    attributes as finite floats in [0, 1]; violations raise ``ValueError``
    rather than being silently absorbed.
    """
    checked = BizarrenessWeights(
        values=dict(weights) if weights else dict(DEFAULT_BIZARRENESS_WEIGHTS),
    )
    weighted = 0.0
    for name in sorted(checked.values):
        raw = float(getattr(features, name))
        if not math.isfinite(raw) or not 0.0 <= raw <= 1.0:
            msg = f"feature {name} out of [0,1]: {raw!r}"
            raise ValueError(msg)
        weighted += checked.values[name] * raw
    normalized = min(max(weighted, 0.0), 1.0)  # single terminal clip
    return normalized, 100.0 * normalized


def quantize_score_for_export(absolute: float) -> float:
    """Quantize the 0–100 score to two decimals (declared export quantum)."""
    from decimal import ROUND_HALF_EVEN, Decimal

    return float(Decimal(repr(absolute)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
