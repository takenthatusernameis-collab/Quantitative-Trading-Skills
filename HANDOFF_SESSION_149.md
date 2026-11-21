# Handoff — Session 149 (2026-11-21): Returns-based regime tuning on fat_tail_crash — thread closed

## Baseline
- HEAD `569ff2f`, branch `main`. Working tree was clean at session start except the
  prior agent's uncommitted `returns_based_regime_detector.py` + results JSON.
- Prior task (from `HANDOFF_SESSION_NEXT.md`): "Tune the cumulative-return
  threshold/window so bear_high is sparse and crash-focused (e.g. -0.20 over 21
  days), then rerun and compare deltas. Do not claim profitability."
- Prior result was a DEGENERATE detector: threshold -0.10 / 63d → bear_high on
  2397/5000 bars (47.9%); deltas SMA -0.0533, EMA -0.3701.

## What changed this session (uncommitted; do NOT commit unless asked)
- `skills/quantitative-backtesting/scripts/returns_based_regime_detector.py`:
  - Parametrized by (cum_return_window, cum_return_threshold); sweeps 4 settings.
  - Reports bear_high sparsity (fraction of bars) AND crash alignment
    (precision/recall vs the 13 true jump-diffusion crash days, which are
    recovered exactly by replaying the generator RNG — diagnostics only, never
    used for sizing).
  - Adds a differential per-regime test (bear_high_vol=0.10, else 0.20) on the
    best sparse setting, to isolate "does crash de-risking help?".
  - **Bug fix:** ffill now runs BEFORE stamping bear_high spans. The prior order
    (stamp then ffill) smeared bear_high forward through every trailing
    "unknown" gap (e.g. the 200-bar trend warmup), inflating the label to 33%
    even for sparse thresholds. Correct order yields genuinely sparse labels.
- `skills/quantitative-backtesting/examples/returns_based_regime_results.json`:
  new schema with two sections — `fat_tail_crash_returns_based_sweep` (uniform
  tv) and `fat_tail_crash_returns_based_per_regime` (differential tv).
- `skills/quantitative-backtesting/scripts/_diag_returns_regime.py` (new,
  untracked): reproducible cumulative-return distribution + crash-alignment
  diagnostic used to choose the sparse settings.

## Results (evidence: returns_based_regime_results.json)
True crash days (seed 42, 5000 bars): 13 →
`[366, 612, 1441, 1583, 1954, 2342, 2769, 2807, 3103, 3548, 4065, 4347, 4992]`.

Uniform target_vol = 0.20 (all regimes):
| setting            | win | thr   | bear% | precision | recall | SMA delta | EMA delta |
|--------------------|-----|-------|-------|-----------|--------|-----------|-----------|
| prior_degenerate   | 63  | -0.10 | 33.08 | 0.26      | 0.23   | -0.0533   | -0.3701   |
| sparse_21d_m20     | 21  | -0.20 | 5.66  | 1.00      | 0.31   | -0.0533   | -0.3701   |
| sparse_21d_m18     | 21  | -0.18 | 6.62  | 1.00      | 0.38   | -0.0533   | -0.3701   |
| sparse_10d_m15     | 10  | -0.15 | 5.30  | 1.00      | 0.46   | -0.0533   | -0.3701   |

Differential per-regime (sparse_21d_m20, bear_high_vol=0.10, else 0.20):
| setting                          | bear% | precision | recall | SMA delta | EMA delta |
|----------------------------------|-------|-----------|--------|-----------|-----------|
| sparse_21d_m20_per_regime_bear010| 5.66  | 1.00      | 0.31   | -0.0874   | -0.3737   |

Baselines (plain crossover, no vol overlay): SMA -0.00597, EMA +0.21417.

