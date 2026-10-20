# Next task — 2026-10-20

## Task

**Measure the held-out-fraction crossing at larger sample sizes (5,000 / 10,000 bars).**

The held-out-fraction sweep (`measure_test_frac_sweep`) was demonstrated at 2,500 bars, where no fraction crosses the 2.0 plausibility bound. The crossing fraction at larger sample sizes has not been measured, and the alpha side of that sweep has not been measured at all.

## Why this is the next thing

The last session established that the three paths resolve the Sharpe criterion at different sample sizes and that criterion 5 (alpha) crosses the 10% plausibility bound later than criterion 2 (Sharpe) on some paths. The held-out-fraction sweep is the one knob left that trades test observations against training window, and it has only been measured at a single small sample size where the trade-off does not cross the bound. The alpha side of that sweep is entirely unmeasured.

## Evidence and constraints

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `measure_test_frac_sweep(...)` and `_summarize_test_frac_sweep(...)`; the sweep currently reports only the Sharpe crossing (`min_detectable_sharpe`, `expected_max_sharpe`) and only for `PATH_OUT_OF_SAMPLE`. Mirror the alpha analysis there too (`min_detectable_alpha`, `expected_max_alpha` vs `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`), and run the sweep at 5,000 and 10,000 bars.
- Constraint: change no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` stays; re-use the framework's own blocks; the shipped 0.6/0.2/0.2 split remains the default and is unchanged.
- Verification: extend `tests/test_resolution_vs_sample_size.py` pinning the sweep's alpha numbers against the framework's own blocks on a directly re-run analysis, and that no verdict moves.
- Existing baseline to preserve: `test_resolution_vs_sample_size.py` 14/14, `pyflakes` clean, default 0.6/0.2/0.2 split unchanged, `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183.
- Evidence: at 2,500 bars the Sharpe sweep shows `min_detectable_sharpe` falling 2.89 -> 2.24 as `test_frac` grows 0.1 -> 0.3 with no fraction crossing the 2.0 bound; the alpha crossing at 2,500 bars is unresolved.

## Subsequent options (after this task)

- The `test_n_periods` rename (counts test *bars*, not periods; a breaking API change needing its own parity harness).

(End of file - total 23 lines)