# Handoff — Current State (2026-11-21): fat_tail_crash regime thread CLOSED

## Baseline
- HEAD `569ff2f`, branch `main`. Working tree has this session's UNCOMMITTED
  changes only (do NOT commit unless asked):
  - `skills/quantitative-backtesting/scripts/returns_based_regime_detector.py` (rewritten: parametrized sweep + per-regime test + ffill-order bug fix)
  - `skills/quantitative-backtesting/examples/returns_based_regime_results.json` (new 2-section schema)
  - `skills/quantitative-backtesting/scripts/_diag_returns_regime.py` (new, untracked diagnostic)
- No library modules were modified. Focused tests (regime_detection, regime_aware_position_sizing, generate_adversarial_scenarios) → 85 passed. Full archive: `HANDOFF_SESSION_149.md`.

## Where the thread landed
- **Sparse crash-focused bear_high is achievable** (21d/-0.20 → 5.66% of bars, precision 1.00, first trigger 368 vs first true crash 366; recall 0.31). Prior "degenerate 47.9%" was inflated by an ffill-order bug (fixed).
- **Uniform tv=0.20: OOS Sharpe is INVARIANT to regime labels** across all settings (SMA delta -0.0533, EMA -0.3701 identical for bear% 5.3→33%). The deltas measure the uniform vol-target overlay (lookback 20) vs the baseline's plain crossover sizing, NOT the detector. This retroactively explains all prior uniform-tv "detector variants".
- **Crash de-risking is worse**: sparse bear_high with bear_high_vol=0.10 → SMA -0.0874, EMA -0.3737 (worse than uniform).
- **Thread EXHAUSTED.** No profitability / significance claim; synthetic data only.

## Approaches already failed (do not repeat)
- Any fat_tail_crash regime-detector tuning at uniform tv (labels irrelevant to sizing).
- Crash de-risking via lower target_vol in a sparse crash regime (worse than uniform).
- Threshold/window tuning to "improve" uniform-tv OOS Sharpe (mathematically cannot).

## One precise next task
See `HANDOFF_SESSION_NEXT.md`.