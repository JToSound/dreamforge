"""DreamForge offline dashboard (Streamlit) — M3, gated by ADR 0004.

Renders VERIFIED exports only: every load runs the full fail-closed import
verification first. No simulator or provider code executes here.

Run:  streamlit run src/dreamforge/visualization/dashboard.py -- <export_dir>

DreamForge is a research and visualization simulator. It does not measure
brains, diagnose conditions, predict dreams, infer psychological meaning, or
provide medical advice.
"""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from dreamforge.visualization.loader import ImportError_, LoadedExport, load_export  # noqa: E402

DISCLAIMER = (
    "DreamForge is a research and visualization simulator. It does not "
    "measure brains, diagnose conditions, predict dreams, infer psychological "
    "meaning, or provide medical advice."
)

MECHANISTIC_LABEL = "Simulated model proxy — not a biological measurement"
GENERATIVE_LABEL = "Generated interpretation — not a dream measurement or inference"

STAGE_ORDER = ["Wake", "N1", "N2", "N3", "REM"]
STAGE_Y = {stage: index for index, stage in enumerate(STAGE_ORDER)}
PROXY_COLORS = {
    "acetylcholine": "#1f77b4",
    "serotonin": "#2ca02c",
    "noradrenaline": "#d62728",
    "cortisol": "#9467bd",
}


def _stage_figure(loaded: LoadedExport) -> go.Figure:
    ticks = [tick for tick, _stage in loaded.stage_timeline]
    values = [STAGE_Y[stage] for _tick, stage in loaded.stage_timeline]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ticks,
            y=values,
            mode="lines+markers",
            line_shape="hv",
            name="Stage",
            marker=dict(size=4),
        ),
    )
    for tick in loaded.replay_ticks:
        fig.add_vline(x=tick, line_width=1, line_dash="dot", opacity=0.35)
    fig.update_yaxes(tickvals=list(range(len(STAGE_ORDER))), ticktext=STAGE_ORDER)
    return fig


def _proxy_figure(loaded: LoadedExport) -> go.Figure:
    ticks = list(range(len(loaded.proxy_timeline)))
    fig = go.Figure()
    for channel in ("acetylcholine", "serotonin", "noradrenaline", "cortisol"):
        fig.add_trace(
            go.Scatter(
                x=ticks,
                y=[row[channel] for row in loaded.proxy_timeline],
                mode="lines",
                name=channel,
                line=dict(color=PROXY_COLORS[channel]),
            ),
        )
    fig.update_yaxes(range=[-0.02, 1.02], title="normalized proxy [0,1]")
    return fig


def _export_candidates() -> list[Path]:
    """Resolve candidate export dirs: query param > CLI args > bundled default.

    Query parameters win so that hosted/tested contexts are deterministic even
    when the host process carries unrelated ``sys.argv`` content (e.g. pytest).
    """
    try:
        raw = str(st.query_params.get("export", ""))
    except Exception:  # pragma: no cover - bare mode
        raw = ""
    if raw:
        return [Path(part) for part in raw.split(",") if part]
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if args:
        return [Path(a) for a in args]
    return [Path("exports/demo_8h")]


def main() -> None:
    """Render the dashboard from resolved export paths."""
    candidates = _export_candidates()

    st.set_page_config(page_title="DreamForge — simulated traces", layout="wide")
    st.title("DreamForge trace viewer")
    st.caption(MECHANISTIC_LABEL)
    st.warning(DISCLAIMER, icon="⚠️")

    existing = [path for path in candidates if path.is_dir()]
    if not existing:
        st.error(
            "No readable export directory given. " "Run the demo first: python -m dreamforge.demo",
        )
        return

    chosen = st.sidebar.selectbox(
        "Export directory",
        existing,
        format_func=lambda p: str(p),
    )
    try:
        loaded = load_export(chosen)
    except ImportError_ as exc:
        st.error(f"Verification FAILED ({exc.code}): this export is not trustworthy.")
        st.stop()
    except Exception as exc:  # noqa: BLE001 - fail closed on ANY verification fault
        st.error(f"Verification FAILED ({type(exc).__name__}): this export is not trustworthy.")
        st.stop()

    verification_rows = [
        {"check": check["check"], "status": check["status"]} for check in loaded.verification.checks
    ]
    passed = all(row["status"] == "pass" for row in verification_rows)
    st.sidebar.metric("verification checks", len(verification_rows))
    st.sidebar.markdown(f"**all pass:** {'yes' if passed else 'NO'}")

    manifest = loaded.imported.manifest
    st.header(f"run `{manifest.run_id}`")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("epochs", manifest.event_count)
    col_b.metric("seed", manifest.run_seed)
    col_c.metric("trace hash", f"{manifest.core_trace_hash[:12]}…")

    st.subheader("Hypnogram-style stage timeline")
    st.caption(MECHANISTIC_LABEL + " · dotted vertical lines mark replay-selection epochs")
    st.plotly_chart(_stage_figure(loaded), use_container_width=True)

    st.subheader("Neuromodulatory proxy timeline")
    st.caption(MECHANISTIC_LABEL + " · dimensionless normalized indices, never concentrations")
    st.plotly_chart(_proxy_figure(loaded), use_container_width=True)

    report = loaded.imported.report
    if report is not None:
        st.subheader("Structured context features & score")
        feature_cols = st.columns(3)
        features = report.features_block.features
        for index, (name, value) in enumerate(sorted(features.items())):
            feature_cols[index % 3].metric(name.replace("_", " "), f"{value:.3f}")
        st.metric(
            "bizarreness score (0–100)",
            f"{report.features_block.score_bizarreness_0_100:.2f}",
            help=f"scorer {report.features_block.scorer_version}; weighted structured aggregate",
        )

        narrative = report.narrative
        if narrative is not None:
            st.subheader("Narrative block")
            st.info(
                f"[{narrative.output_class}] {GENERATIVE_LABEL}\n\n{narrative.text}",
                icon="📝",
            )

    with st.expander("Import verification result"):
        st.dataframe(verification_rows, hide_index=True)

    st.divider()
    st.caption(MECHANISTIC_LABEL + " · " + GENERATIVE_LABEL)


if __name__ == "__main__":
    main()
