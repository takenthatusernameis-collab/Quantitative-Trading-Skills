# Handoff — MACD elevated-cost-sweep + param-sensitivity guards added; MACD single-asset sweep-guard layer complete

## What changed
- Added `skills/quantitative-backtesting/tests/test_macd_param_sensitivity_real_aapl.py` (new file), mirroring `test_ema_cross_param_sensitivity_real_aapl.py`: 6 pre-registered MACD fast/slow/signal settings, single-asset AAPL, relative-tolerance pinned metrics, honest verdict assertions.
- Updated `skills/quantitative-backtesting/tests/test_macd_elevated_cost_real_aapl.py` (already existed; corrected the docstring from "long/flat" to "long/short" to match the actual MACD strategy and rewrote the methodological note to cite the benchmark-aware p-values).
- The sweep machinery (`run_elevated_cost_sweep`, `PARAM_SENSITIVITY_GRID`, `run_param_sensitivity_sweep`) already existed in `examples/macd_hypothesis.py`; these tests simply regression-guard it.

## What was actually verified
- Focused gate: `test_macd_elevated_cost_real_aapl.py` + `test_macd_param_sensitivity_real_aapl.py` + `test_macd_benchmark_aware_real_aapl.py` + `test_walk_forward_macd_real_aapl.py` → **6 passed, 0 failed** in 15.22s.
- No-regression gate across the other single-asset families (ema_cross incl. elevated-cost + param-sensitivity, bollinger_bands, donchian_breakout, simple_momentum, mean_reversion benchmark-aware) → **14 passed, 0 failed** in 37.20s.
- Observed on committed AAPL (net of 3bp costs, weak 2-criterion sweep): MACD is NOT SUPPORTED at every tested cost level (Sharpe 0.056→-0.336, return -0.13%→-18.9% as costs rise to 20bp/10bp) and mixed across the six pre-registered parameter settings: (12,26,9), (8,21,5), (12,26,6), (10,24,9) are NOT SUPPORTED, while (16,34,12) (Sharpe 0.855, return 50.8%) and (12,26,12) (Sharpe 0.134, return 4.2%) pass both weak criteria. The benchmark-aware guard pins the stronger verdict NOT SUPPORTED (does not beat buy-and-hold AAPL 77.4%, alpha p=0.60, deflated Sharpe p=0.96). The mixed param-sweep result is itself evidence of parameter sensitivity, not of a robust edge; no profitability claim is made.
- Offline, committed fixtures only (`assets/example_data/real_market_data/AAPL.csv`); no live network; no tuning to force SUPPORT.

## What remains unresolved
- MACD now has benchmark-aware + elevated-cost-sweep + param-sensitivity + walk-forward guards. The remaining families still lack pinned sweep regression tests despite having the sweep machinery in their example scripts: **bollinger_bands, donchian_breakout, mean_reversion, simple_momentum**. (Note: `mean_reversion_hypothesis.py` runs the `bollinger_bands` strategy, so its sweep machinery is shared with `bollinger_bands_hypothesis.py`.)
- Full quant-backtesting suite (~981 tests, ~34 min) is too slow to complete in-session; per-file focused gates are the reliable verification mode.

## Approaches already tried / failed
- Running pytest from inside `skills/quantitative-backtesting/` with a bare `tests/...` path fails because the repo-root `conftest`/rootdir resolution differs; always pass the full `skills/quantitative-backtesting/tests/...` path from the repo root.
- No source change was needed; the example sweep functions already returned the keys the tests assert (`commission_bps`, `slippage_bps`, `fast_period`, `slow_period`, `signal_period`, `commission`, `slippage`, `sharpe_ratio`, `total_return`, `criteria`, `verdict`, `all_pass`).

## One precise next task
Pin the elevated-cost-sweep and parameter-sensitivity regression guards for the remaining four single-asset families that have the sweep machinery in their example scripts but no regression tests. Concretely, for one family (e.g. `bollinger_bands_hypothesis.py`, which has `run_elevated_cost_sweep` + `PARAM_SENSITIVITY_GRID` + `run_param_sensitivity_sweep`):
1. Add `tests/test_bollinger_bands_elevated_cost_real_aapl.py` and `tests/test_bollinger_bands_param_sensitivity_real_aapl.py`, mirroring the two new MACD tests above (single-asset AAPL, relative-tolerance pinned metrics, honest verdict asserted — do not tune to force SUPPORT). Capture the pinned metrics by running the sweep functions first; do not guess them.
2. Verify with a focused gate: the two new tests + `test_bollinger_bands_benchmark_aware_real_aapl.py` + `test_walk_forward_bollinger_real_aapl.py`.
3. Repeat for donchian_breakout, mean_reversion, simple_momentum if time permits; otherwise hand off after one.

Constraints: offline only, committed fixtures only, no live network, no profitability claims, do not tune parameters to force SUPPORT. Env: `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`. Do not commit unless explicitly asked.

(End of file - total 38 lines)