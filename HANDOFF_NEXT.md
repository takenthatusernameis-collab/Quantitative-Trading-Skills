# Handoff — Bollinger Bands walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_bollinger_real_aapl.py` — walk-forward OOS falsification test for Bollinger Bands mean reversion on the committed AAPL fixture. Pre-registered grid (period=20, std_dev=2.0), chronological WF (train12/test12/step12), 2bps+1bps costs, point-in-time validation, DSR. Falsification discipline (no forced SUPPORT). 2 passed.

## What was verified
- Bollinger WF on AAPL: pooled OOS Sharpe **-0.5005**, total return **-48.62%**, DSR p=**0.9997** (>=0.10) → NOT SUPPORTED. All three falsification criteria fail. Test pins metrics; passes.
- Focused regression gate on the new test plus the existing walk-forward guards (bollinger + rsi + donchian + zscore pair AAPL/MSFT + zscore pair AAPL/GOOGL + zscore triple): **12 passed in 10.81s**.

## What remains unresolved
- On committed fixtures, every strategy family tested under walk-forward re-optimization net of costs (dual momentum, cross-sectional momentum, multi-pair z-score mean reversion, single-asset RSI, Donchian, Bollinger) fails the Deflated Sharpe p < 0.10 falsification criterion. No profitability/robustness claim warranted on any of them.
- This is a falsification outcome on committed fixtures (AAPL/MSFT/GOOGL only), not evidence about any market.

## Approaches already tried / failed
- None this session; the Bollinger walk-forward was a clean addition following the established rsi/donchian pattern.

## One precise next task
Walk-forward regression coverage is now complete for the mean-reversion family (RSI, Bollinger, z-score pair/triple) and the trend-following Donchian breakout on committed fixtures. The next bounded quant task is a new falsification experiment on committed fixtures using a single-asset trend-following / crossover family not yet covered under walk-forward re-optimization (e.g., `sma_crossover`), reusing the same framework: single-asset AAPL panel pricing, chronological split (train12/test12/step12), point-in-time validation, pre-registered criteria, DSR applied, no profitability claim. Add a focused regression test mirroring `test_walk_forward_bollinger_real_aapl.py`, then run a targeted gate. Do not tune parameters to force SUPPORT.

Evidence/constraints:
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Focused gate for the six walk-forward guards takes ~11s; the full slow gate takes ~810s.
- New test file: `skills/quantitative-backtesting/tests/test_walk_forward_bollinger_real_aapl.py` (2 passed).

(End of file - total 33 lines)