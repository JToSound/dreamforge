# Experimental Results — quantified behaviour study (2026-08-24)

> DreamForge is a research and visualization simulator. It does not measure brains, diagnose conditions, predict dreams, infer psychological meaning, or provide medical advice.

Five experiment families were designed and executed against the real engine
(`scripts/experiment.py`; raw data in `exports/_experiment_results.json`).
Everything below reports **observed values only**; "model-conditional"
applies throughout — none of this describes biology.

## E1 — Determinism

| Check | Result |
|---|---|
| Same seed × 5 repeats, one process | identical trace hash (`9efa218674b4b85c…`) |
| Fresh OS process, same seed/config | **identical hash** |
| Three other seeds | all produce different hashes |

Cross-process determinism holds byte-exactly. Two earlier "failures" of this
check were bugs in the experiment harness itself (an `exec` without
`__file__`, then JSON escaping through nested quoting), not engine
behaviour — worth recording because it demonstrates the value of probing
your measurement tools before trusting their verdicts.

## E2 — Scalability (uniform matrix, single runs)

| ticks | wall s | epochs/s | events |
|---|---|---|---|
| 480 | 0.119 | 4,035 | 1,536 |
| 960 | 0.258 | 3,719 | 3,072 |
| 1,920 | 0.516 | 3,720 | 6,144 |
| 4,800 | 1.268 | 3,786 | 15,360 |
| 9,600 | 2.572 | 3,732 | 30,720 |

Throughput is flat within noise (~3.7–4.1k epochs/s) over a 20× length range:
cost is linear in epochs with no graph/store blow-up. Note these rates exceed
the earlier PERFORMANCE.md figures because that suite traced allocations
(`tracemalloc` overhead ~4×); both sets are internally consistent.

## E3 — Sleep-model behaviour

### Stage distribution follows the declared matrix

- **Uniform matrix** (every off-diagonal 0.25), 1,920 epochs: all five stages
  land within **±0.57 pp** of 20% (e.g. N1 20.6%, N3 19.4%). For n=1920 the
  expected multinomial standard error is ≈0.91 pp, so the observed spread is
  inside sampling noise — the sampler tracks its declared distribution.
- **Deep-sleep-biased matrix** (each row sends 0.85 to the deep-sleep target):
  N3 46.0% + N2 39.1% = **85.1% of epochs in deep-sleep chain**, Wake 5.3%,
  REM 4.0%. Output composition moved exactly where the parameters point.
  (First attempt at this scenario was invalid — a row may not transition to
  itself, so biasing "N3→N3" silently produced a row summing to 0.20; the
  fail-closed validator's spirit caught it in design.)

### Process S / proxies stay in their lanes

Over a 9,600-epoch default run: Process S ∈ **[0.012, 0.497]** (bounded ✓),
circadian C(t) ∈ [0.35, 0.65], and **every neurochemical proxy sample stayed
inside [0,1]** across all four channels (n=38,400 samples).

### Dwell-cap sensitivity — a degenerate-config finding

With the single-point dwell prior used by the test configs
(`weights=[1.0]`, `min_epochs=1`), changing `max_dwell_epochs` (2/4/8/16)
produced **exactly 1,920 transitions in all cases**: every epoch expires
immediately, so the cap never binds. Consequence visible in E5 too:
stage-transition counts are *structurally fixed*, not stochastic, under this
prior. Realistic dwell variation needs a multi-point weight vector — a
documented knob, exercised here only at its degenerate corner.

## E4 — Stress edges

| Scenario | Expected | Observed |
|---|---|---|
| Minimal graph (3 nodes, top_k=3) | replays still work | ✓ 48 replays, selections always size 3 |
| Extreme baselines (0 and 1 mixed) | clip to [0,1] | ✓ all samples in bounds |
| Long night 28,800 epochs (~4 h wall-night at 30 s… 240 h sim) | invariants hold | ✓ 92,160 events, sequence perfectly contiguous |
| Replay-every-epoch, top_k=5 (heaviest legal replay load) | schedule exact | ✓ 480/480 replays |

No invariant broke under any edge configuration; the engine neither crashes
nor drifts out of bounds even at 92k events in one process.

## E5 — Cross-seed ensemble statistics (20 members)

| Metric | mean | sd | min–max |
|---|---|---|---|
| Mean Process S | 0.1042 | 0.0020 | 0.1006–0.1075 |
| Stage transitions | 960.0 | 0.0 | fixed (see E3 dwell note) |
| Memory replays | 192.0 | 0.0 | fixed by schedule |

- All 20 members produced **distinct trace hashes** (seeds matter; no
  accidental stream reuse).
- Process S varies tightly (CV ≈ 1.9%) across seeds under this matrix —
  the equilibrium level is stable while stage *sequences* differ.
- Wall time for all 40 runs (20 + 20 re-runs for hashes): ~5 s.

## Threats to validity (honest list)

- Single machine, single OS, no warmup; timings have ±10% run-to-run jitter.
- Dwell distributions in E3/E5 are degenerate single-point priors; results
  characterise that corner, not multi-point dwell behaviour.
- Stage-fraction deviations were compared to multinomial SE informally, not
  with a formal goodness-of-fit test.
- E4's "long night" uses the same uniform-matrix family; adversarial matrices
  (near-deterministic) were not swept.

Reproduce everything:

```bash
".venv/Scripts/python.exe" scripts/experiment.py          # all families
".venv/Scripts/python.exe" scripts/experiment.py E1 E3    # subset
```
