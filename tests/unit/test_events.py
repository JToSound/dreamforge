"""Event envelope, ID derivation, and manifest units (section 4.2, ADR 0002)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dreamforge.core.models.events import (
    NAMESPACE_DREAMFORGE_EVENT,
    NeurochemicalStatePayload,
    SleepStatePayload,
    compute_event_id,
    make_event,
    payload_hash_bytes,
)


def build_payload(**overrides: object) -> SleepStatePayload:
    values = {
        "stage": "Wake",
        "s_value": 0.5,
        "c_value": 0.5,
        "ticks_in_stage": 3,
    }
    values.update(overrides)
    return SleepStatePayload(**values)  # type: ignore[arg-type]


class TestEventId:
    def test_derivation_matches_spec(self) -> None:
        payload = build_payload()
        digest = payload_hash_bytes(payload.model_dump())
        expected = compute_event_id("run-12345678", "sleep_state", 1, digest)
        event = make_event(
            run_id="run-12345678",
            event_type="sleep_state",
            event_sequence=1,
            tick=0,
            epoch_seconds=30.0,
            source_component="sleep_regulation",
            schema_version="1.0",
            correlation_id="corr-1",
            emitted_at="2026-08-24T21:00:00+00:00",
            payload=payload,
        )
        assert event.event_id == expected

    def test_sequence_changes_id(self) -> None:
        payload = build_payload()
        kwargs = {
            "run_id": "run-12345678",
            "event_type": "sleep_state",
            "epoch_seconds": 30.0,
            "tick": 0,
            "source_component": "x",
            "schema_version": "1.0",
            "correlation_id": "c",
            "emitted_at": "2026-08-24T21:00:00+00:00",
            "payload": payload,
        }
        e1 = make_event(event_sequence=1, **kwargs)
        e2 = make_event(event_sequence=2, **kwargs)
        assert e1.event_id != e2.event_id

    def test_timestamp_does_not_change_payload_hash_or_id(self) -> None:
        payload = build_payload()
        common = {
            "run_id": "run-12345678",
            "event_type": "sleep_state",
            "event_sequence": 1,
            "epoch_seconds": 30.0,
            "tick": 4,
            "source_component": "x",
            "schema_version": "1.0",
            "correlation_id": "c",
            "payload": payload,
        }
        a = make_event(emitted_at="2026-08-24T21:00:00+00:00", **common)
        b = make_event(emitted_at="2030-01-01T00:00:00+00:00", **common)
        assert a.event_id == b.event_id

    def test_naive_emitted_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_event(
                run_id="run-12345678",
                event_type="sleep_state",
                event_sequence=1,
                epoch_seconds=30.0,
                tick=0,
                source_component="x",
                schema_version="1.0",
                correlation_id="c",
                emitted_at="2026-08-24T21:00:00",
                payload=build_payload(),
            )

    def test_frozen_envelope_and_payload(self) -> None:
        event = make_event(
            run_id="run-12345678",
            event_type="neurochemical_state",
            event_sequence=1,
            epoch_seconds=30.0,
            tick=0,
            source_component="x",
            schema_version="1.0",
            correlation_id="c",
            emitted_at="2026-08-24T21:00:00+00:00",
            payload=NeurochemicalStatePayload(
                acetylcholine=0.5,
                serotonin=0.5,
                noradrenaline=0.5,
                cortisol=0.5,
            ),
        )
        with pytest.raises(ValidationError):
            event.tick = 99  # type: ignore[misc]

    def test_simulated_time_conversion(self) -> None:
        event = make_event(
            run_id="run-12345678",
            event_type="sleep_state",
            event_sequence=1,
            epoch_seconds=30.0,
            tick=7,
            source_component="x",
            schema_version="1.0",
            correlation_id="c",
            emitted_at="2026-08-24T21:00:00+00:00",
            payload=build_payload(),
        )
        assert event.simulated_time_minutes == pytest.approx(3.5)

    def test_namespace_is_documented_constant(self) -> None:
        import uuid

        assert NAMESPACE_DREAMFORGE_EVENT == uuid.UUID(
            "7d444842-7fb0-4ae1-9d43-e8ddae0a4d67",
        )
