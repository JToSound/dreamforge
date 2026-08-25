"""DreamForge experimental suite, round 2 — validity-threat closure.

Round 1 (scripts/experiment.py) listed four honest threats to validity. This
suite closes them:

E6 warmup timing stats : repeated timed runs after discarded warmups,
                         reporting min/median/p90/CV instead of single shots.
E7 formal GoF          : chi-square goodness-of-fit for stage fractions
                         against the ANALYTIC semi-Markov stationary
                         distribution (embedded-chain pi x mean dwell),
                         with a pure-Python chi2 p-value (no scipy).
E8 multi-point dwells  : the degenerate-corner finding applied - realistic
                         multi-point dwell priors verified against closed-
                         form expectations (mean dwell per stage, dwell-length
                         histogram GoF, cross-seed stochasticity restored).
E9 adversarial sweep   : near-deterministic matrices (epsilon 0.50 -> 0.97)
                         checked for invariant preservation and tracking of
                         the analytic stationary distribution.

Run: .venv/Scripts/python.exe scripts/experiment_round2.py [E6|E7|E8|E9 ...]
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dreamforge.core.config import load_config  # noqa: E402
from dreamforge.core.provenance.clock import FixedClock  # noqa: E402
from dreamforge.simulation.engine import run_simulation  # noqa: E402

STAGES = ("Wake", "N1", "N2", "N3", "REM")
CHANNELS = ("acetylcholine", "serotonin", "noradrenaline", "cortisol")
CLOCK = FixedClock(datetime(2026, 8, 24, tzinfo=UTC))

# Realistic multi-point dwell priors (mirrors examples/configs/demo_8h.json).
MULTIPOINT_DWELLS = {
    "Wake": {"min_epochs": 4, "weights": [0.4, 1.0, 1.6, 2.2], "max_dwell_epochs": 20},
    "N1": {"min_epochs": 2, "weights": [2.0, 1.2, 0.6], "max_dwell_epochs": 20},
    "N2": {"min_epochs": 6, "weights": [1.0, 1.8, 2.2, 1.6, 1.0, 0.6], "max_dwell_epochs": 30},
    "N3": {
        "min_epochs": 8,
        "weights": [1.2, 2.0, 2.4, 1.8, 1.2, 0.8, 0.5, 0.3],
        "max_dwell_epochs": 40,
    },
    "REM": {"min_epochs": 4, "weights": [0.6, 1.2, 1.8, 1.4, 1.0, 0.7], "max_dwell_epochs": 30},
}


def make_payload(ticks: int, seed: int, *, matrix=None, dwells=None) -> dict:
    if matrix is None:
        matrix = {
            s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
            for i, s in enumerate(STAGES)
        }
    if dwells is None:
        dwells = {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in STAGES}
    return {
        "schema_version": "1.0",
        "run_id": f"r2-{ticks}-{seed}",
        "run_seed": seed,
        "total_ticks": ticks,
        "transitions": {"probabilities": matrix},
        "dwells": dwells,
        "chemistry": {
            "baselines": {c: 0.5 for c in CHANNELS},
            "stage_modulation": {c: {s: 0.0 for s in STAGES} for c in CHANNELS},
            "circadian_gain": {c: 0.0 for c in CHANNELS},
        },
        "replay_policy": {
            "synthetic_graph": {"node_count": 50, "edge_count": 120},
            "selector": {"top_k": 3},
            "replay_every_n_epochs": 5,
        },
    }


def run(payload: dict):
    return run_simulation(load_config(payload), CLOCK)


# --- statistics helpers (pure python; no scipy) --------------------------------


def chi2_sf(x: float, df: int) -> float:
    """Survival function of the chi-square distribution (regularized Q)."""
    if x <= 0.0:
        return 1.0

    def _gser(a: float, xx: float) -> float:  # series for P(a,x)
        ap, summ, delta = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1.0
            delta *= xx / ap
            summ += delta
            if abs(delta) < abs(summ) * 1e-14:
                break
        return summ * math.exp(-xx + a * math.log(xx) - math.lgamma(a))

    def _gcf(a: float, xx: float) -> float:  # continued fraction for Q(a,x)
        tiny = 1e-300
        b, c, d = xx + 1.0 - a, 1.0 / tiny, 1.0 / (xx + 1.0 - a)
        h = d
        for i in range(1, 500):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            d = d if abs(d) > tiny else tiny
            c = b + an / c
            c = c if abs(c) > tiny else tiny
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < 1e-14:
                break
        return math.exp(-xx + a * math.log(xx) - math.lgamma(a)) * h

    a = df / 2.0
    xx = x / 2.0
    if xx < a + 1.0:
        p = _gser(a, xx)
        return max(0.0, min(1.0, 1.0 - p))
    q = _gcf(a, xx)
    return max(0.0, min(1.0, q))


def chi2_test(observed: list[float], expected: list[float]) -> dict:
    """Chi-square GoF with pooling of low-expected bins."""
    pairs = [(o, e) for o, e in zip(observed, expected, strict=True)]
    pooled_o = pooled_e = 0.0
    terms = []
    for o, e in pairs:
        if e < 5.0:
            pooled_o += o
            pooled_e += e
        else:
            terms.append((o, e))
    if pooled_e > 0.0:
        terms.append((pooled_o, pooled_e))
    stat = sum((o - e) ** 2 / e for o, e in terms)
    dof = len(terms) - 1
    return {
        "chi2": round(stat, 4),
        "dof": dof,
        "p_value": round(chi2_sf(stat, dof), 6),
        "bins_used": len(terms),
        "pooled_bins": len(pairs) - len([t for t in pairs if t[1] >= 5.0]),
    }


def embedded_stationary(matrix: dict[str, dict[str, float]]) -> dict[str, float]:
    """Left-eigenvector (power iteration) of the row-stochastic matrix."""
    order = sorted(STAGES)
    dim = len(order)
    p_mat = np.array([[matrix[s][t] for t in order] for s in order], dtype=float)
    vec = np.full(dim, 1.0 / dim)
    for _ in range(20_000):
        nxt = vec @ p_mat
        nxt /= nxt.sum()
        if np.max(np.abs(nxt - vec)) < 1e-15:
            vec = nxt
            break
        vec = nxt
    return {s: float(vec[i]) for i, s in enumerate(order)}


def mean_dwell(dwell_spec: dict) -> float:
    weights = dwell_spec["weights"]
    total = sum(weights)
    support = [dwell_spec["min_epochs"] + k for k in range(len(weights))]
    return (
        dwell_spec["min_epochs"]
        + sum((k - dwell_spec["min_epochs"]) * w for k, w in zip(support, weights, strict=True))
        / total
    )


def time_weighted_stationary(
    matrix: dict[str, dict[str, float]],
    dwells: dict[str, dict],
) -> dict[str, float]:
    """Semi-Markov stationary occupancy: pi_emb(s)*mean_dwell(s), normalized."""
    emb = embedded_stationary(matrix)
    raw = {s: emb[s] * mean_dwell(dwells[s]) for s in STAGES}
    z = sum(raw.values())
    return {s: r / z for s, r in raw.items()}


def stage_epoch_fractions(events) -> dict[str, float]:
    counts = {s: 0 for s in STAGES}
    total = 0
    for event in events:
        if event.event_type == "sleep_state":
            counts[str(event.payload.stage)] += 1
            total += 1
    return {s: counts[s] / total for s in STAGES}, total


# --- E6: warmup timing statistics ------------------------------------------------


def e6_timing() -> dict:
    def timed(ticks: int) -> float:
        t0 = time.perf_counter()
        run(make_payload(ticks, 42))
        return time.perf_counter() - t0

    results = {}
    for label, ticks, warmups, repeats in (("small_960", 960, 3, 15), ("large_9600", 9600, 1, 7)):
        for _ in range(warmups):
            timed(ticks)
        samples = sorted(timed(ticks) for _ in range(repeats))
        med = statistics.median(samples)
        results[label] = {
            "warmup_runs_discarded": warmups,
            "repeats": repeats,
            "min_s": round(samples[0], 4),
            "median_s": round(med, 4),
            "p90_s": round(samples[int(math.ceil(0.9 * repeats)) - 1], 4),
            "max_s": round(samples[-1], 4),
            "cv_percent": (
                round(100.0 * statistics.stdev(samples) / statistics.fmean(samples), 2)
                if repeats > 1
                else 0.0
            ),
        }
    return results


# --- E7: formal GoF against analytic stationary ----------------------------------


def e7_formal_gof() -> dict:
    matrix = {
        s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
        for i, s in enumerate(STAGES)
    }
    dwells = {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in STAGES}
    ticks = 19_200
    result = run(make_payload(ticks, 2024, matrix=matrix, dwells=dwells))
    fractions, n_epochs = stage_epoch_fractions(result.events)

    pi_time = time_weighted_stationary(matrix, dwells)
    gof = chi2_test(
        [fractions[s] * n_epochs for s in STAGES],
        [pi_time[s] * n_epochs for s in STAGES],
    )
    return {
        "config": f"uniform matrix, single-point dwells, {ticks} epochs",
        "analytic_pi_time": {s: round(pi_time[s], 5) for s in STAGES},
        "observed_fractions": {s: round(fractions[s], 5) for s in STAGES},
        "max_abs_deviation_pp": round(
            100.0 * max(abs(fractions[s] - pi_time[s]) for s in STAGES), 3
        ),
        "chi2_gof_vs_analytic": gof,
        "interpretation_note": "p>0.05 means observations consistent with analytic distribution",
    }


# --- E8: multi-point dwells (applying the degenerate-corner finding) --------------


def e8_multipoint_dwells() -> dict:
    matrix = {
        s: {t: (0.25 if i != j else 0.0) for j, t in enumerate(STAGES)}
        for i, s in enumerate(STAGES)
    }
    ticks = 28_800

    # 8a: cross-seed stochasticity restored?
    transition_counts = []
    for seed in range(9100, 9120):
        result = run(make_payload(ticks // 30, seed, matrix=matrix, dwells=MULTIPOINT_DWELLS))
        transition_counts.append(
            sum(1 for e in result.events if e.event_type == "stage_transition")
        )
    stdev = statistics.stdev(transition_counts)

    # 8b: mean completed dwell per stage vs closed form.
    result = run(make_payload(ticks, 777, matrix=matrix, dwells=MULTIPOINT_DWELLS))
    sums: dict[str, list[int]] = {s: [] for s in STAGES}
    hist: dict[str, dict[int, int]] = {s: {} for s in STAGES}
    for event in result.events:
        if event.event_type == "stage_transition":
            src = str(event.payload.from_stage)
            completed = int(event.payload.completed_dwell_epochs)
            sums[src].append(completed)
            hist[src][completed] = hist[src].get(completed, 0) + 1

    per_stage_gof = {}
    for stage in STAGES:
        spec = MULTIPOINT_DWELLS[stage]
        expected_mean = mean_dwell(spec)
        observed_mean = statistics.fmean(sums[stage]) if sums[stage] else 0.0
        n_from = len(sums[stage])
        support = list(range(spec["min_epochs"], spec["min_epochs"] + len(spec["weights"])))
        weights = spec["weights"]
        total_w = sum(weights)
        expected_counts = [n_from * (w / total_w) for w in weights]
        observed_counts = [float(hist[stage].get(k, 0)) for k in support]
        per_stage_gof[stage] = {
            "n_transitions_from_stage": n_from,
            "closed_form_mean_dwell": round(expected_mean, 3),
            "observed_mean_dwell": round(observed_mean, 3),
            "abs_error_epochs": round(abs(observed_mean - expected_mean), 3),
            "histogram_chi2_gof": chi2_test(observed_counts, expected_counts),
        }

    return {
        "config": f"demo-style multi-point dwells, uniform matrix, {ticks}-epoch main run",
        "cross_seed_transition_counts": {
            "members": len(transition_counts),
            "mean": round(statistics.fmean(transition_counts), 1),
            "stdev": round(stdev, 2),
            "stochastic_now": stdev > 0.0,
        },
        "per_stage_dwell_verification": per_stage_gof,
    }


# --- E9: adversarial near-deterministic sweep -------------------------------------


def e9_adversarial_sweep() -> list[dict]:
    epsilons = (0.50, 0.85, 0.97)
    targets = ("N3", "REM", "Wake")
    rows = []
    for epsilon, target in zip(epsilons, targets, strict=True):
        matrix = {}
        for src in STAGES:
            dst_target = "N2" if src == "N3" and target == "N3" else target
            if src == dst_target:
                dst_target = next(t for t in STAGES if t not in (src, target))
            others = [t for t in STAGES if t != src and t != dst_target]
            rest = (1.0 - epsilon) / len(others)
            matrix[src] = {
                t: (epsilon if t == dst_target else (0.0 if t == src else rest)) for t in STAGES
            }
            assert abs(sum(matrix[src].values()) - 1.0) < 1e-9
        dwells = {s: {"min_epochs": 1, "weights": [1.0], "max_dwell_epochs": 8} for s in STAGES}
        ticks = 19_200
        result = run(make_payload(ticks, 31337, matrix=matrix, dwells=dwells))
        fractions, n_epochs = stage_epoch_fractions(result.events)
        pi_time = time_weighted_stationary(matrix, dwells)
        seqs_ok = True
        seqs = [e.event_sequence for e in result.events]
        if seqs != list(range(1, len(seqs) + 1)):
            seqs_ok = False
        chem_ok = all(
            0.0 <= float(getattr(e.payload, ch)) <= 1.0
            for e in result.events
            if e.event_type == "neurochemical_state"
            for ch in CHANNELS
        )
        rows.append(
            {
                "epsilon_to_target": epsilon,
                "target": target,
                "invariants_hold": bool(seqs_ok and chem_ok),
                "events": len(result.events),
                "observed_target_fraction_pp": round(100.0 * fractions[target], 2),
                "analytic_pi_time_target_pp": round(100.0 * pi_time[target], 2),
                "chi2_gof_vs_analytic": chi2_test(
                    [fractions[s] * n_epochs for s in STAGES],
                    [pi_time[s] * n_epochs for s in STAGES],
                ),
            },
        )
    return rows


FAMILIES = {
    "E6": e6_timing,
    "E7": e7_formal_gof,
    "E8": e8_multipoint_dwells,
    "E9": e9_adversarial_sweep,
}


def main(argv: list[str]) -> int:
    wanted = argv or list(FAMILIES)
    out: dict[str, object] = {}
    for family in wanted:
        print(f"running {family} ...", flush=True)
        out[family] = FAMILIES[family]()
        print(json.dumps(out[family], indent=2)[:900], flush=True)

    (REPO / "exports").mkdir(exist_ok=True)
    target = REPO / "exports" / "_experiment_results.json"
    existing: dict = {}
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
    existing.update({f"round2_{k}": v for k, v in out.items()})
    existing["_meta"] = {
        "python": sys.version.split()[0],
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    target.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"\nraw -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
