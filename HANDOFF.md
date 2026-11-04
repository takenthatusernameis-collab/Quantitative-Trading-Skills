# Handoff — EMA elevated-cost-sweep + param-sensitivity guards added; single-asset sweep-guard layer complete

## What changed
- Added `skills/quantitative-backtesting/tests/test_ema_cross_elevated_cost_real_aapl.py`, mirroring `test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py` (single-asset AAPL, relative-tolerance pinned metrics, deterministic verdict assertions).
- Added `skills/quantitative-backtesting/tests/test_ema_cross_param_sensitivity_real_aapl.py`, mirroring `test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py` (6 pre-registered EMA fast/slow settings, pinned metrics per setting).
- These are the two guards HANDOFF.md called for; the example machinery (`run_elevated_cost_sweep`, `PARAM_SENSITIVITY_GRID`, `run_param_sensitivity_sweep`) already existed in `examples/ema_cross_hypothesis.py` and was simply untested.

## What was actually verified
- Focused gate: `test_ema_cross_elevated_cost_real_aapl.py` + `test_ema_cross_param_sensitivity_real_aapl.py` + `test_ema_cross_benchmark_aware_real_aapl.py` + `test_walk_forward_ema_crossover_real_aapl.py` → **6 passed, 0 failed** in 13.94s.
- No-regression gate across the other single-asset families (bollinger / donchian / macd / mean_reversion / simple_momentum benchmark-aware + walk-forward) → **16 passed, 0 failed** in 31.24s.
- Observed on committed AAPL (net of 3bp costs, weak 2-criterion sweep): EMA crossover is SUPPORTED at every tested cost level (Sharpe 1.35→1.24, return 65.8%→59.2% as costs rise to 20bp/10bp) and at every pre-registered parameter setting (Sharpe 1.17→1.45). This is the weak-criterion (vs zero baseline) outcome, recorded honestly; the benchmark-aware guard pins the stronger verdict NOT SUPPORTED (does not beat buy-and-hold AAPL 77.4%, alpha p=0.21, deflated Sharpe p=0.49). No profitability claim is made.
- Offline, committed fixtures only (`assets/example_data/real_market_data/AAPL.csv`); no live network; no tuning to force SUPPORT.

## What remains unresolved
- All six single-asset families (dual_momentum, rsi, zscore, cross_sectional_momentum, bollinger_bands, donchian_breakout, ema_cross, macd, mean_reversion, simple_momentum) now have benchmark-aware guards. EMA additionally has elevated-cost-sweep + param-sensitivity guards. The remaining families still lack pinned sweep regression tests (their sweep machinery exists in example scripts but is not regression-guarded): bollinger_bands, donchian_breakout, macd, mean_reversion, simple_momentum.
- Full quant-backtesting suite (~981 tests, ~34 min) is too slow to complete in-session; per-file focused gates are the reliable verification mode.

## Approaches already tried / failed
- Direct relative `--data` path fails because `_run_backtest_metrics` subprocesses with `cwd=scripts/`; tests pass an absolute `data_path` (via `SRC`), as do the sibling dual_momentum sweep tests.
- First param-sensitivity test draft asserted `commission_bps`/`slippage_bps` keys that `run_param_sensitivity_sweep` does not emit (only `commission`/`slippage`); removed those assertions. No source change needed.

## One precise next task
Pin the elevated-cost-sweep and parameter-sensitivity regression guards for the remaining five single-asset families that have the sweep machinery in their example scripts but no regression tests. Concretely, for one family (e.g. `macd_hypothesis.py`, which has `run_elevated_cost_sweep` + `PARAM_SENSITIVITY_GRID` + `run_param_sensitivity_sweep`):
1. Add `tests/test_macd_elevated_cost_real_aapl.py` and `tests/test_macd_param_sensitivity_real_aapl.py`, mirroring the two new EMA tests above (single-asset AAPL, relative-tolerance pinned metrics, honest verdict asserted — do not tune to force SUPPORT).
2. Verify with a focused gate: the two new tests + `test_macd_benchmark_aware_real_aapl.py` + `test_walk_forward_macd_real_aapl.py`.
3. Repeat for bollinger_bands, donchian_breakout, mean_reversion, simple_momentum if time permits; otherwise hand off after one.

Constraints: offline only, committed fixtures only, no live network, no profitability claims, do not tune parameters to force SUPPORT. Env: `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`. Do not commit unless explicitly asked.

(End of file - total 36 lines)