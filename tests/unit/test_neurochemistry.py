"""Neurochemical proxy units (section 5.2)."""

from __future__ import annotations

import pytest

from dreamforge.core.models.neurochemistry import (
    NeurochemicalProxyModel,
    NeurochemistryConfig,
)

CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")


def make_config(**overrides: object) -> NeurochemistryConfig:
    payload = {
        "baselines": dict.fromkeys(CHANNELS, 0.5),
        "stage_modulation": {
            c: dict.fromkeys(("Wake", "N1", "N2", "N3", "REM"), 0.0) for c in CHANNELS
        },
        "circadian_gain": dict.fromkeys(CHANNELS, 0.0),
    }
    payload.update(overrides)
    return NeurochemistryConfig.model_validate(payload)


class TestBoundsAndOrder:
    def test_values_bounded_finite(self) -> None:
        model = NeurochemicalProxyModel(make_config())
        for stage in ("Wake", "N1", "N2", "N3", "REM"):
            out = model.step(tick=0, stage=stage, c_value=0.7)
            assert set(out) == set(CHANNELS)
            for value in out.values():
                assert 0.0 <= value <= 1.0

    def test_transform_then_clip_single_terminal(self) -> None:
        # baseline 0.9 + modulation +0.5 would be 1.4 -> clipped exactly to 1.
        cfg = make_config(
            baselines=dict.fromkeys(CHANNELS, 0.9),
            stage_modulation={
                c: {**dict.fromkeys(("Wake", "N1", "N2", "N3", "REM"), 0.0), "REM": 0.5}
                for c in CHANNELS
            },
        )
        out = NeurochemicalProxyModel(cfg).step(0, "REM", 0.0)
        assert all(out[c] == 1.0 for c in CHANNELS)

    def test_clip_floor_at_zero(self) -> None:
        cfg = make_config(baselines=dict.fromkeys(CHANNELS, 0.05))
        cfg = make_config(
            baselines={c: (0.0 if c == "cortisol" else 0.5) for c in CHANNELS},
            stage_modulation={
                c: {**dict.fromkeys(("Wake", "N1", "N2", "N3", "REM"), -0.25)} for c in CHANNELS
            },
        )
        out = NeurochemicalProxyModel(cfg).step(0, "N3", 0.0)
        assert out["cortisol"] == 0.0

    def test_circadian_term_applied_before_clip(self) -> None:
        gains = dict.fromkeys(CHANNELS, 0.0)
        gains["acetylcholine"] = 0.5
        cfg = make_config(circadian_gain=gains)
        out = NeurochemicalProxyModel(cfg).step(0, "Wake", c_value=0.6)
        assert out["acetylcholine"] == pytest.approx(0.8)
        assert out["serotonin"] == pytest.approx(0.5)

    def test_nonfinite_c_value_rejected(self) -> None:
        model = NeurochemicalProxyModel(make_config())
        with pytest.raises(ValueError, match="finite"):
            model.step(0, "Wake", float("nan"))


class TestConfigValidation:
    def test_missing_channel_rejected(self) -> None:
        baselines = dict.fromkeys(CHANNELS, 0.5)
        del baselines["cortisol"]
        with pytest.raises(ValueError, match="channels"):
            make_config(baselines=baselines)

    def test_missing_stage_row_rejected(self) -> None:
        mod = {c: dict.fromkeys(("Wake", "N1", "N2", "N3", "REM"), 0.0) for c in CHANNELS}
        del mod["serotonin"]["N3"]
        with pytest.raises(ValueError, match="cover stages"):
            make_config(stage_modulation=mod)

    def test_nonfinite_baseline_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_config(
                baselines={c: (float("inf") if c == "serotonin" else 0.5) for c in CHANNELS},
            )
