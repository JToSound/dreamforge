# RESEARCH.md — Scientific model and claims

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

## Evidence status overview

| Feature | Evidence status | Model type | User-facing label | Limitation |
|---|---|---|---|---|
| Process S homeostatic proxy | No empirical source verified; `assumption` | Deterministic exponential approach equations | Simulated model proxy — not a biological measurement | Conceptual construct; parameters are assumptions, not fitted physiology |
| Circadian proxy C(t) | No empirical source verified; `assumption` | Sum of two sinusoids (2nd harmonic off by default) | Simulated model proxy — not a biological measurement | Phase/amplitude are configuration, not measurements |
| Stage transitions (Wake/N1/N2/N3/REM) | No empirical source verified; `synthetic_demo` | Semi-Markov with bounded integer-epoch dwell distributions | Simulated model proxy — not a biological measurement | 30 s resolution simulation policy; explicitly not PSG scoring |
| Neuromodulatory proxies (ACh/5-HT/NE/cortisol) | No empirical source verified; `assumption` | Baseline + stage lookup + optional circadian term, transform-then-clip | Simulated model proxy — not a biological measurement | Dimensionless [0,1] indices only; never concentrations |
| Synthetic memory graph | Not applicable (synthetic input) | Directed weighted NetworkX graph over controlled tokens | Simulated model proxy — not a biological measurement | Labels are synthetic tokens; no real memories ever |
| Replay selection | Not applicable (policy, not biology) | Weighted normalized contribution formula | Interpretive output — not a scientific inference | Graph selection ≠ neural replay; NREM preference is a declared probabilistic policy |
| Bizarreness/context features | Deferred to M2 | Deterministic structured features over selected IDs | Simulated model proxy — not a biological measurement | Not built in this slice; will ship with evidence-variable specs |

Every public scientific claim is enumerated in
[`docs/scientific_model/claim_registry.yaml`](docs/scientific_model/claim_registry.yaml)
with: claim ID; exact wording; implementation/equation/parameter mapping;
source key; evidence grade; population/context; limitation; validation status;
owner/review date.

**Citation policy.** No bibliographic citation key exists yet because none has
been verified against checked metadata supporting an exact claim
(MASTER_PROMPT.md §5). A source may be added only after its bibliographic
metadata *and* the precise supported claim have been verified; reviews do not
justify numerical parameters unless the review itself states that number for a
compatible population/context.

**Validation plan.** This sandbox is not intended for biological validation.
"Validation" here means: internal consistency (bounds, legal transitions,
hash determinism) — tested continuously; sensitivity demonstrations in example
notebooks at M4 — labeled as simulations only. Human calibration claims are
prohibited permanently.

## Equations implemented this slice

1. Wake: $S_{t+\Delta t}=S_{max}-(S_{max}-S_t)\,e^{-\Delta t/\tau_{wake}}$
2. Sleep: $S_{t+\Delta t}=S_{min}+(S_t-S_{min})\,e^{-\Delta t/\tau_{sleep}}$
3. Circadian: $C(t)=b+A\sin\!\big(2\pi(t-\phi)/T\big)+A_2\sin\!\big(4\pi(t-\phi_2)/T\big)$,
   second harmonic disabled by default ($A_2=0$).
4. Chemistry: $\text{proxy}_{c,t}=\operatorname{clip}\big(\text{base}_c+
   m_{c,\text{stage}}+a_c\cdot C(t),\,0,\,1\big)$ — transform order documented:
   sum terms first, then clip once to [0,1].
5. Replay score: normalized contributions
   $\tilde{x}_k=x_k/\sum_j x_j$ per enabled factor (activation, recency,
   salience, stage bonus), weighted sum with declared weights, deterministic
   tie-break by node ID ordering.

Sign conventions, unit conversion (tick × epoch_seconds → simulated minutes),
update order within an epoch, bounds/clipping order, and boundary behaviour are
documented in the corresponding module docstrings and enforced by tests.
