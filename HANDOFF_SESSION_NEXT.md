# Handoff — returns-based regime detection on fat_tail_crash (uniform tv=0.20)

## What changed
- Added `skills/quantitative-backtesting/scripts/returns_based_regime_detector.py`.
- Output `examples/returns_based_regime_results.json`.

## Results
- SMA: OOS Sharpe -0.0593, delta -0.0533 vs baseline (-0.0060).
- EMA: OOS Sharpe -0.1560, delta -0.3701 vs baseline (0.2142).
- bear_high triggered on 2397/5000 bars (threshold -0.10 over 63-day cumulative return) → regime is degenerate (mostly bear_high), so sizing collapses to uniform 0.20 everywhere; deltas identical to the uniform baseline. No improvement.

## Next task
Tune the cumulative-return threshold/window so bear_high is sparse and crash-focused (e.g. -0.20 over 21 days), then rerun and compare deltas. Do not claim profitability.