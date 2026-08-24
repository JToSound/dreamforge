"""DQCJ-1 — DreamForge Quantized Canonical JSON, version 1 (ADR 0002).

Normative rules (MASTER_PROMPT.md section 4.3):

1. Inputs must already be schema-validated models or plain JSON-compatible
   containers; this module re-validates structurally.
2. NaN, infinities, duplicate keys (at the parsing boundary via
   :func:`loads_strict`), unsupported/ambiguous types, and unpaired surrogates
   are rejected with typed errors.
3. Strings are emitted NFC-normalized; an input whose NFC form differs is
   rejected unless the ingestion boundary passed ``require_nfc=False``
   (output is still normalized either way).
4. Object keys are sorted by Unicode code-point order (``sorted`` on ``str``).
5. Arrays keep schema-defined (insertion) order; JSON objects are produced
   from Python dicts whose insertion order is irrelevant because of rule 4.
6. Quantization applies ONLY to fields declared in a quantization registry
   (dotted paths, ``*`` array wildcard), via ``Decimal`` ``ROUND_HALF_EVEN``.
   Undeclared plain floats serialize as-is; *ambiguous implicit conversions*
   (Decimal, numpy scalars, Fraction, ...) are rejected outright. All zeros
   (including ``-0.0``) serialize as ``0.0`` to remove sign-of-zero ambiguity.
7. UTF-8 output with ``,``/``:`` separators and ``ensure_ascii=False``;
   ``allow_nan=False`` as a second line of defense.
8. NDJSON records terminate with exactly one ``\n``.

Version identifiers are recorded in run manifests.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

CANONICALIZATION_NAME = "DQCJ-1"
TEST_VECTOR_VERSION = "1"

#: Hard structural limits enforced at the parsing boundary (section 6.3).
MAX_JSON_DEPTH = 64


class DQCJError(ValueError):
    """Base error for all canonicalization failures."""


class DQCJTypeError(DQCJError):
    """A value of unsupported or ambiguous type was encountered."""


class DQCJFloatError(DQCJError):
    """NaN or infinity reached the canonical boundary."""


class DQCJNormalizationError(DQCJError):
    """A string changed under NFC normalization without ingest opt-in."""


class DQCJEncodingError(DQCJError):
    """A string contains unpaired surrogates and cannot encode to UTF-8."""


class DQCIDuplicateKeyError(DQCJError):
    """Duplicate object keys were found while strict-parsing text."""


def _quantize(value: float, quantum: str) -> float:
    """Quantize ``value`` to ``quantum`` (e.g. ``"0.000001"``), HALF_EVEN."""
    if value != value or value in (float("inf"), float("-inf")):
        msg = f"non-finite float cannot be quantized: {value!r}"
        raise DQCJFloatError(msg)
    return float(Decimal(repr(value)).quantize(Decimal(quantum), rounding=ROUND_HALF_EVEN))


def _check_string(value: str, *, require_nfc: bool) -> str:
    """Validate encodability/NFC and return the NFC-normalized string."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = "string contains unpaired surrogates"
        raise DQCJEncodingError(msg) from exc
    normalized = unicodedata.normalize("NFC", value)
    if require_nfc and normalized != value:
        msg = (
            "string is not NFC-normalized; pass require_nfc=False only at the " "ingestion boundary"
        )
        raise DQCJNormalizationError(msg)
    return normalized


