# Handoff — EMA crossover benchmark-aware falsification guard added; dual momentum task verified complete

## What changed
- Verified the HANDOFF_SESSION_NEXT.md dual-momentum task is already complete: `tests/test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py` and `tests/test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py` already pass `benchmark_path="MSFT.csv"` and `n_trials=N_TRIALS` (6) and pin benchmark+Deflated-Sharpe metrics; `test_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py` passes. All 4 dual-momentum tests green (8.18s).
- Added `skills/quantitative-backtesting/tests/test_ema_cross_benchmark_aware_real_aapl.py`, mirroring `test_donchian_breakout_benchmark_aware_real_aapl.py`: calls `run_benchmark_aware_hypothesis_test(data_path=AAPL.csv, benchmark_path="AAPL.csv", n_trials=N_TRIALS=6)` from `examples/ema_cross_hypothesis.py` (which already had benchmark-aware machinery matching the Donchian pattern). Pins verdict NOT SUPPORTED, all four BENCHMARK_CRITERIA pass/fail, and observed net-of-costs metrics (rel tol 1e-3) as regression guards.

## What was actually verified
- New EMA test: 2 passed in 2.79s (verdict NOT SUPPORTED; Sharpe 1.3539, return 65.78% vs AAPL buy-and-hold 77.43%, alpha p=0.2065, deflated Sharpe p=0.4930 across 6 trials).
- No-regression gate: donchian + macd benchmark-aware + walk-forward tests: 8 passed in 7.70s.
- Only intended change: one new test file (`tests/test_ema_cross_benchmark_aware_real_aapl.py`); working tree otherwise clean. Offline, committed fixtures only; no live network; no tuning to force SUPPORT.

## What remains unresolved
- Full quant-backtesting suite (971 tests) is too slow to complete in-session (never observed to finish); affected subsets already confirmed green per HANDOFF.md. Bollinger Bands single-asset family still lacks a benchmark-aware falsification guard (no `examples/bollinger_bands_hypothesis.py` exists yet).

## Approaches already tried / failed
- None this session. Direct `run_backtest.py` invocation with a relative `--data` path failed because `_run_backtest_metrics` subprocesses with `cwd=scripts/`; fixed in the test by passing an absolute `data_path` (as the donchian test does via `SRC`).

## One precise next task
Add a benchmark-aware falsification guard for Bollinger Bands on committed AAPL, mirroring `donchian_breakout_hypothesis.py` / `ema_cross_hypothesis.py`:
1. Confirm `run_backtest.py` supports a `bollinger_bands` strategy (inspect `scripts/run_backtest.py` strategy list). If not supported, document that as the blocker and stop.
2. If supported, create `examples/bollinger_bands_hypothesis.py` (benchmark-aware `run_benchmark_aware_hypothesis_test` + `BENCHMARK_CRITERIA` + `N_TRIALS`, buy-and-hold AAPL self-benchmark, 3bp costs, chronological 0.6/0.2/0.2 split, PIT validation) mirroring `ema_cross_hypothesis.py`.
3. Add `tests/test_bollinger_bands_benchmark_aware_real_aapl.py` mirroring `test_ema_cross_benchmark_aware_real_aapl.py`; run the observed metrics once to pin values (rel tol 1e-3), assert verdict NOT SUPPORTED unless evidence warrants, do not tune to force SUPPORT.
4. Verify offline with committed fixtures only (assets/example_data/real_market_data/AAPL.csv); no live network.

Constraints: offline only; relative tolerance only; verdict stays NOT SUPPORTED unless the evidence genuinely supports SUPPORT; smallest reversible change; do not touch inherited marketplace schemas/attribution.
