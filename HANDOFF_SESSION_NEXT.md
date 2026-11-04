# Handoff — Bollinger Bands benchmark-aware falsification guard added

## What changed
- Confirmed `run_backtest.py` supports the `bollinger_bands` strategy (`skills/quantitative-backtesting/scripts/strategy_builder.py:1454`, defaults `{"period": 20, "std_dev": 2.0}`).
- Added `skills/quantitative-backtesting/examples/bollinger_bands_hypothesis.py` (benchmark-aware `run_benchmark_aware_hypothesis_test` + `BENCHMARK_CRITERIA` + `N_TRIALS=6`, buy-and-hold AAPL self-benchmark, 3bp costs, chronological 0.6/0.2/0.2 split, PIT validation), mirroring `ema_cross_hypothesis.py` / `donchian_breakout_hypothesis.py`.
- Added `skills/quantitative-backtesting/tests/test_bollinger_bands_benchmark_aware_real_aapl.py` mirroring `test_ema_cross_benchmark_aware_real_aapl.py`: asserts verdict NOT SUPPORTED, all four BENCHMARK_CRITERIA pass/fail, and pinned observed net-of-costs metrics (rel tol 1e-3).
- Working tree otherwise clean: only the two new files are untracked.

## What was actually verified
- New Bollinger Bands test: 2 passed.
- No-regression gate: bollinger + ema + donchian + macd benchmark-aware tests: 8 passed in 10.82s.
- Observed on committed AAPL (net of 3bp costs): Sharpe -1.3014, return -42.55% vs benchmark 77.43%, alpha p=0.0199, deflated Sharpe p=0.9999 (6 trials). Criteria: oos_sharpe_gt_zero FAIL, oos_total_return_gt_benchmark FAIL, deflated_sharpe_pvalue_lt_0.10 FAIL, benchmark_alpha_pvalue_lt_0.05 PASS → verdict NOT SUPPORTED. Elevated-cost sweep stays NOT SUPPORTED (stable).
- Offline, committed fixtures only (assets/example_data/real_market_data/AAPL.csv); no live network; no tuning to force SUPPORT.

## What remains unresolved
- Full quant-backtesting suite (971 tests) is too slow to complete in-session; affected subsets confirmed green per prior handoffs. No remaining single-asset family lacks a benchmark-aware guard (MACD, Donchian, EMA, Bollinger Bands all now have one).

## Approaches already tried / failed
- None this session. Direct relative `--data` path fails because `_run_backtest_metrics` subprocesses with `cwd=scripts/`; tests pass an absolute `data_path` (via `SRC`).

## One precise next task
All four single-asset families (MACD, Donchian, EMA, Bollinger Bands) now have benchmark-aware + elevated-cost-sweep + param-sensitivity falsification guards on committed AAPL. The bounded single-asset guard work is complete.
Next candidate: extend benchmark-aware coverage to a multi-asset panel, or review whether any remaining hypothesis family (e.g. zscore_mean_reversion, pairs_trading) lacks a benchmark-aware guard. Inspect `skills/quantitative-backtesting/examples/` and `tests/` to confirm coverage before declaring the falsification-guard layer complete; do not add guards merely for completeness without a demonstrated methodological gap.

Constraints: offline only; relative tolerance only; verdict stays NOT SUPPORTED unless evidence genuinely warrants SUPPORT; smallest reversible change; do not touch inherited marketplace schemas/attribution/licenses.