def _transform(
    obj: Any,
    *,
    path: str,
    quantizations: Mapping[str, str],
    require_nfc: bool,
    matched: set[str],
    depth: int = 0,
) -> Any:
    """Recursively validate/normalize/quantize; returns the transformed copy."""
    if depth > MAX_JSON_DEPTH:
        msg = f"nesting exceeds MAX_JSON_DEPTH={MAX_JSON_DEPTH} at {path!r}"
        raise DQCJError(msg)
    if obj is None or isinstance(obj, bool):
        return obj
    # bool is an int subclass; exact-type checks keep numpy scalars out.
    if isinstance(obj, int) and type(obj) is int:
        return obj
    if isinstance(obj, float):
        if type(obj) is not float:
            msg = f"ambiguous float subtype rejected at {path!r}: {type(obj).__name__}"
            raise DQCJTypeError(msg)
        if obj != obj or obj in (float("inf"), float("-inf")):
            msg = f"non-finite float rejected at {path!r}"
            raise DQCJFloatError(msg)
        if obj == 0.0:
            # Rule 6a: all zeros (incl. -0.0) serialize identically as 0.0,
            # removing sign-of-zero ambiguity from hashes.
            return 0.0
        quantum = quantizations.get(path)
        if quantum is not None:
            matched.add(path)
            return _quantize(obj, quantum)
        return obj
    if isinstance(obj, str):
        return _check_string(obj, require_nfc=require_nfc)
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for key, val in obj.items():
            if not isinstance(key, str):
                msg = f"object key at {path!r} is not a string: {key!r}"
                raise DQCJTypeError(msg)
            child_path = f"{path}.{key}" if path else key
            out[key] = _transform(
                val,
                path=child_path,
                quantizations=quantizations,
                require_nfc=require_nfc,
                matched=matched,
                depth=depth + 1,
            )
        return out
    if isinstance(obj, (list, tuple)):
        return [
            _transform(
                item,
                path=f"{path}.*",
                quantizations=quantizations,
                require_nfc=require_nfc,
                matched=matched,
                depth=depth + 1,
            )
            for item in obj
        ]
    msg = (
        f"unsupported type at {path!r}: {type(obj).__name__} "
        "(implicit numeric conversions are forbidden)"
    )
    raise DQCJTypeError(msg)


def assert_quantization_paths_covered(
    obj: Any,
    quantizations: Mapping[str, str],
) -> None:
    """Raise unless every declared quantization path hit at least one float.

    Used by the engine so that a renamed payload field can never silently drop
    out of the declared quantization contract.
    """
    matched: set[str] = set()
    _transform(
        obj,
        path="",
        quantizations=quantizations,
        require_nfc=True,
        matched=matched,
    )
    missing = sorted(set(quantizations) - matched)
    if missing:
        msg = f"declared quantization paths matched no floats: {missing}"
        raise DQCJError(msg)


def transform_canonical(
    obj: Any,
    *,
    quantizations: Mapping[str, str] | None = None,
    require_nfc: bool = True,
) -> Any:
    """Validate/normalize/quantize ``obj`` and return the transformed copy.

    Public entry point used both by :func:`dumps_canonical` and by the engine,
    which applies declared quantizations to payload floats *at event creation
    time* so that payload hashes are stable independent of low-order float
    noise.
    """
    quant = dict(quantizations) if quantizations else {}
    return _transform(
        obj,
        path="",
        quantizations=quant,
        require_nfc=require_nfc,
        matched=set(),
    )


def dumps_canonical(
    obj: Any,
    *,
    quantizations: Mapping[str, str] | None = None,
    require_nfc: bool = True,
) -> bytes:
    """Serialize ``obj`` to DQCJ-1 canonical UTF-8 JSON bytes."""
    transformed = transform_canonical(
        obj,
        quantizations=quantizations,
        require_nfc=require_nfc,
    )
    text = json.dumps(
        transformed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """object_pairs_hook that refuses duplicate keys deterministically."""
    seen: dict[str, Any] = {}
    for key, val in pairs:
        if key in seen:
            msg = f"duplicate object key detected: {key!r}"
            raise DQCIDuplicateKeyError(msg)
        seen[key] = val
    return seen


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        msg = f"JSON nesting exceeds MAX_JSON_DEPTH={MAX_JSON_DEPTH}"
        raise DQCJError(msg)
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1)


def _reject_constant(name: str) -> Any:
    msg = f"non-finite JSON constant rejected: {name}"
    raise DQCJFloatError(msg)


def loads_strict(text: str | bytes) -> Any:
    """Strict JSON parser: no duplicate keys, no NaN/Infinity, depth-capped."""
    parsed = json.loads(
        text,
        object_pairs_hook=_reject_pairs,
        parse_constant=_reject_constant,
    )
    _check_depth(parsed)
    return parsed


def ndjson_bytes(records: Iterable[Mapping[str, Any]], **kwargs: Any) -> bytes:
    """Concatenate canonical records as NDJSON, each ending in one ``\\n``."""
    chunks = [dumps_canonical(record, **kwargs) for record in records]
    if not chunks:
        return b""
    return b"".join(chunk + b"\n" for chunk in chunks)


def sha256_of_concat(chunks: Iterable[bytes]) -> str:
    """SHA-256 hex digest over the concatenation of ``chunks``."""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()
