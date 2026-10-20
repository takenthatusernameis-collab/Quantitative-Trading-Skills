# Handoff — 2026-10-20 (session)

## What changed

Implemented the alpha resolution per path from HANDOFF_NEXT.md: `_summarize_path` now mirrors the Sharpe crossing analysis for criterion 5, in
`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`:

- `per_size_alpha` — per rung, per path: `min/max_min_detectable_alpha`, `max/min_expected_max_alpha` (alpha*), draws measured/resolved/within bound, `all_within_bound` / `any_within_bound` against `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`.
- `first_size_all_within_alpha_bound` / `first_size_any_within_alpha_bound` — the first rung at which every / any draw's minimum confirmable annualized alpha crossed the 10% bound.
- `min_min_detectable_alpha`, `max_min_detectable_alpha`, `max_expected_max_alpha`, `alpha_floor_at_largest_size`, `alpha_floor_beyond_plausible_bound`, `alpha_floor_beyond_plausible_bound_at_largest_size`, `all_rungs_within_alpha_bound`, `any_rungs_within_alpha_bound` — exposed in `summary.by_path[*]`.
- `print_path_summary(...)` prints the alpha crossing alongside the Sharpe one, and states explicitly when the alpha bound is crossed later than the Sharpe bound.
- Module and `_summarize_path` docstrings record that the two criteria cross at different sample sizes.

The measurement re-reads the framework's own `summary["test_resolution"].min_detectable_alpha` and `summary["deflated_alpha"].expected_max_alpha`; it changes no threshold, bound, criterion or verdict.

Extended `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` (12 -> 14 tests):
- `test_each_path_reports_the_framework_s_own_alpha_block` — pins the walk-forward and CPCV paths' `min_detectable_alpha` and `expected_max_alpha` against the framework's own blocks on a directly re-run analysis.
- `test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound` — pins the per-path alpha crossing points against the measured data and states the ordering.

## What was verified

- `test_resolution_vs_sample_size.py`: 14/14.
- Neighbouring suites untouched by this work previously passed: `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183`.
- `pyflakes` clean on both changed files.
- Default ladder (`--sizes 2500 --seeds 7 --series no_effect`) still runs and prints identical out-of-sample numbers as before (at 2,500 bars, test_frac=0.2: min_detectable_sharpe 2.3975, SR* 1.4403 — matching the pre-change baseline).
- Measured trade-off visible: the alpha bound is crossed later than the Sharpe bound on the CPCV path (some draws at 5,000 bars vs every draw already at 2,500 bars for Sharpe); the walk-forward path's alpha floor (alpha*) is above the 10% bound at every measured rung, so no measured sample size would let it confirm a plausible alpha on every draw.

## What remains unresolved

- The held-out-fraction sweep was demonstrated at 2,500 bars where no fraction crosses the bound; the crossing fraction at larger sample sizes (e.g. 5,000 / 10,000 bars) has not been measured.
- The `test_n_periods` rename API change remains outstanding.

## Approaches that failed

- None in this session; the baseline (12/12) was clean and the alpha analysis integrated without conflict.

## Next task (one, precise)

**Measure the held-out-fraction crossing at larger sample sizes.**

The held-out-fraction sweep (`measure_test_frac_sweep`) was demonstrated at 2,500 bars, where no fraction crosses the 2.0 plausibility bound. The crossing fraction at larger sample sizes (5,000 / 10,000 bars) has not been measured, and the alpha side of that sweep has not been measured at all.

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `measure_test_frac_sweep(...)` and `_summarize_test_frac_sweep(...)`; the sweep currently reports only the Sharpe crossing (`min_detectable_sharpe`, `expected_max_sharpe`) and only for `PATH_OUT_OF_SAMPLE`. Mirror the alpha analysis there too (`min_detectable_alpha`, `expected_max_alpha` vs `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`), and run the sweep at 5,000 and 10,000 bars.
- Constraint: change no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` stays; re-use the framework's own blocks; the shipped 0.6/0.2/0.2 split remains the default and is unchanged.
- Verification: extend `tests/test_resolution_vs_sample_size.py` pinning the sweep's alpha numbers against the framework's own blocks on a directly re-run analysis, and that no verdict moves.
- Evidence: at 2,500 bars the Sharpe sweep shows `min_detectable_sharpe` falling 2.89 -> 2.24 as `test_frac` grows 0.1 -> 0.3 with no fraction crossing the 2.0 bound; the alpha crossing at 2,500 bars is unresolved.

(End of file - total 47 lines)