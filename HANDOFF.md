# Handoff — regime-dependent performance disclosure rendered in tear sheet

## What changed (this session)
- `skills/quantitative-backtesting/scripts/reporting.py`: Added regime-dependent performance rendering (`regime_analysis`) to the HTML tear sheet and JSON summary for **all four analysis paths**:
  - **Main results** (single backtest) — was already computed, now also rendered (pre-existing `regime_analysis_section` at line 664, tested by `test_tear_sheet_includes_regime_analysis_section`).
  - **Walk-Forward Analysis** — renders `wf_summary.get("regime_analysis")` after the Multiple-Testing Correction section.
  - **CPCV Analysis** — renders `cpcv_summary.get("regime_analysis")` after the Multiple-Testing Correction section.
  - **Monte Carlo Simulation** — renders `mc_summary.get("regime_analysis")` after the Metric Distributions section.
- The existing `regime_analysis_section` function (lines 501-568) is reused; it gracefully handles missing/None regime_analysis by returning an empty list (backward compatible).
- JSON summary (`tear_sheet_summary.json`) now carries `regime_analysis` for all four paths: top-level `summary["regime_analysis"]`, `summary["walk_forward"]["summary"]["regime_analysis"]`, `summary["cpcv"]["summary"]["regime_analysis"]`, `summary["monte_carlo"]["summary"]["regime_analysis"]`.

## What was actually verified
- All 66 `test_reporting.py` tests pass.
- All 23 `test_regime_detection.py` tests pass.
- `test_run_backtest_records_regime_analysis` passes (regime_analysis computed in run_backtest).
- Manual integration tests confirm HTML and JSON rendering for all four analysis paths with distinct regime data.
- Core quantitative-backtesting tests pass: 105 tests in `test_data_loader.py`, `test_performance.py`, `test_strategy_builder.py`.
- 103 `test_run_backtest.py` tests (excluding slow/sweep) pass.

## What remains unresolved
- Full quant gate `python3 -m pytest skills/quantitative-backtesting/tests -q -p no:cacheprovider --tb=short -n 4` has **not** been re-run this session (prior run: 1193 passed, 1 failed = the known artifact-mutation test `test_examples_coverage.py::test_scripts_results_untouched_after_examples`, which is self-inflicted by running the gate and reverted with `git checkout -- .`). Full gate times out as a single blocking run (~60+ min); use `pytest -n 4` with adequate budget.
- pytest-xdist is installed but not pinned in any requirements file.
- The CPCV and Monte Carlo analysis paths do not currently compute `regime_analysis` (only walk_forward's out-of-sample path and run_backtest do). The rendering code is in place and will display it when those paths start computing it.

## Approaches already tried / failed
- Serial full gate: timed out at ~60 min (twice). Do not repeat unchanged.
- Regime analysis rendering: verified green with focused and integration tests; no failure.

## One precise next task
Re-run the full quant gate with `pytest -n 4` and adequate budget, then `git checkout -- .` to restore artifacts, and confirm 1193/1194. Do not commit unless explicitly asked. To re-run the gate: `python3 -m pytest skills/quantitative-backtesting/tests -q -p no:cacheprovider --tb=short -n 4` then `git checkout -- .`.

(End of file - total 33 lines)