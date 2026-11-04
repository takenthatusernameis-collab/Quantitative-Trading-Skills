# Handoff — simple_momentum elevated-cost + param-sensitivity sweep-guard layer complete

## What changed
- `skills/quantitative-backtesting/examples/simple_momentum_hypothesis.py` (+153/-2):
  - Added `ELEVATED_COST_SWEEP_LEVELS` (advertised 3bps reference then 5bp+2.5bp, 10bp+5bp, 20bp+10bp round-trip).
  - Added `DEFAULT_PARAMS = '{"fast_period": 10, "slow_period": 30}'`.
  - Refactored `_run_backtest_metrics` to accept a `params=DEFAULT_PARAMS` argument (was hardcoded; backward-compatible).
  - Added `run_elevated_cost_sweep(data_path, grid=ELEVATED_COST_SWEEP_LEVELS)` and `run_param_sensitivity_sweep(data_path, grid=PARAM_SENSITIVITY_GRID)`, mirroring `macd_hypothesis.py` (weak two-criterion verdict: oos_sharpe > 0, oos_total_return > 0; params grid is 2-tuples fast/slow).
- `skills/quantitative-backtesting/tests/test_simple_momentum_elevated_cost_real_aapl.py` (new): pins observed metrics per cost level (rel tol 1e-3), determinate verdicts, honest methodological note.
- `skills/quantitative-backtesting/tests/test_simple_momentum_param_sensitivity_real_aapl.py` (new): pins observed metrics per parameter setting (rel tol 1e-3), determinate verdicts, honest methodological note.

## What was actually verified
- `py_compile` on the modified example + both new tests: OK.
- Focused gate: `test_simple_momentum_elevated_cost_real_aapl.py` + `test_simple_momentum_param_sensitivity_real_aapl.py` + `test_simple_momentum_benchmark_aware_real_aapl.py` → **4 passed, 0 failed** in 8.40s.
- Full simple_momentum family (`test_simple_momentum_*.py`) → **22 passed, 0 failed** in 59.29s (no regression from the `_run_backtest_metrics` signature change).
- Offline, committed fixtures only (`assets/example_data/real_market_data/AAPL.csv`); no live network; no tuning to force SUPPORT.

## Honest methodological finding (preserve, no hype)
- Under the weak two-criterion sweep, simple momentum is SUPPORTED at every tested cost level (Sharpe 1.50→1.40, return 76.2%→69.2% up to 20bp+10bp) and SUPPORTED across all six pre-registered parameter settings (Sharpe 1.45→1.86).
- BUT the benchmark-aware guard (`test_simple_momentum_benchmark_aware_real_aapl.py`, pre-existing, pinned NOT SUPPORTED) records: simple momentum does NOT beat buy-and-hold AAPL (strategy 76.2% vs benchmark 77.4%), benchmark alpha not significant (raw p=0.12), Deflated Sharpe p=0.41 across 6 trials. Verdict NOT SUPPORTED.
- These are consistent: the weak sweep overstates the edge; the benchmark-aware control falsifies it. Do not describe simple momentum as profitable or production-ready.

## What remains unresolved
- The full `skills/quantitative-backtesting/tests/` suite (~981 tests, ~34 min) has NOT been run as a single full-regression pass this session; per-file focused gates are the verified mode. My `_run_backtest_metrics` change is backward-compatible (default param) and only simple_momentum tests import it, but a full-suite baseline would confirm no cross-file regression.
- No walk-forward guard exists for simple_momentum (none exists for the family; not part of this slice).

## Approaches already tried / failed
- None this session; all verification passed on first run. No approach was abandoned.

## One precise next task
Run the complete `skills/quantitative-backtesting/tests/` suite as a single full-regression pass and record the pass/fail count, since individual slices were verified at different times and no full-suite baseline exists this session. Investigate and fix any failure; if a failure is a pre-existing flake unrelated to this session's changes, document it.

Evidence/constraints:
- Baseline slices green this session: simple_momentum family 22/22; focused gate 4/4; bollinger/donchian/macd/mean_reversion sweep guards green in prior sessions.
- Offline, committed fixtures only; no live network; do not modify framework source or fixtures; do not commit unless explicitly asked.
- Gate command template: `cd skills/quantitative-backtesting && python3 -m pytest tests/ -p no:cacheprovider -q` (expect several minutes; run from repo root with full `skills/quantitative-backtesting/tests/...` path — running pytest from inside `skills/quantitative-backtesting/` with a bare `tests/...` path fails due to rootdir/conftest resolution).
