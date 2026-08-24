"""Generate DQCJ-1 byte-level test vectors from the current implementation.

The generated file is checked in; the test suite asserts the implementation
still reproduces these exact bytes. Re-run this generator ONLY with a
deliberate spec change plus an ADR note.

Usage:
    ".venv/Scripts/python.exe" scripts/generate_dqcj_vectors.py
"""

from __future__ import annotations

import json
from pathlib import Path

from dreamforge.core.serialization.dqcj import dumps_canonical

OUT = Path("tests/fixtures/dqcj1_vectors.json")


def main() -> None:
    """Write canonical byte vectors observed from real execution."""
    cases = []

    def add(name: str, obj: object, quant: dict[str, str] | None = None) -> None:
        data = dumps_canonical(obj, quantizations=quant or {})
        cases.append(
            {
                "name": name,
                "input": obj,
                "quantizations": quant or {},
                "expected_hex": data.hex(),
            },
        )

    add("key_sort_codepoint", {"z": 1, "a": 2, "Z": 3, "A": 4, "0": 5})
    add("array_order_preserved", [3, 1, 2])
    add("quant_half_even_down", {"v": 0.1234565}, {"v": "0.000001"})
    add("quant_half_even_up", {"v": 0.1234575}, {"v": "0.000001"})
    add("quant_array_wildcard", {"rows": [{"x": 1.2345649}]}, {"rows.*.x": "0.000001"})
    add("float_plain_and_negative_zero", {"p": 0.1, "q": 1.5e-07, "n": -0.0})
    add("unicode_literal_utf8", {"s": "café"})
    add("bool_and_null", {"t": True, "f": False, "n": None})
    add("empty_containers", {"e": [], "m": {}})

    payload = {
        "canonicalization": "DQCJ-1",
        "test_vector_version": "1",
        "note": (
            "Byte-level vectors generated from a verified execution; "
            "regenerated only with a deliberate specification change."
        ),
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(cases)} cases")


if __name__ == "__main__":
    main()
