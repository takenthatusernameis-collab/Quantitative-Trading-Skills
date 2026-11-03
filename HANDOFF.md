# Handoff — MACD walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py` — walk-forward OOS falsification test for MACD (trend-following) on the committed single-asset panel (AAPL). Pre-registered grid (fast_period=12, slow_period=26, signal_period=9), chronological WF (train12/test12/step12), 2bps+1bps costs, point-in-time validation, DSR. Falsification discipline (no forced SUPPORT). 2 passed.

## What was actually verified
- MACD WF on AAPL: pooled OOS Sharpe **0.138801**, total return **+20.31%**, DSR p=**0.848748** (>=0.10) → NOT SUPPORTED (fails DSR criterion). Test pins metrics and asserts honest NOT SUPPORTED verdict.
- Focused gate on MACD test: **2 passed in 1.20s**.
- Regression check: `test_walk_forward.py` + `test_strategy_builder.py` still green (76 tests).

## What remains unresolved
- On committed fixtures, every strategy family tested under walk-forward re-optimization net of costs (dual momentum, cross-sectional momentum, multi-pair z-score mean reversion, single-asset RSI, Donchian, Bollinger, SMA crossover, EMA crossover, MACD) fails the Deflated Sharpe p < 0.10 falsification criterion. No profitability/robustness claim warranted on any of them.
- This is a falsification outcome on committed fixtures (AAPL/MSFT/GOOGL only), not evidence about any market.

## Approaches already tried / failed
- None this session; followed established pattern from SMA/Donchian/Bollinger/RSI/EMA tests.

## One precise next task
All single-asset trend-following strategies in the registry (SMA, EMA, MACD) and the breakout/mean-reversion ones (Donchian, Bollinger, RSI) now have walk-forward falsification tests on committed AAPL fixtures. The remaining strategy families without a dedicated walk-forward test on committed real fixtures are the panel/multi-asset strategies (`cross_sectional_momentum`, `dual_momentum`, `zscore_mean_reversion`, `multi_pair_zscore_mean_reversion`) — but several of those already have walk-forward tests on the triple panel (`test_walk_forward_cross_sectional_momentum_real_triple_aapl_msft_googl.py`, `test_walk_forward_zscore_triple_real_aapl_msft_googl.py`, `test_dual_momentum_walk_forward_real_triple_aapl_msft_googl.py`). Verify that coverage inventory is complete; if a gap exists, add the matching walk-forward falsification test following the established pattern.

Evidence/constraints:
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Committed fixtures only in `skills/quantitative-backtesting/assets/example_data/real_market_data/`
- New test: `skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py` (2 passed)

(End of file - total 32 lines)