"""Degenerate dwell-distribution detection units (experiment follow-up)."""

from __future__ import annotations

import pytest

from dreamforge.core.models.sleep_cycle import (
    DwellDistribution,
    config_dwell_degeneracy,
    dwell_distribution_is_degenerate,
)


def dwell(weights: tuple[float, ...], min_epochs: int = 1, cap: int = 8) -> DwellDistribution:
    return DwellDistribution(min_epochs=min_epochs, weights=weights, max_dwell_epochs=cap)


class TestDegeneracyDetection:
    def test_single_point_prior_is_degenerate(self) -> None:
        assert dwell_distribution_is_degenerate(dwell((1.0,)))

    def test_single_point_with_dead_tail_is_degenerate(self) -> None:
        # Zero weights beyond the single positive mass still degenerate.
        assert dwell_distribution_is_degenerate(dwell((1.0, 0.0, 0.0)))

    def test_multi_point_prior_not_degenerate(self) -> None:
        assert not dwell_distribution_is_degenerate(dwell((1.0, 2.0)))

    def test_two_equal_masses_not_degenerate(self) -> None:
        assert not dwell_distribution_is_degenerate(dwell((0.5, 0.5)))

    @pytest.mark.parametrize("weights", [(1e-12,), (3.7,)])
    def test_any_single_positive_mass_is_degenerate(self, weights: tuple[float, ...]) -> None:
        assert dwell_distribution_is_degenerate(dwell(weights))

    def test_min_epochs_does_not_affect_degeneracy(self) -> None:
        # min_epochs shifts the support but the mass structure decides.
        assert dwell_distribution_is_degenerate(dwell((1.0,), min_epochs=4))
        assert not dwell_distribution_is_degenerate(dwell((1.0, 1.0), min_epochs=4))

    def test_config_map_sorted_and_complete(self) -> None:
        dwells = {
            "REM": dwell((1.0,)),
            "Wake": dwell((1.0, 2.0)),
            "N3": dwell((5.0,)),
        }
        result = config_dwell_degeneracy(dwells)
        assert list(result) == ["N3", "REM", "Wake"]  # sorted
        assert result == {"N3": True, "REM": True, "Wake": False}

    def test_default_demo_weights_are_non_degenerate(self) -> None:
        from dreamforge.core.models.sleep_cycle import DEFAULT_DWELL_WEIGHTS

        for stage, weights in DEFAULT_DWELL_WEIGHTS.items():
            assert not dwell_distribution_is_degenerate(
                dwell(weights),
            ), f"default {stage} weights unexpectedly degenerate"
