"""DQCJ-1 canonical serializer units and byte-level vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dreamforge.core.serialization.dqcj import (
    CANONICALIZATION_NAME,
    TEST_VECTOR_VERSION,
    DQCIDuplicateKeyError,
    DQCJEncodingError,
    DQCJFloatError,
    DQCJNormalizationError,
    DQCJTypeError,
    dumps_canonical,
    loads_strict,
    ndjson_bytes,
)

VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "dqcj1_vectors.json"


class TestByteVectors:
    """Checked-in byte-level vectors (regenerate only with an ADR)."""

    def test_reproduces_checked_in_vectors(self) -> None:
        payload = json.loads(VECTORS.read_text(encoding="utf-8"))
        assert payload["canonicalization"] == CANONICALIZATION_NAME
        assert payload["test_vector_version"] == TEST_VECTOR_VERSION
        for case in payload["cases"]:
            data = dumps_canonical(case["input"], quantizations=case["quantizations"])
            assert data.hex() == case["expected_hex"], case["name"]

    def test_negative_zero_serializes_as_positive(self) -> None:
        assert dumps_canonical({"n": -0.0}) == b'{"n":0.0}'
        assert dumps_canonical({"n": 0.0}) == dumps_canonical({"n": -0.0})


class TestRejections:
    """Typed rejections required by rule 2/3/6."""

    def test_nan_rejected(self) -> None:
        with pytest.raises(DQCJFloatError):
            dumps_canonical({"v": float("nan")})

    def test_infinity_rejected(self) -> None:
        with pytest.raises(DQCJFloatError):
            dumps_canonical({"v": float("inf")})

    def test_numpy_scalar_rejected(self) -> None:
        np = pytest.importorskip("numpy")
        with pytest.raises(DQCJTypeError):
            dumps_canonical({"v": np.float64(1.5)})

    def test_decimal_rejected(self) -> None:
        from decimal import Decimal

        with pytest.raises(DQCJTypeError):
            dumps_canonical({"v": Decimal("1.5")})

    def test_unpaired_surrogate_rejected(self) -> None:
        with pytest.raises(DQCJEncodingError):
            dumps_canonical({"s": "\ud800"})

    def test_non_nfc_string_rejected_without_opt_in(self) -> None:
        decomposed = "cafe\u0301"  # e + combining acute
        assert dumps_canonical({"s": decomposed}, require_nfc=False) == (b'{"s":"caf\xc3\xa9"}')
        with pytest.raises(DQCJNormalizationError):
            dumps_canonical({"s": decomposed})

    def test_duplicate_keys_rejected_on_parse(self) -> None:
        with pytest.raises(DQCIDuplicateKeyError):
            loads_strict('{"a":1,"a":2}')

    def test_nan_constant_rejected_on_parse(self) -> None:
        with pytest.raises(DQCJFloatError):
            loads_strict('{"a":NaN}')

    def test_depth_cap_enforced(self) -> None:
        deep = json.loads("[" * 70 + "]" * 70)
        from dreamforge.core.serialization.dqcj import MAX_JSON_DEPTH, DQCJError

        assert MAX_JSON_DEPTH < 70
        # Parsing succeeds structurally; transform rejects beyond the cap.
        with pytest.raises(DQCJError):
            dumps_canonical(deep)


class TestNdjson:
    def test_records_end_with_single_newline(self) -> None:
        data = ndjson_bytes([{"b": 1}, {"a": 2}])
        assert data == b'{"b":1}\n{"a":2}\n'

    def test_empty_sequence_is_empty_bytes(self) -> None:
        assert ndjson_bytes([]) == b""
