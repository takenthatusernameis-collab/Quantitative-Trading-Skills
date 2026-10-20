# Next task — 2026-10-20

## Task

Measure the **out-of-sample path's test resolution as a function of the held-out fraction** (`test_frac`): at a fixed sample size, how much of the data must be held out before the held-out test window can resolve a plausible annualized Sharpe?

Sweep `test_frac` (with `val_frac = 0.2` and `train_frac = 0.8 - test_frac`, so the three always sum to 1) on the same synthetic control fixture the measurement already uses, and report per `test_frac`: the framework's own `summary["test_resolution"].min_detectable_sharpe`, the deflation floor `expected_max_sharpe` (SR\*), and the crossing point of the 2.0 plausibility bound.

The trade-off to measure: a larger held-out window gives the test more observations (better resolution) but shortens the training window, which raises the SR\* floor, because the trial Sharpes the floor is estimated from are then estimated on less data. The question is where the two effects cross.

## Why this is the next thing

The last session established that the three analysis paths resolve a plausible effect at **different** sample sizes — the out-of-sample path (whose criterion 2 is evaluated on the held-out test window) last, at 10,000 bars, the walk-forward path at 5,000, the CPCV path at 2,500 — and that the out-of-sample path is the binding constraint *because* its test observations grow at a fifth of the rate the sample grows. That makes the size of the held-out window a first-class design parameter, and the framework currently fixes it at 0.6/0.2/0.2 without saying what it costs.

## Evidence and constraints

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — the split constants (`TRAIN_FRAC, VAL_FRAC, TEST_FRAC`, line 133) sit next to `WF_TRAIN_MONTHS` (line 134); `measure_synthetic` (line 432) -> `_measure_sample` (line 339) -> `_run_validation` (line 202, the `out_of_sample_validation` call) is the per-sample chain; `measure_ladder` (line 507) builds the ladder; `main` (line 803) is the CLI entry point; `_summarize_path` (line 563) produces the per-path crossing summary.
- The framework call is `out_of_sample_validation(data=…, train_frac=…, val_frac=…, test_frac=…, …)`; the resolution block it attaches to its summary is the one to read (`summary["test_resolution"]`), together with `summary["deflated_sharpe"]["expected_max_sharpe"]` for SR\*.
- Convention: the script calls the framework's own helpers, re-derives nothing, changes no threshold, bound, criterion or verdict; results are properties of the sample and the machinery, not evidence about any security.
- Constraints: the shipped 0.6/0.2/0.2 split stays the default and must not change; the sweep is a measurement beside the verdict; the data is the synthetic control fixture (`scripts/generate_positive_control_data.py`), a formula, not a market.
- Verification: extend `tests/test_resolution_vs_sample_size.py` with a pin that each swept split's numbers equal the framework's own blocks for that split, and that the shipped default split's numbers are unchanged.
- Verified baseline of this session: `test_resolution_vs_sample_size.py` 9/9, `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183; `pyflakes` clean on the changed files.

## Subsequent options (after this task)

- Summarise the **alpha** resolution per path (criteria 3 and 5). The data is already collected (`min_detectable_alpha` per path per rung); what is missing is the per-path crossing analysis. The alpha bound (10%) is crossed later than the Sharpe bound (2.0) on some paths — e.g. CPCV at 10,000 bars still reports 12.6% on one draw — so the two criteria have different sample-size requirements, which the report should state.
- The `test_n_periods` rename (the key counts test *bars*, not periods; the example already renames it to `test_n_observations`). It is a breaking API change and needs its own parity harness.
