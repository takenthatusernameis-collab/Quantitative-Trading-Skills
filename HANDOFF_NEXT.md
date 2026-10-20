# Next task — 2026-10-20

## Task
Extend `scripts/measure_resolution_vs_sample_size.py` so its resolution-vs-sample-size ladder also covers the walk-forward and CPCV paths (today it measures out-of-sample validation only).

At each sample-size rung, run `walk_forward_analysis` and `cpcv_analysis` (shipped configuration: train/test/step months, 5 splits, test size 0.2 for CPCV) and report `summary["test_resolution"].min_detectable_sharpe` together with `expected_max_sharpe` (SR*, the floor no sample size can beat), on the same synthetic control fixture the script already uses (`scripts/generate_positive_control_data.py`; `--data PATH` also supported). The curve answers, per path: at what sample size can the pre-registered criteria confirm a plausible annualized Sharpe, and is there such a size at all?

## Evidence and constraints
- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — entry point `main(argv)` at line 439; imports `out_of_sample_validation` + `_build_test_resolution` from `walk_forward` at lines 79-92; per-rung call at line 146 (`out_of_sample_validation(..., validation_method="walk_forward", ...)`).
- Related code now in place: every sweep point of walk-forward / CPCV / out-of-sample carries `summary["test_resolution"]` plus `sharpe_below_resolution` (`scripts/walk_forward.py` row builders); monte-carlo builds its block via `_build_test_resolution({"deflated_sharpe": dsr}, returns)`; parameter optimization is explicitly unresolved (`null`/`null`).
- Convention: the script calls the framework's own helpers, re-derives nothing, changes no threshold, bound, criterion or verdict; results are properties of the sample and the machinery, not evidence about any security.
- Verified baseline of this session: `test_test_resolution.py` 38/38, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183, rest of suite green except 9 pre-existing `test_reporting.py` failures (matplotlib missing). No swept number moved between HEAD and this session (empirical parity check on commission sweeps for all six paths; `run_backtest` sweep artifacts byte-identical).

## Subsequent options (after this task)
- SR* (floor) as a first-class reported number alongside the resolution.
- `test_n_periods` rename (checks the period-count diagnostic; needs its own parity harness).
