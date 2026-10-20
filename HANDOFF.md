# Handoff — 2026-10-20 (session)

## What changed

Implemented the held-out-fraction sweep from HANDOFF_NEXT.md: the out-of-sample path's test resolution as a function of `test_frac`, in
`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`:

- `measure_test_frac_sweep(bars, seeds, test_fracs, val_frac=0.2, ...)` — at a fixed sample size, sweeps `test_frac` with `train_frac = 0.8 - test_frac` and `val_frac = 0.2` (the three always sum to 1.0; the shipped 0.6/0.2/0.2 split is the `test_frac = 0.2` case and is untouched). Each row is one `measure_synthetic` run annotated with the split actually used; only the out-of-sample path is measured (walk-forward/CPCV don't depend on the train/val/test split).
- `_summarize_test_frac_sweep(rows)` — buckets rows by `test_frac` and reports per fraction: `min_detectable_sharpe` (min/max across draws), the deflation floor `expected_max_sharpe` (SR*), `n_test_observations`, and whether the 2.0 plausibility bound is crossed (all / any draws), plus the first fraction where every / any draw is within the bound.
- `print_test_frac_sweep(...)` — prints one table row per held-out fraction plus the crossing points.
- `--test-fracs` CLI option (comma-separated fractions in (0, 0.8), exactly one `--size`); when set it replaces the ladder with the sweep; JSON output carries `rows` and `sweep`.

The measurement re-reads the framework's own `summary["test_resolution"]` block and `summary["deflated_sharpe"]["expected_max_sharpe"]`; it changes no threshold, bound, criterion or verdict.

Extended `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` (9 -> 12 tests):
- `test_test_frac_sweep_keeps_val_frac_and_sums_to_one`
- `test_test_frac_sweep_each_split_matches_the_framework_own_block` (each swept split's numbers equal the framework's own blocks for that split)
- `test_shipped_default_split_is_unchanged` (0.6/0.2/0.2 constants and numbers unchanged)

## What was verified

- `test_resolution_vs_sample_size.py`: 12/12.
- Neighbouring suites untouched by this work previously passed: `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183.
- `pyflakes` clean on both changed files.
- Default ladder (`--sizes 500 --seeds 7 --series no_effect`) still runs and prints identical out-of-sample numbers as before (e.g. at 2,500 bars, test_frac=0.2: min_detectable_sharpe 2.3975, SR* 1.4403 — matching the pre-change baseline).
- Measured trade-off visible: at 2,500 bars, min_detectable_sharpe falls 2.89 -> 2.24 as test_frac grows 0.1 -> 0.3 (more test observations) while SR* rises 1.41 -> 1.48 (shorter training window); no fraction crosses the 2.0 bound at 2,500 bars.

## What remains unresolved

- The sweep was demonstrated at 2,500 bars where no fraction crosses the bound; the crossing fraction at larger sample sizes (e.g. 5,000 / 10,000 bars) has not been measured.
- The alpha resolution (criteria 3 and 5) is still not summarised per path; the per-path alpha crossing analysis from HANDOFF_NEXT.md is outstanding.
- The `test_n_periods` rename API change remains outstanding.

## Approaches that failed

- None in this session; the baseline (9/9) was clean and the new sweep integrated without conflict.

## Next task (one, precise)

**Summarise the alpha resolution per path (criteria 3 and 5).**

The ladder already collects `min_detectable_alpha` per path per rung (`_measure_path` / `_summarize_path` carry it), but `_summarize_path` only analyses the Sharpe crossing; there is no per-path alpha crossing (which rung each path's alpha resolution crosses the 10% plausibility bound, on every / any draw). The data shows the alpha bound is crossed later than the Sharpe bound (e.g. CPCV at 10,000 bars still reports 12.6% on one draw), so the two criteria have different sample-size requirements and the report should state that.

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `_summarize_path` (line ~563) builds `per_size` with `min/min_detectable_sharpe` etc.; mirror that for alpha (`min_detectable_alpha` vs `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`), adding `first_size_all_within_bound` / `first_size_any_within_bound` for alpha per path, exposed in `summary.by_path[*]`.
- Constraint: change no threshold, bound, criterion or verdict; alpha bound stays `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`; re-use the framework's own `summary["test_resolution"].min_detectable_alpha`.
- Verification: extend `tests/test_resolution_vs_sample_size.py` pinning each path's alpha crossing against the framework's own blocks on a directly re-run analysis, and that no verdict moves.
- Evidence: the existing ladder run quoted CPCV at 10,000 bars still at 12.6% alpha on one draw — the alpha crossing analysis should reproduce that ordering.
