# Handoff — full slow framework gate green; RSI walk-forward regression guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_rsi_real_aapl.py` — walk-forward out-of-sample falsification test for single-asset RSI mean reversion on the committed AAPL fixture. Pre-registered narrow grid (period=14, oversold=30, overbought=70, neutral=50), chronological walk-forward (train 12 / test 12 / step 12), 2bps+1bps costs, point-in-time validation, DSR applied. Falsification discipline (no forced SUPPORT). Focused tests pass (2 passed).
- Ran the full slow framework regression gate that was pending since HANDOFF_SESSION29/35: `tests/test_walk_forward.py tests/test_cpcv.py tests/test_resolution_vs_sample_size.py` — **303 passed, 401 warnings in 810.37s**. Working tree is green with the new test added.
- Focused regression gate on the new test plus the z-score walk-forward guards: `test_walk_forward_rsi_real_aapl.py` + `test_walk_forward_zscore_pair_real_aapl_msft.py` + `test_walk_forward_zscore_pair_real_aapl_googl.py` + `test_walk_forward_zscore_triple_real_aapl_msft_googl.py` — **8 passed in 7.38s**.

## What was actually verified
- RSI walk-forward on AAPL (this session): 8 periods (train 12 / test 12 months, step 12), pooled OOS Sharpe **-0.0907**, total OOS return **-12.22%**, win_rate_periods **0.2754**, bias_controls_engaged true, point-in-time validation passed. Pooled DSR p_value = **0.99997** (DSR ratio 3.29e-05, n_trials 8) >> 0.10 threshold → **NOT SUPPORTED**. All three falsification criteria fail (Sharpe <= 0, return < 0, DSR p >= 0.10). Test pins these metrics and asserts the honest NOT SUPPORTED verdict without tuning.
- Full slow framework regression gate: **303 passed**, no failures, no collection errors. Prior expected counts (walk_forward 195, cpcv 29, resolution 79) plus the additive guards added since.
- Z-score walk-forward guards still green (AAPL/MSFT pair, AAPL/GOOGL pair, triple).

## What remains unresolved
- On committed fixtures, every strategy family tested under walk-forward re-optimization net of costs (dual momentum, cross-sectional momentum, multi-pair z-score mean reversion, single-asset RSI mean reversion) fails the Deflated Sharpe p < 0.10 falsification criterion. No profitability/robustness claim warranted on any of them.
- This is a falsification outcome on committed fixtures (AAPL/MSFT/GOOGL only), not evidence about any market.

## Approaches already tried / failed
- Full slow gate: previously pending since HANDOFF_SESSION29/35; now run and green (303 passed, 810.37s). Not a failure — the blocker was simply an unrun verification.
- RSI walk-forward: NOT SUPPORTED (DSR p=0.99997) — falsified, not a failure of the test.
- Large test groups hang/time out — use per-file/focused gates; the full slow gate is the exception at ~810s.

## One precise next task
The walk-forward regression coverage is now complete for the z-score and RSI families on committed fixtures. The next bounded quant task is a new falsification experiment on committed fixtures using a strategy family not yet covered under walk-forward re-optimization (e.g., DonchianChannelBreakout trend-following, or mean_reversion), reusing the same framework: book/net-exposure panel pricing, chronological split, point-in-time validation, pre-registered criteria, elevated-cost sweep, no profitability claim. Add a focused regression test mirroring `test_walk_forward_rsi_real_aapl.py`, then run a targeted gate. Do not tune parameters to force SUPPORT.

Evidence/constraints:
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Full slow gate takes ~810s; prefer per-file/focused gates for large groups.
- New test file: `skills/quantitative-backtesting/tests/test_walk_forward_rsi_real_aapl.py` (2 passed).

(End of file - total 59 lines)