# Handoff — EMA crossover walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_real_aapl.py` — walk-forward OOS falsification test for EMA crossover (trend-following) on the committed single-asset panel (AAPL). Pre-registered grid (fast_period=12, slow_period=26), chronological WF (train12/test12/step12), 2bps+1bps costs, point-in-time validation, DSR. Falsification discipline (no forced SUPPORT). 2 passed.

## What was actually verified
- EMA crossover WF on AAPL: pooled OOS Sharpe **0.625020**, total return **+155.88%**, DSR p=**0.392689** (>=0.10) → NOT SUPPORTED (fails DSR criterion). Test pins metrics and asserts honest NOT SUPPORTED verdict.
- Focused gate on EMA crossover test: **2 passed in 0.45s**.

## What remains unresolved
- On committed fixtures, every strategy family tested under walk-forward re-optimization net of costs (dual momentum, cross-sectional momentum, multi-pair z-score mean reversion, single-asset RSI, Donchian, Bollinger, SMA crossover, EMA crossover) fails the Deflated Sharpe p < 0.10 falsification criterion. No profitability/robustness claim warranted on any of them.
- This is a falsification outcome on committed fixtures (AAPL/MSFT/GOOGL only), not evidence about any market.

## Approaches already tried / failed
- None this session; followed established pattern from SMA/Donchian/Bollinger/RSI tests.

## One precise next task
MACD is in the strategy registry (`MACDStrategy`) but has no walk-forward test on committed real fixtures yet. Add a walk-forward falsification test for MACD on AAPL (`skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py`) following the exact pattern: pre-registered narrow grid (fast_period=12, slow_period=26, signal_period=9 or similarly constrained), train12/test12/step12, commission 0.0002, slippage 0.0001, apply_deflation=True, validate_pit=True, pin metrics, assert NOT SUPPORTED under falsification criteria (do not tune to force SUPPORT). Run focused gate on the new test.

Evidence/constraints:
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Committed fixtures only in `skills/quantitative-backtesting/assets/example_data/real_market_data/`
- New test: `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_real_aapl.py` (2 passed)
