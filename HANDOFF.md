# Handoff — falsifiable hypothesis example's advertised controls are now auditable (2026-10-24)

## What changed
- `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`:
  - `run_hypothesis_test(...)` now accepts `commission` and `slippage` keyword args (defaulting to the example's advertised 2bps / 1bps) and records them, alongside the validation path actually engaged, in a new `methodology` block of the returned dict.
  - The cost args are threaded into the `out_of_sample_validation` call (previously hardcoded to `COMMISSION`/`SLIPPAGE` constants), so a caller can run the identical machinery at zero cost.
  - The returned dict gains `methodology`: `commission`, `slippage`, `validation_method`, `selection_criterion`, `walk_forward_window`, `multiple_benchmarks`, `n_benchmarks_loaded`, `param_grid`, `train_frac`, `val_frac`, `test_frac`.
- `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`:
  - Added `test_the_example_records_its_methodology_block` (the methodology block is present and pins the advertised costs, walk-forward path, `best_avg_sharpe` selection, 3-period window, N=2 benchmarks, 0.6/0.2/0.2 split, and the parameter grid).
  - Added `test_the_advertised_costs_are_actually_applied` (running the same machinery at `commission=0, slippage=0` must beat the costed run on net Sharpe and net total return — a deterministic regression guard that the cost path is live, the same shape as the pairs-trading cost sweep).
  - Added `test_the_selection_criterion_is_oos_aware` (selection criterion is `best_avg_sharpe`, and the selected params' average test Sharpe is a real number, so selection genuinely read OOS scores).
  - Added a cached `_cost_result(data_path, commission, slippage)` helper; registry grew 14 → 17 tests.

## What was actually verified
- `tests/test_falsifiable_hypothesis_example.py` → 17 passed (was 14).
- `tests/test_examples_coverage.py` → 39 passed (unchanged; the example's printed banner strings are intact).
- `falsifiable_hypothesis_example.py` standalone → exit 0; positive-control fixture still returns `SUPPORTED` with the new signature.
- Empirical guard values confirmed before encoding: costed run Sharpe −0.3581 / return −1.98% vs zero-cost −0.3293 / −1.81% (costs reduce both); `validation_method=walk_forward`, `selection_criterion=best_avg_sharpe`, `walk_forward_window.effective_periods=3`, `multiple_benchmarks=True`.

## What remains unresolved
- The framework test files (`test_walk_forward.py`, `test_cpcv.py`, `test_performance.py`, `test_resolution_vs_sample_size.py`, `test_out_of_sample_window.py`) are slow (>2 min each) and could not be re-run to completion in-session; they were not modified by this change and are presumed unaffected (only the example and its test file were touched).
- `results/` root artifacts remain retired (missing `splits_test_data.csv`); `results/resolution_floor/*.json` remain reproducible. No change made.

## Approaches already tried
- The prior handoff's suggestion to add walk-forward / cost-sensitivity assertions to the falsifiable example was inspected and found to be already covered elsewhere (`test_examples_coverage.py` covers `trading_costs_robustness_example.py`; `pairs_trading_example` emits walk-forward and cost-sensitivity banners). The real gap was that the falsifiable example *advertised* "all figures net of 2bps commission + 1bps slippage", "walk-forward parameter selection", and "Deflated Alpha Ratio benchmark-selection correction" while returning a dict that carried none of those facts — so a silent break in the cost path or the selection path would not have been caught. The fix pins those advertised facts in the return value and in regression tests.

## One precise next task
- Re-run the slow framework suite (`test_walk_forward.py`, `test_cpcv.py`, `test_performance.py`, `test_resolution_vs_sample_size.py`, `test_out_of_sample_window.py`) to confirm no regression, and if any fail, triage against this change (which touched only `falsifiable_hypothesis_example.py` and its test file). Relevant files: `skills/quantitative-backtesting/tests/test_walk_forward.py`, `tests/test_cpcv.py`, `tests/test_performance.py`, `tests/test_resolution_vs_sample_size.py`, `tests/test_out_of_sample_window.py`.

(End of file - total 25 lines)