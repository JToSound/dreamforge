"""Engine determinism, stream isolation, and event-store units."""

from __future__ import annotations

import pytest

from dreamforge.simulation.engine import InMemoryEventStore, derive_stream


class TestEventStore:
    def test_append_strict_sequence(self) -> None:
        from dreamforge.core.models.events import NeurochemicalStatePayload, make_event

        def ev(seq: int):
            return make_event(
                run_id="run-12345678",
                event_type="neurochemical_state",
                event_sequence=seq,
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

        store = InMemoryEventStore()
        store.append(ev(1))
        store.append(ev(2))
        with pytest.raises(ValueError, match="sequence"):
            store.append(ev(4))

    def test_first_event_must_be_sequence_one(self) -> None:
        from dreamforge.core.models.events import SleepStatePayload, make_event

        event = make_event(
            run_id="run-12345678",
            event_type="sleep_state",
            event_sequence=2,
            epoch_seconds=30.0,
            tick=0,
            source_component="x",
            schema_version="1.0",
            correlation_id="c",
            emitted_at="2026-08-24T21:00:00+00:00",
            payload=SleepStatePayload(
                stage="Wake",
                s_value=0.5,
                c_value=0.5,
                ticks_in_stage=1,
            ),
        )
        store = InMemoryEventStore()
        with pytest.raises(ValueError, match="expected 1"):
            store.append(event)


class TestStreamIsolation:
    def test_streams_are_distinct_per_component(self) -> None:
        s1 = [float(x) for x in derive_stream(42, "stage").uniform(0, 1, size=4)]
        c1 = [float(x) for x in derive_stream(42, "chemistry").uniform(0, 1, size=4)]
        assert s1 != c1

    def test_same_seed_same_stream(self) -> None:
        a = [float(x) for x in derive_stream(99, "replay").uniform(0, 1, size=4)]
        b = [float(x) for x in derive_stream(99, "replay").uniform(0, 1, size=4)]
        assert a == b

    def test_registry_ids_fixed(self) -> None:
        from dreamforge.core.models.events import COMPONENT_REGISTRY

        assert COMPONENT_REGISTRY == {
            "stage": 1,
            "chemistry": 2,
            "replay": 3,
            "synthetic_memory": 4,
            "ensemble": 5,
        }


class TestRunDeterminism:
    def test_identical_inputs_identical_hash_different_clock(
        self,
        demo_config,
        fixed_clock,
    ) -> None:
        from datetime import UTC, datetime

        from dreamforge.core.provenance.clock import FixedClock
        from dreamforge.simulation.engine import run_simulation

        r1 = run_simulation(demo_config, fixed_clock)
        other_clock = FixedClock(datetime(2030, 1, 1, tzinfo=UTC))
        r2 = run_simulation(demo_config, other_clock)
        assert r1.core_trace_hash == r2.core_trace_hash
        assert r1.manifest.manifest_hash() == r2.manifest.manifest_hash()

    def test_seed_change_changes_hash_legitimately(
        self,
        demo_config_dict,
        fixed_clock,
    ) -> None:
        from dreamforge.core.config import load_config
        from dreamforge.simulation.engine import run_simulation

        payload_a = dict(demo_config_dict)
        payload_b = dict(demo_config_dict)
        payload_b["run_seed"] = payload_a["run_seed"] + 1
        r_a = run_simulation(load_config(payload_a), fixed_clock)
        r_b = run_simulation(load_config(payload_b), fixed_clock)
        assert r_a.core_trace_hash != r_b.core_trace_hash

    def test_manifest_records_versions_and_policies(
        self,
        demo_config,
        fixed_clock,
    ) -> None:
        result = __import__(
            "dreamforge.simulation.engine",
            fromlist=["run_simulation"],
        ).run_simulation(demo_config, fixed_clock)
        manifest = result.manifest
        assert manifest.rng_contract_version == "dreamforge-rng-v1"
        assert manifest.canonicalization == {"name": "DQCJ-1", "test_vectors": "1"}
        assert "stage_process" in manifest.declared_policies
        transitions = manifest.declared_policies["stage_process"]["transitions"]
        for _src, row in sorted(transitions.items()):  # type: ignore[union-attr]
            total = sum(row.values())  # type: ignore[union-attr]
            assert abs(total - 1.0) < 1e-9

    def test_no_network_in_core_modules(self) -> None:
        """Static guard: core/simulation modules import no network clients."""
        import ast
        from pathlib import Path

        banned = {"socket", "http", "urllib", "requests", "httpx", "ftplib"}
        roots = [
            Path("src/dreamforge/core"),
            Path("src/dreamforge/simulation"),
        ]
        checked = 0
        for root in roots:
            for py in root.rglob("*.py"):
                tree = ast.parse(py.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            assert alias.name.split(".")[0] not in banned, py
                            checked += 1
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        root_name = (node.module or "").split(".")[0]
                        assert root_name not in banned, py
                        checked += 1
        assert checked > 20  # sanity: the scan actually saw imports
