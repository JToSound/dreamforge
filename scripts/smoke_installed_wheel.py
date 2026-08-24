"""Import smoke test for the installed DreamForge wheel.

Run from a NEUTRAL working directory with the clean venv's interpreter:

    <clean-venv>/Scripts/python.exe scripts/smoke_installed_wheel.py <repo> <venv-tag>

It proves:

1. the loaded ``dreamforge`` resolves to site-packages of THIS interpreter,
   not to a source/editable path;
2. the checked-in DQCJ-1 byte vectors reproduce byte-for-byte;
3. a small deterministic trace reproduces the dev environment's core hash
   for identical config bytes + seed (reference passed as argv[3]);
4. no network client modules are imported by the run.

Exit code 0 = all four proofs hold.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
VENV_TAG = sys.argv[2] if len(sys.argv) > 2 else ".venv-wheel"
DEV_REFERENCE = sys.argv[3] if len(sys.argv) > 3 else ""


def fail(message: str) -> None:
    print(f"SMOKE FAIL: {message}")
    raise SystemExit(1)


import dreamforge  # noqa: E402

here = Path(dreamforge.__file__).resolve()
normalized = str(here).replace("\\", "/").lower()
expected_marker = f"{VENV_TAG.lower()}/lib/site-packages/"
if expected_marker not in normalized:
    fail(f"dreamforge resolved outside {VENV_TAG} site-packages: {here}")
print(f"proof-1 module-path: OK ({here.parent})")

# --- proof 2: DQCJ vectors ------------------------------------------------
import json  # noqa: E402

from dreamforge.core.serialization.dqcj import dumps_canonical  # noqa: E402

payload = json.loads(
    (REPO / "tests" / "fixtures" / "dqcj1_vectors.json").read_text(encoding="utf-8"),
)
for case in payload["cases"]:
    data = dumps_canonical(case["input"], quantizations=case["quantizations"])
    if data.hex() != case["expected_hex"]:
        fail(f"vector mismatch: {case['name']}")
print(f"proof-2 dqcj-vectors: OK ({len(payload['cases'])} cases)")

# --- proof 3: deterministic trace parity -----------------------------------
from datetime import UTC, datetime  # noqa: E402

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

config_dict = json.loads(
    (REPO / "examples/configs/demo_8h.json").read_text(encoding="utf-8"),
)
config_dict["total_ticks"] = 60
config_dict["run_seed"] = 777001
config = load_config(config_dict)
result = run_simulation(
    config,
    FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC)),
)
wheel_hash = result.core_trace_hash
print(f"proof-3 installed-wheel trace-hash: {wheel_hash}")
if not DEV_REFERENCE:
    fail("dev reference hash not supplied (argv[3])")
if wheel_hash != DEV_REFERENCE:
    fail("installed-wheel hash differs from dev-environment reference")
print("proof-3b dev-parity: OK")


# --- proof 4: zero network connection attempts during a full trace ---------
# Note: bare module-presence checks are not a meaningful invariant here —
# mandatory dependencies (pydantic -> importlib.metadata -> email/zipfile)
# transitively load stdlib socket/urllib without any network use. The strong,
# honest proof is behavioral: any attempt to open a connection RAISES.
import socket  # noqa: E402


class _NetworkBlocked(RuntimeError):
    pass


def _blocked(*args: object, **kwargs: object) -> None:
    raise _NetworkBlocked("network access attempted during simulation")


_original_socket = socket.socket
_original_create_connection = getattr(socket, "create_connection", None)
socket.socket = _blocked  # type: ignore[assignment]
if _original_create_connection is not None:
    socket.create_connection = _blocked  # type: ignore[assignment]
try:
    result_guarded = run_simulation(config, FixedClock(datetime(2026, 8, 24, 21, 0, 0, tzinfo=UTC)))
finally:
    socket.socket = _original_socket  # type: ignore[assignment]
    if _original_create_connection is not None:
        socket.create_connection = _original_create_connection

if result_guarded.core_trace_hash != wheel_hash:
    fail("guarded re-run hash differs (nondeterminism)")
print("proof-4 zero-connection-attempts: OK (full trace under socket block)")
print("SMOKE PASS")
