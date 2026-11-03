# Handoff — SMA crossover walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_real_aapl.py` — walk-forward OOS falsification test for SMA crossover (trend-following) on the committed single-asset panel (AAPL). Pre-registered grid (fast_period=20, slow_period=50), chronological WF (train12/test12/step12), 2bps+1bps costs, point-in-time validation, DSR. Falsification discipline (no forced SUPPORT). 2 passed.

## What was verified
- SMA crossover WF on AAPL: pooled OOS Sharpe **0.292286**, total return **+54.58%**, DSR p=**0.601882** (>=0.10) → NOT SUPPORTED (fails DSR criterion). Test pins metrics; passes.
- New test passes in isolation. Quick gate for SMA crossover + previous families pattern verified locally.

## What remains unresolved
- On committed fixtures, every strategy family tested under walk-forward re-optimization net of costs (dual momentum, cross-sectional momentum, multi-pair z-score mean reversion, single-asset RSI, Donchian, Bollinger, SMA crossover) fails the Deflated Sharpe p < 0.10 falsification criterion. No profitability/robustness claim warranted on any of them.
- This is a falsification outcome on committed fixtures (AAPL/MSFT/GOOGL only), not evidence about any market.

## Approaches already tried / failed
- None this session; followed the established pattern from bollinger/rsi/donchian tests.

## One precise next task
The mean-reversion family (RSI, Bollinger, z-score pair/triple) and the trend-following families (Donchian, SMA crossover) are now covered under walk-forward re-optimization on committed AAPL fixtures. The next bounded quant task is to add walk-forward coverage for another strategy family not yet covered, or extend existing coverage to another committed asset/panel. For example, add a walk-forward test for EMA crossover (`ema_crossover`) on AAPL if present, following the exact pattern of existing tests: pre-registered grid, train12/test12/step12, costs 2bps+1bps, point-in-time validation, DSR applied, pin metrics, falsification verdict (do not tune to force SUPPORT). If EMA crossover is not easily parameterizable or has issues, consider MACD instead, but must reuse the framework and be strict about falsification. Run focused gate on the new test.

Evidence/constraints:
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Committed fixtures only in `skills/quantitative-backtesting/assets/example_data/real_market_data/`
- New test: `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_real_aapl.py` (2 passed)
