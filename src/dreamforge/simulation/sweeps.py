"""Deterministic parameter sweeps over counterfactual pairs (M4, §5.5).

A sweep is an explicit, ordered grid of single-field variations applied to one
base configuration. Every cell is a full :class:`CounterfactualComparison`
with the same §1.2 labeling and model-conditional disclaimer. Cell order is
the sorted tuple of override keys — documented and stable, so identical grids
produce byte-identical sweep results.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from dreamforge.core.config import SimulationConfig
from dreamforge.core.provenance.clock import Clock
from dreamforge.core.serialization.dqcj import dumps_canonical
from dreamforge.simulation.counterfactual import (
    DISCLAIMER,
    CounterfactualError,
    CounterfactualSpec,
    run_counterfactual,
)

MECHANISTIC_LABEL = "Simulated model proxy — not a biological measurement"


class SweepCell(BaseModel):
    """One executed grid cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_id: str
    field: str
    value: Any
    comparison_json_sha256: str


class ParameterSweepResult(BaseModel):
    """Complete labeled result of one sweep execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_class: str = "mechanistic_proxy"
    visible_label: str = MECHANISTIC_LABEL
    disclaimer: str = DISCLAIMER
    base_run_id: str
    cells: tuple[SweepCell, ...]
    comparisons: tuple[dict[str, Any], ...]

    def to_canonical_bytes(self) -> bytes:
        """DQCJ-1 canonical bytes of the whole sweep result."""
        return dumps_canonical(self.model_dump())


class ParameterSweep:
    """Deterministic grid executor over single-field counterfactuals."""

    MAX_CELLS = 64

    def __init__(
        self,
        base_config: SimulationConfig,
        grid: dict[str, tuple[Any, ...]],
        *,
        seed_shift_per_cell: int = 0,
    ) -> None:
        """Freeze the base config and the declared grid.

        ``grid`` maps field name -> tuple of values (each value becomes one
        cell). Empty grids are refused; grids exceeding ``MAX_CELLS`` total
        cells are refused to keep runtime bounded.
        """
        if not grid:
            msg = "sweep grid must contain at least one field with values"
            raise CounterfactualError(msg)
        for field_name, values in grid.items():
            if not values:
                msg = f"grid field {field_name!r} has no values"
                raise CounterfactualError(msg)
        total = 1
        for values in grid.values():
            total *= len(values)
        if total > self.MAX_CELLS:
            msg = f"sweep would execute {total} cells, cap is {self.MAX_CELLS}"
            raise CounterfactualError(msg)
        self._base = base_config
        self._grid = {name: tuple(values) for name, values in sorted(grid.items())}
        self._seed_shift = int(seed_shift_per_cell)

    def _cells(self) -> list[tuple[str, Any]]:
        """Enumerate cells in documented order: field-sorted, then value order."""
        cells: list[tuple[str, Any]] = []
        for field_name in sorted(self._grid):
            for value in self._grid[field_name]:
                cells.append((field_name, value))
        return cells

    def run(self, clock: Clock) -> ParameterSweepResult:
        """Execute every cell deterministically."""
        comparisons: list[dict[str, Any]] = []
        cells_meta: list[SweepCell] = []
        for index, (field_name, value) in enumerate(self._cells()):
            spec = CounterfactualSpec(
                base_config=self._base,
                override_fields={field_name: value},
                seed_shift=self._seed_shift,
            )
            comparison = run_counterfactual(spec, clock)
            payload = comparison.model_dump()
            canonical = dumps_canonical(payload)
            cells_meta.append(
                SweepCell(
                    cell_id=f"cell-{index:03d}-{field_name}",
                    field=field_name,
                    value=value,
                    comparison_json_sha256=hashlib_sha256(canonical),
                ),
            )
            comparisons.append(payload)
        return ParameterSweepResult(
            base_run_id=self._base.run_id,
            cells=tuple(cells_meta),
            comparisons=tuple(comparisons),
        )


def hashlib_sha256(data: bytes) -> str:
    """SHA-256 hex digest helper kept local for clarity."""
    import hashlib

    return hashlib.sha256(data).hexdigest()
