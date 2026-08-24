"""RunRepository + theme recurrence units (M4 completion)."""

from __future__ import annotations

import pytest

from dreamforge.simulation.run_repository import (
    JsonFileRunRepository,
    RepositoryError,
    StoredNightRecord,
    ThemeRecurrenceReport,
    theme_recurrence,
)


def record(run_id: str, night: int, tokens: tuple[str, ...]) -> StoredNightRecord:
    safe_id = f"night-{run_id}" if len(run_id) < 4 else run_id
    return StoredNightRecord(
        run_id=safe_id,
        night_index=night,
        core_trace_hash="a" * 64,
        total_ticks=40,
        selected_token_ids=tokens,
        stage_sequence=("Wake", "N2", "REM"),
    )


class TestRepository:
    def test_round_trip_canonical(self, tmp_path) -> None:
        repo = JsonFileRunRepository(tmp_path / "nights")
        original = record("night-0001", 0, ("tok_01", "tok_02"))
        repo.save(original)
        loaded = repo.load("night-0001")
        assert loaded == original
        # stored bytes are canonical: rewriting yields identical bytes
        path = tmp_path / "nights" / "night-0001.night.json"
        first = path.read_bytes()
        repo.save(original)
        assert path.read_bytes() == first

    def test_list_and_load_all_sorted(self, tmp_path) -> None:
        repo = JsonFileRunRepository(tmp_path / "nights")
        repo.save(record("b-run", 1, ()))
        repo.save(record("a-run", 0, ()))
        assert repo.list_run_ids() == ["a-run", "b-run"]
        ordered = [r.run_id for r in repo.load_all()]
        assert ordered == ["a-run", "b-run"]  # by night_index

    def test_missing_load_returns_none(self, tmp_path) -> None:
        repo = JsonFileRunRepository(tmp_path / "nights")
        assert repo.load("never-saved") is None

    def test_bad_id_refused(self, tmp_path) -> None:
        repo = JsonFileRunRepository(tmp_path / "nights")
        with pytest.raises(RepositoryError, match="pattern"):
            repo.load("../escape")

    def test_traversal_refused_typed(self, tmp_path) -> None:
        repo = JsonFileRunRepository(tmp_path / "nights")
        with pytest.raises(RepositoryError) as excinfo:
            repo.load("..%2F..%2Fevil")
        assert excinfo.value.code in ("run_id_invalid", "path_traversal_refused")


class TestThemeRecurrence:
    def test_counts_distinct_nights_not_repeats(self) -> None:
        nights = [
            record("n1", 0, ("tok_a", "tok_b", "tok_a")),
            record("n2", 1, ("tok_a",)),
            record("n3", 2, ("tok_c",)),
        ]
        report = theme_recurrence(nights)
        assert report.nights_analyzed == 3
        recurring_ids = [entry.token_id for entry in report.recurring_tokens]
        assert recurring_ids == ["tok_a"]  # tok_b/c appear on one night only
        entry = report.recurring_tokens[0]
        assert entry.nights_present == 2
        assert entry.first_night_index == 0

    def test_min_nights_filter(self) -> None:
        nights = [record("n1", 0, ("tok_x",)), record("n2", 1, ("tok_x",))]
        assert len(theme_recurrence(nights).recurring_tokens) == 1
        assert len(theme_recurrence(nights, min_nights=3).recurring_tokens) == 0

    def test_ordering_count_desc_then_id(self) -> None:
        nights = [
            record("n1", 0, ("b_tok", "a_tok", "c_tok")),
            record("n2", 1, ("b_tok", "a_tok")),
            record("n3", 2, ("b_tok",)),
            record("n4", 3, ("c_tok",)),
        ]
        report = theme_recurrence(nights)
        order = [(e.token_id, e.nights_present) for e in report.recurring_tokens]
        assert order == [("b_tok", 3), ("a_tok", 2), ("c_tok", 2)]

    def test_deterministic_bytes_and_labels(self) -> None:
        nights = [record("n1", 0, ("t1",)), record("n2", 1, ("t1", "t2"))]

        def build() -> bytes:
            return theme_recurrence(nights).to_canonical_bytes()

        report = theme_recurrence(nights)
        assert isinstance(report, ThemeRecurrenceReport)
        assert build() == build()
        assert report.output_class == "mechanistic_proxy"

    def test_empty_records(self) -> None:
        report = theme_recurrence([])
        assert report.nights_analyzed == 0
        assert report.recurring_tokens == ()