## Key findings (no profitability / significance claim; synthetic data)
1. **A sparse, crash-focused bear_high IS achievable as a labeler.** The
   21d/-0.20 setting touches 5.66% of bars with precision 1.00 (every trigger's
   lookback window contains a true crash) and first bear_high at 368 (first true
   crash at 366). 10d/-0.15 hits the first crash exactly (366) with recall 0.46.
   The prior "degenerate 47.9%" was partly the ffill bug; corrected it is 33%
   for the old setting and ~5–7% for sparse settings.
2. **At uniform target_vol, OOS Sharpe is INVARIANT to the regime labels.** All
   four settings give byte-identical OOS Sharpe (SMA -0.05930, EMA -0.15596)
   despite bear_high fractions from 5.3% to 33%. Reason: `target_by_regime`
   maps every label to 0.20, so `regime_aware_position_size` is a pure
   vol-target overlay with no regime dependence. The reported deltas
   (-0.0533 / -0.3701) therefore measure the **uniform 20%-vol-target overlay
   (lookback=20) vs the baseline's plain crossover sizing** — NOT the detector.
   This retroactively explains why every prior uniform-tv "detector variant"
   (session 148 crash-trigger/crash-only, this session returns-based) produced
   the same deltas: the detector never entered the sizing math.
3. **Crash de-risking does not help.** A sparse, crash-focused bear_high with a
   lower target_vol (0.10) during the 5.66% crash bars is WORSE than uniform for
   both strategies (SMA -0.0874 vs -0.0533; EMA -0.3737 vs -0.3701). Cutting
   exposure during/after the crash costs more than it saves on this data.

## Thread status: EXHAUSTED
fat_tail_crash regime-detector tuning is closed. Every variant tried
(vol-quantile, crash-trigger, crash-only, returns-based uniform, returns-based
per-regime) fails to beat uniform target_vol=0.20. The uniform-tv experiments
were provably regime-independent; the one per-regime (de-risking) experiment is
worse than uniform.

## What was actually verified
- `returns_based_regime_detector.py` runs end-to-end (~1m47s), all 5 rows saved.
- Focused tests: `test_regime_detection.py`, `test_regime_aware_position_sizing.py`,
  `test_generate_adversarial_scenarios.py` → **85 passed** (`-n 4`, 14.6s).
  `test_walk_forward.py` NOT re-run (library code unchanged by this session; it
  is large/slow; prior baseline 226 passed). NOTE: pytest IS importable in
  `/tmp/venv` now (contradicts session 148's note that pytest was missing).
- No library modules were modified; changes are isolated to a standalone script
  + its output JSON + a diagnostic script.

## Approaches already failed (do NOT repeat)
- Any regime-detector tuning on fat_tail_crash at uniform tv (labels irrelevant).
- Crash de-risking via lower target_vol in a sparse crash regime (worse).
- Detector threshold/window tuning to "improve" uniform-tv OOS Sharpe (cannot).

## One precise next task
Move OFF synthetic fat_tail_crash detector tuning and onto a real-data quant
methodology thread with genuine signal. Concretely:
- Audit ONE existing real-data walk-forward test for cost realism and honest
  out-of-sample reporting, e.g.
  `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py`.
  Determine whether its conclusion survives net-of-cost / borrow / capacity, and
  report the net numbers (no profitability claim beyond what the test shows).
- Alternatively, if a fresh hypothesis is preferred, state it with an EXPLICIT
  falsification criterion and a chronological train/validation/test split before
  coding.
Constraints: preserve synthetic/no-significance-claim discipline; reuse existing
`detect_combined_regime` + `walk_forward_analysis` machinery; do not commit unless
asked. Environment: `source /tmp/venv/bin/activate` (pytest available).

## Evidence locations
- `skills/quantitative-backtesting/scripts/returns_based_regime_detector.py`
- `skills/quantitative-backtesting/scripts/_diag_returns_regime.py`
- `skills/quantitative-backtesting/examples/returns_based_regime_results.json`
- Baseline: repo-root `adversarial_stress_test_results.json`