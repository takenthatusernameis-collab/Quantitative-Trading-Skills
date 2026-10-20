# Next task — 2026-10-20

## Task

Summarise the **alpha resolution per path** (criteria 3 and 5): for each analysis path, at which sample size does the minimum confirmable annualized alpha cross the framework's 10% plausibility bound — on every draw and on any draw?

The resolution-vs-sample-size ladder already collects `min_detectable_alpha` per path per rung, but `_summarize_path` only analyses the Sharpe crossing. Add a mirror alpha analysis: per path, `first_size_all_within_bound` / `first_size_any_within_bound` for alpha (`min_detectable_alpha <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA`), plus the per-rung alpha floor (`expected_max_alpha`), exposed in `summary.by_path[*]`. State that the alpha bound is crossed later than the Sharpe bound on some paths (e.g. CPCV at 10,000 bars still reports 12.6% on one draw), so the two criteria have different sample-size requirements.

## Why this is the next thing

The last session established the three paths resolve the Sharpe criterion at different sample sizes and that `min_detectable_alpha` is already collected per path per rung but never summarised the way Sharpe is. Criteria 3 (raw alpha, 10% bound via the t-test) and 5 (deflated alpha, 10% bound) therefore have an unresolved crossing profile — the report should state it explicitly rather than leave it implicit.

## Evidence and constraints

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `_summarize_path` (builds `per_size[*]` with `min/min_detectable_sharpe`, `max_expected_max_sharpe`, `all_within_bound`/`any_within_bound`); mirror it for alpha using `min_detectable_alpha`, `expected_max_alpha`, `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`.
- Constraint: change no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` stays; re-use the framework's own `summary["test_resolution"].min_detectable_alpha`; do not re-derive.
- Verification: extend `tests/test_resolution_vs_sample_size.py` pinning each path's alpha crossing against the framework's own blocks on a directly re-run analysis, and that no verdict moves.
- Existing baseline to preserve: `test_resolution_vs_sample_size.py` 12/12, `pyflakes` clean, default 0.6/0.2/0.2 split unchanged, `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183.

## Subsequent options (after this task)

- The `test_n_periods` rename (counts test *bars*, not periods; a breaking API change needing its own parity harness).
- Measuring the held-out-fraction crossing at larger sample sizes (5,000 / 10,000 bars) now that the sweep exists.
