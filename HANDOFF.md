# Handoff — benchmark-aware RSI mean-reversion test + panel support added

## What changed
- Made `RSIMeanReversion` panel-capable in `skills/quantitative-backtesting/scripts/strategy_builder.py`: `generate_signals` now accepts dict (`symbol -> DataFrame`) and MultiIndex-column panel data (returns per-asset positions, collapsed to a scalar net-exposure series), and a new `generate_target_weights` returns the per-asset position book (`None` for single-asset, unchanged behaviour). This enables `--multi-symbol --panel-pricing book` for RSI, mirroring dual momentum / z-score mean reversion. Single-asset RSI behaviour is untouched.
- Extended `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py` with benchmark-aware machinery, mirroring `dual_momentum_hypothesis.py` / `zscore_mean_reversion_hypothesis.py`:
  - `BENCHMARK_FILE = "MSFT.csv"` (resolved relative to `assets/example_data/real_market_data/`)
  - `PARAMS`, `N_TRIALS = len(PARAM_SENSITIVITY_GRID)` (= 5)
  - `_gt_zero`, `_lt_0_10`, `_lt_0_05`, `_oos_total_return_gt_benchmark` helpers
  - `BENCHMARK_CRITERIA` (4 criteria: oos_sharpe > 0, oos_total_return > benchmark, deflated_sharpe_pvalue < 0.10, benchmark_alpha_pvalue < 0.05)
  - `run_benchmark_aware_hypothesis_test(data_path, benchmark_path=BENCHMARK_FILE, n_trials=N_TRIALS)` using `--multi-symbol --panel-pricing book --benchmark --n-trials`
  - Baseline `run_hypothesis_test` and `main()` unchanged (examples-coverage tests still pass).
- Added `skills/quantitative-backtesting/tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py` (2 tests: run smoke + pinned regression guard).

## What was actually verified
- New RSI benchmark-aware test: 2 passed (~2s), deterministic across repeated runs.
- Observed (committed fixtures only, NOT evidence about any market), honest NOT SUPPORTED — no tuning:
  - sharpe_ratio -0.2979, total_return -31.84%, vs benchmark MSFT total_return +90.15%
  - benchmark_alpha -0.2281, benchmark_alpha_pvalue 0.4367 (> 0.05)
  - deflated_sharpe_pvalue 0.9859 (> 0.10, 5 trials)
  - All 4 benchmark-aware criteria fail; verdict pinned NOT SUPPORTED.
- All 17 existing RSI tests pass (no regression from `strategy_builder.py` change).
- RSI examples-coverage tests: 5 passed (`test_rsi_mean_reversion_hypothesis_*`).
- `test_strategy_builder.py` + `test_run_backtest.py`: 141 passed (warnings are pre-existing and unrelated).

## What remains unresolved
- Full bounded quant-backtesting suite not re-run end-to-end after the `strategy_builder.py` change (only RSI + strategy_builder/run_backtest subsets). Broad regression risk is low (change isolated to RSIMeanReversion), but a full-suite pass would confirm it.
- Changes are uncommitted (working tree only); no commit was requested.

## Approaches already tried / failed
- None for this task; RSI multi-symbol crashed before the panel change (fixed by making RSI panel-capable).

## One precise next task
Run the full quant-backtesting test suite (`pytest skills/quantitative-backtesting/tests/`) to confirm no regressions from the shared `strategy_builder.py` change, then (if green and the user asks) commit the three changes:
- `skills/quantitative-backtesting/scripts/strategy_builder.py`
- `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py`
- `skills/quantitative-backtesting/tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py`

Evidence/constraints:
- Offline, committed fixtures only; MSFT as buy-and-hold benchmark; relative tolerance only; no tuning to force SUPPORT.
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0; `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
