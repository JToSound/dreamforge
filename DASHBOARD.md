# Dashboard — accessibility, theming, and startup (M3)

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

## One documented startup command

```bash
# 1) produce the bundled demo export if you do not have one:
".venv/Scripts/python.exe" -m dreamforge.demo

# 2) start the dashboard against an export directory:
".venv/Scripts/python.exe" -m streamlit run src/dreamforge/visualization/dashboard.py -- exports/demo_8h
```

Multiple export directories can be passed after `--`; they appear in the
sidebar selector. The dashboard renders **verified exports only** — loading
runs the full fail-closed import verification first; a failed verification
shows an error instead of charts.

## What is rendered

| View | Output class | Exact visible label |
|---|---|---|
| Stage timeline (hypnogram-style), replay markers | `mechanistic_proxy` | Simulated model proxy — not a biological measurement |
| Neuromodulatory proxy timeline | `mechanistic_proxy` | Simulated model proxy — not a biological measurement |
| Structured features & bizarreness score | `mechanistic_proxy` | Simulated model proxy — not a biological measurement |
| Narrative block (when present) | `generative_interpretation` | Generated interpretation — not a dream measurement or inference |

The page header, a persistent warning banner, and the footer all repeat the
mandatory disclaimer sentence. No view implies measurement of any person;
wording review is part of the test suite (`tests/unit/test_dashboard.py`).

## Color-vision review

- The stage timeline encodes stages by **vertical position with text labels on
  the axis** (Wake/N1/N2/N3/REM) — position, not hue, carries the information.
  Replay epochs are dotted vertical lines, distinguishable without color.
- Proxy channels use the Okabe–Ito-adjacent qualitative palette (blue/green/
  red/purple) AND direct text legends; each line is identified by name in the
  legend, so color-blind users can trace channels via labels.
- Status information ("all pass: yes/NO") uses text, never color alone.
- Charts include both line + marker shape redundancy where practical.

## Non-color encodings

- Stages: y-position + labeled ticks.
- Replay events: dashed vertical gridlines (pattern encoding).
- Channels: named legend entries + distinct line colors as reinforcement only.
- Metrics: numeric text values (never bar-length-only).

## Keyboard behaviour

Streamlit's rendered UI is standard HTML: sidebar selectbox, expander, and
tabs are reachable with Tab/Shift+Tab and operated with Enter/Space; Plotly
charts expose their own keyboard-navigable mode bar and static fallback data
via the underlying figure. No custom keyboard traps are introduced; no
pointer-only interactions exist.

## Light/dark theme behaviour

The app sets no hard-coded background/text colors; it inherits Streamlit's
theme (light/dark) from `.streamlit/config.toml` or the user's settings. All
text is rendered through theme-aware components; chart backgrounds default to
transparent so both themes remain legible. Verified in light and dark modes
via the smoke tests' DOM assertions where applicable.

## Data boundary

The loader (`src/dreamforge/visualization/loader.py`) imports only the
export/verification machinery — never the simulation engine or providers —
so rendering cannot execute simulation code. This is asserted by a
subprocess probe test (`ENGINE_NOT_LOADED`).
