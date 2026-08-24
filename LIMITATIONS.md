# LIMITATIONS.md

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

DreamForge is a conceptual simulator of explicit assumptions. Know what it is
not:

1. **Population vs individual inference.** Any future parameter drawn from
   literature describes populations under specific contexts; nothing here
   models *you* or any individual brain.
2. **Unobserved variables.** Adenosine dynamics, orexin, thalamocortical
   activity, and essentially all real neurophysiology are unobserved and
   unmodelled; the proxies are deliberately crude mathematical constructs.
3. **Simulator vs PSG.** The stage process emits a simulated 30-second-resolution
   sequence from declared transition matrices and dwell distributions. It is
   not a hypnogram and must never be compared to clinical scoring as if
   equivalent.
4. **Normalized proxies vs concentrations.** The four chemistry outputs are
   dimensionless `[0,1]` indices shaped by lookup tables and sinusoids. They
   are never concentrations, samples, patient values, or pharmacokinetic
   predictions.
5. **Graph selection vs neural replay.** "Replay" here means weighted selection
   of nodes in a small synthetic graph by exposed formulas. It is not hippocampal
   replay and makes no claim about memory consolidation biology.
6. **LLM bias/hallucination.** No LLM provider exists in this slice. When they
   exist (later milestones), narratives will be labeled
   `generative_interpretation`, cloud adapters will be disabled by default, and
   provider output will never feed back into core state or scores.
7. **Synthetic data only.** The first release accepts only `public_synthetic`
   structured data with controlled token labels. Diary text, PII, health data,
   medication information, and wearable/EEG/PSG data are rejected at boundaries,
   not redacted after acceptance.
8. **Stochastic sensitivity.** Outputs depend on `run_seed`. Seed changes alter
   trajectories legitimately; only same-seed same-version replays are
   byte-comparable. Cross-platform byte identity is not promised.
9. **Platform/provider limits.** Determinism claims hold for identical package
   versions in one environment; floating-point behaviour across BLAS/platforms
   can differ and is not papered over.
10. **Pharmacology boundary.** No medication functionality exists. If fictional
    pharmacology scenarios arrive later, they will remain disabled by default,
    dose-free, identity-free, non-predictive, and gated behind explicit
    acknowledgement events.
