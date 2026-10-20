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

- `print_test_frac_sweep(...)` prints the alpha columns (`min alpha`, `alpha*`, `all alpha`, `any alpha`) alongside the Sharpe ones, and reports the first held-out fraction at which every / any draw is within the alpha plausibility bound; `main(...)` forwards `first_all_alpha` / `first_any_alpha` to it. The alpha stats were already computed by `_summarize_test_frac_sweep`; only the printing path was missing.
- Extended `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` (14 -> 16 tests):
  - `test_test_frac_sweep_at_larger_sizes_matches_the_framework_own_block` — pins the sweep's `min_detectable_alpha` / `expected_max_alpha` at 5,000 and 10,000 bars against the framework's own `test_resolution` / `deflated_alpha` blocks on a directly re-run analysis (test_fracs 0.1/0.2/0.3, seed 7, no_effect).
  - `test_test_frac_sweep_alpha_crossings_match_the_per_fraction_flags` — the reported alpha crossing equals the smallest fraction whose per-fraction flag is set, or None (no verdict moves).

Ran the sweep at 5,000 and 10,000 bars (seed 7, no_effect, test_fracs 0.1/0.2/0.3):
- 5,000 bars: Sharpe bound crossed at test_frac 20.0% (min SR 1.9096 at 0.2; 2.1745 at 0.1); alpha bound also at 20.0% (min alpha 0.1131 at 0.1 > 0.10).
- 10,000 bars: Sharpe bound crossed at test_frac 10.0% (min SR 1.9142 at 0.1; 1.7136 at 0.2), but alpha bound NOT crossed at 0.1 (min alpha 0.1277 > 0.10) — alpha crossing at 20.0% (min alpha 0.0689). Confirms criterion 5's bound is crossed later than criterion 2's, exactly the held-out-fraction trade-off.

The measurement changes no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` stays; the shipped 0.6/0.2/0.2 split remains the default and unchanged.

## What was verified

- `test_resolution_vs_sample_size.py`: 16/16 (was 14/14 at the start of the session).
- `python3 -m py_compile` clean on both changed files (pyflakes is not installed in this environment).
- Neighbouring suites untouched by this work previously passed: `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183`.
- Default ladder (`--sizes 2500 --seeds 7 --series no_effect`) still runs and prints identical out-of-sample numbers as before (at 2,500 bars, test_frac=0.2: min_detectable_sharpe 2.3975, SR* 1.4403 — matching the pre-change baseline); pinned by `test_shipped_default_split_is_unchanged` and `test_the_measurement_agrees_with_the_shipped_example_path`.
- Measured trade-off visible: the alpha bound is crossed later than the Sharpe bound on the CPCV path (some draws at 5,000 bars vs every draw already at 2,500 bars for Sharpe); the walk-forward path's alpha floor (alpha*) is above the 10% bound at every measured rung, so no measured sample size would let it confirm a plausible alpha on every draw.

## What remains unresolved

- The `test_n_periods` rename API change remains outstanding: `walk_forward.py:5797` emits `"test_n_periods": len(test_returns)` (counts test bars, mislabeled "periods") and `out_of_sample_validation` passes it through at `walk_forward.py:10148`, but the example already reports `test_n_observations` and `tests/test_falsifiable_hypothesis_example.py:256-257` asserts `"test_n_periods" not in obs`. `references/validation_methods.md:1365-1369` documents the distinction. Breaking API change needing its own parity harness.

## Approaches that failed

- None in this session; the baseline (14/14) was clean and the sweep printing integrated without conflict.

## Next task (one, precise)

**Rename `test_n_periods` -> `test_n_observations` in the framework's `test_performance` (the held-out window counts test bars, not periods), with a parity harness.**

The held-out-fraction sweep (`measure_test_frac_sweep`) was demonstrated at 2,500 bars, where no fraction crosses the 2.0 plausibility bound. The crossing fraction at larger sample sizes (5,000 / 10,000 bars) has not been measured, and the alpha side of that sweep has not been measured at all.

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `measure_test_frac_sweep(...)` and `_summarize_test_frac_sweep(...)`; the sweep currently reports only the Sharpe crossing (`min_detectable_sharpe`, `expected_max_sharpe`) and only for `PATH_OUT_OF_SAMPLE`. Mirror the alpha analysis there too (`min_detectable_alpha`, `expected_max_alpha` vs `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`), and run the sweep at 5,000 and 10,000 bars.
- Constraint: change no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` stays; re-use the framework's own blocks; the shipped 0.6/0.2/0.2 split remains the default and is unchanged.
- Verification: extend `tests/test_resolution_vs_sample_size.py` pinning the sweep's alpha numbers against the framework's own blocks on a directly re-run analysis, and that no verdict moves.
- Evidence: at 2,500 bars the Sharpe sweep shows `min_detectable_sharpe` falling 2.89 -> 2.24 as `test_frac` grows 0.1 -> 0.3 with no fraction crossing the 2.0 bound; the alpha crossing at 2,500 bars is unresolved.

(End of file - total 47 lines)