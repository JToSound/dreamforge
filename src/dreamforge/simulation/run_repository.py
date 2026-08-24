"""RunRepository port and JSON-file implementation (§3.1, M4 persistence).

Multi-night synthetic persistence stores SMALL night summaries (never full
traces - exports already cover those). The repository lives OUTSIDE the core:
the deterministic core never touches the filesystem. Storage is canonical
DQCJ-1 bytes; listing is sorted; ids are validated against a strict pattern
and resolved paths must stay inside the repository root (path containment,
section 6.3).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from dreamforge.core.serialization.dqcj import dumps_canonical, loads_strict

MECHANISTIC_LABEL = "Simulated model proxy — not a biological measurement"

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{4,64}$")


class RepositoryError(ValueError):
    """Raised for repository violations; ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StoredNightRecord(BaseModel):
    """Small per-night summary sufficient for recurrence analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(pattern=r"^[A-Za-z0-9._-]{4,64}$")
    night_index: int = Field(ge=0)
    core_trace_hash: str = Field(min_length=64, max_length=64)
    total_ticks: int = Field(ge=1)
    selected_token_ids: tuple[str, ...]
    stage_sequence: tuple[str, ...]
    output_class: str = "mechanistic_proxy"
    visible_label: str = MECHANISTIC_LABEL


class RunRepository(Protocol):
    """Typed port for durable night records (implemented outside the core)."""

    def save(self, record: StoredNightRecord) -> None:
        """Persist one night record."""
        ...

    def load(self, run_id: str) -> StoredNightRecord | None:
        """Load one record by id; None when absent."""
        ...

    def list_run_ids(self) -> list[str]:
        """All stored ids in sorted order."""
        ...


class JsonFileRunRepository:
    """Canonical-bytes JSON file store rooted at one directory."""

    def __init__(self, root: Path) -> None:
        """Create the root if needed and remember its resolved path."""
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise RepositoryError("run_id_invalid", f"id fails pattern: {run_id!r}")
        candidate = (self._root / f"{run_id}.night.json").resolve()
        if self._root not in candidate.parents:
            raise RepositoryError(
                "path_traversal_refused",
                f"resolved path escapes repository root: {candidate}",
            )
        return candidate

    def save(self, record: StoredNightRecord) -> None:
        """Write canonical bytes atomically (temp + replace)."""
        path = self._path_for(record.run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(dumps_canonical(record.model_dump()))
        tmp.replace(path)

    def load(self, run_id: str) -> StoredNightRecord | None:
        """Load one record; missing files yield None."""
        path = self._path_for(run_id)
        if not path.is_file():
            return None
        payload = loads_strict(path.read_text(encoding="utf-8"))
        return StoredNightRecord.model_validate(payload)

    def list_run_ids(self) -> list[str]:
        """Sorted stored ids (by Unicode code point)."""
        return sorted(
            path.name[: -len(".night.json")]
            for path in self._root.glob("*.night.json")
            if path.is_file()
        )

    def load_all(self) -> list[StoredNightRecord]:
        """Every stored record ordered by (night_index, run_id)."""
        records = [self.load(run_id) for run_id in self.list_run_ids()]
        present = [record for record in records if record is not None]
        return sorted(present, key=lambda r: (r.night_index, r.run_id))


# --- theme recurrence (M4) ----------------------------------------------------


class TokenRecurrence(BaseModel):
    """Per-token cross-night appearance summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token_id: str
    nights_present: int
    first_night_index: int


class ThemeRecurrenceReport(BaseModel):
    """Deterministic cross-night recurring-token report.

    Counts only: which tokens appear across how many stored nights. No
    interpretation of 'meaning' is made anywhere.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = "mechanistic_proxy"
    visible_label: str = MECHANISTIC_LABEL
    nights_analyzed: int
    recurring_tokens: tuple[TokenRecurrence, ...]  # sorted by count desc, then id

    def to_canonical_bytes(self) -> bytes:
        """DQCJ-1 canonical bytes of the report."""
        return dumps_canonical(self.model_dump())


def theme_recurrence(
    records: list[StoredNightRecord],
    *,
    min_nights: int = 2,
) -> ThemeRecurrenceReport:
    """Compute which tokens appear on at least ``min_nights`` distinct nights.

    Evidence: each record's ``selected_token_ids`` set. Deterministic order:
    descending ``nights_present``, ties broken by token id (code points).
    """
    appearances: dict[str, set[int]] = {}
    first_seen: dict[str, int] = {}
    for record in records:
        for token_id in set(record.selected_token_ids):
            appearances.setdefault(token_id, set()).add(record.night_index)
            if token_id not in first_seen or record.night_index < first_seen[token_id]:
                first_seen[token_id] = record.night_index
    recurring = [
        TokenRecurrence(
            token_id=token_id,
            nights_present=len(night_set),
            first_night_index=first_seen[token_id],
        )
        for token_id, night_set in appearances.items()
        if len(night_set) >= min_nights
    ]
    recurring.sort(key=lambda entry: (-entry.nights_present, entry.token_id))
    return ThemeRecurrenceReport(
        nights_analyzed=len(records),
        recurring_tokens=tuple(recurring),
    )
