# Handoff — Donchian walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_donchian_real_aapl.py` — walk-forward OOS falsification test for Donchian channel breakout trend-following on committed AAPL fixture. Pre-registered grid (period=20, exit_period=10), chronological WF (train12/test12/step12), 2bps+1bps costs, point-in-time validation, DSR. Falsification discipline (no forced SUPPORT). 2 passed.

## What was verified
- Donchian WF on AAPL: pooled OOS Sharpe 0.2629, total return +52.1%, DSR p=0.731 (>=0.10) → NOT SUPPORTED on multiple-testing-corrected criterion. Raw Sharpe positive but not DSR-significant. Test pins metrics; passes.

## What remains unresolved
- All strategy families tested under WF re-optimization on committed fixtures fail DSR p<0.10. Donchian now added; still fails corrected criterion.

## Next task
Add walk-forward falsification experiment for mean_reversion (single-asset) or MeanReversionZScore on committed fixtures, mirroring test_walk_forward_rsi_real_aapl.py. Run targeted gate. Do not tune to force SUPPORT.
