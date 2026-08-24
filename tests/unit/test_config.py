"""Configuration loading negatives (fail-closed validation)."""

from __future__ import annotations

import pytest

from dreamforge.core.config import ConfigError, load_config


class TestConfigAcceptance:
    def test_demo_dict_loads(self, demo_config_dict: dict) -> None:
        config = load_config(demo_config_dict)
        assert config.total_ticks == 960
        assert config.epoch_seconds == 30.0


class TestConfigRejections:
    def test_bad_seed_type_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["run_seed"] = "not-an-int"
        with pytest.raises(ConfigError, match="validation"):
            load_config(demo_config_dict)

    def test_negative_seed_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["run_seed"] = -1
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_oversized_seed_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["run_seed"] = 2**65
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_zero_ticks_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["total_ticks"] = 0
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_unknown_stage_transition_rejected(self, demo_config_dict: dict) -> None:
        row = demo_config_dict["transitions"]["probabilities"]["Wake"]
        row["N9"] = 0.1
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_row_not_summing_to_one_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["transitions"]["probabilities"]["REM"]["Wake"] = 0.9
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_missing_dwell_stage_rejected(self, demo_config_dict: dict) -> None:
        del demo_config_dict["dwells"]["REM"]
        with pytest.raises(ConfigError, match="missing stages"):
            load_config(demo_config_dict)

    def test_extra_key_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["mystery_option"] = True
        with pytest.raises(ConfigError):
            load_config(demo_config_dict)

    def test_duplicate_json_keys_rejected(self, tmp_path: object) -> None:
        from pathlib import Path

        path = Path(str(tmp_path)) / "dup.json"
        path.write_text('{"schema_version":"1.0","schema_version":"1.1"}', encoding="utf-8")
        with pytest.raises(ConfigError, match="duplicate"):
            load_config(path)

    def test_unreadable_file_typed_error(self, tmp_path: object) -> None:
        from pathlib import Path

        missing = Path(str(tmp_path)) / "nope.json"
        with pytest.raises(ConfigError) as excinfo:
            load_config(missing)
        assert excinfo.value.code == "config_unreadable"

    def test_epoch_out_of_bounds_rejected(self, demo_config_dict: dict) -> None:
        demo_config_dict["epoch_seconds"] = 7200.0
        with pytest.raises(ConfigError, match="epoch_seconds"):
            load_config(demo_config_dict)
