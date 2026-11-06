# Handoff — zscore single-asset AAPL guard not applicable (pairs-only strategy)

## What changed
- No source/test changes. Audited `zscore_mean_reversion_hypothesis.py` single-asset AAPL feasibility.

## What was verified
- `run_elevated_cost_sweep` on `AAPL.csv` fails: `_run_backtest_metrics` -> `load_multi_symbol` requires a `symbol`/`ticker` column; zscore is a pairs strategy and cannot run on a single-asset panel.
- All single-asset strategies already have elevated-cost + param-sensitivity AAPL guards (bollinger, donchian, ema_cross, macd, mean_reversion, rsi, simple_momentum, sma_crossover, cross_sectional_momentum, dual_momentum).

## One precise next task
All single-asset guard coverage is complete. Next: audit pair-level zscore elevated-cost/param-sensitivity guards for missing combos or verify an existing pair guard's pinned metrics; or move to cross-sectional momentum pair-level coverage. Avoid inventing single-asset zscore tests.
" filePath">
HANDOFF_SESSION_NEXT.md