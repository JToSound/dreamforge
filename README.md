# DreamForge AI

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

An open-source, deterministic, offline sandbox for simulating explicit,
configurable, **non-clinical proxies** related to sleep regulation, sleep-stage
dynamics, normalized neuromodulatory patterns, synthetic-memory graph
selection, and structured dream-context features — under active construction
toward the milestone plan in [`MASTER_PROMPT.md`](MASTER_PROMPT.md).

## Status

First execution slice + M1 (complete) and M2 groundwork: deterministic core with
an 8-hour (960 × 30 s epoch) offline trace, event sourcing, DQCJ-1 canonical
serialization, hash-verified exports, structured dream context/features/score,
and the mandatory offline narrative provider with labeled report blocks. See
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`RESEARCH.md`](RESEARCH.md),
[`LIMITATIONS.md`](LIMITATIONS.md), and `docs/`.

**Not yet built** (by explicit scope control): API, plugins, notebooks,
Anthropic-native adapter shape.

## Optional: local / OpenAI-compatible narrative provider (opt-in)

The offline mock is always the default. To use a local model via Ollama's
OpenAI-compatible endpoint (or any `/chat/completions` service), construct the
adapter explicitly in your own script — nothing is enabled by configuration
alone:

```python
from dreamforge.core.providers.narrative import NarrativeRequest
from dreamforge.integrations.openai_compat import OpenAICompatConfig, OpenAICompatProvider
from dreamforge.integrations.transport import UrllibTransport

config = OpenAICompatConfig(
    base_url="http://127.0.0.1:11434/v1",  # Ollama loopback example
    model="llama3.2:3b",
    timeout_seconds=20,
    max_retries=2,
)
provider = OpenAICompatProvider(config, UrllibTransport())
response = provider.generate(request)  # request = validated NarrativeRequest
```

Guarantees (ADR 0005): allowlisted projection only; strict response schema;
per-attempt timeout; bounded retries then fail-closed; errors redacted to
status code + response hash; every response labeled `generative_interpretation`.

## Dashboard (optional extras)

```bash
".venv/Scripts/python.exe" -m pip install -c constraints.txt streamlit plotly
".venv/Scripts/python.exe" -m streamlit run src/dreamforge/visualization/dashboard.py -- exports/demo_8h
```

Renders verified exports only; accessibility/theme documentation in
[`DASHBOARD.md`](DASHBOARD.md).

## What it simulates (and what that means)

- Conceptual two-process-inspired sleep-regulation equations (homeostatic "S"
  pressure + sinusoidal circadian proxy) — mathematical constructs, not physiology.
- A semi-Markov Wake/N1/N2/N3/REM stage process at 30-second resolution —
  explicitly *not* PSG scoring.
- Four normalized `[0,1]` neuromodulatory proxy indices — qualitative synthetic
  values, never concentrations or measurements.
- Selection over a synthetic directed weighted memory graph — graph selection,
  not neural replay.
- Deterministic structured features and scores derived only from the above.

All parameters carry evidence grades (`assumption`, `synthetic_demo`, …) in
[`docs/scientific_model/claim_registry.yaml`](docs/scientific_model/claim_registry.yaml).
No empirical or clinical claim is made anywhere in this repository.

## Quick start (offline demo)

Requires Python 3.11+ (developed on 3.12, Windows). No network egress at runtime;
install needs PyPI once.

```bash
python -m venv .venv
".venv/Scripts/python.exe" -m pip install -c constraints.txt -e .   # Windows path; use .venv/bin elsewhere
".venv/Scripts/python.exe" -m dreamforge.demo                       # runs examples/configs/demo_8h.json
```

The demo validates its configuration, runs 960 epochs, verifies stage-transition
legality, writes an export under `exports/demo_8h/`
(`events.ndjson` + `manifest.json`), re-imports it, and re-verifies all hashes.

## Development checks

```bash
".venv/Scripts/python.exe" -m pytest -q                                            # tests
".venv/Scripts/python.exe" -m pytest -q --cov=src/dreamforge --cov-report=term-missing
".venv/Scripts/python.exe" -m ruff check src tests examples                        # lint
".venv/Scripts/python.exe" -m black --check src tests examples                     # format-check
".venv/Scripts/python.exe" -m mypy src/dreamforge/core                             # typecheck
```

## Repository layout

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the diagram and component table.

## License

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 JToSound.
