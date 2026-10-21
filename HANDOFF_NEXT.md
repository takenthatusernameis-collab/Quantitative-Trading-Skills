# Next task — measure the CPCV path's lever

## Task

**Sweep the CPCV path's own configuration (the number of splits and the
per-group test fraction) at a fixed sample size, and report the same
resolution numbers the out-of-sample held-out-fraction sweep and the
walk-forward window sweep report.**

The three analysis paths are each configured in the units of their own
analysis, and each path's configuration has now been measured except one.
The out-of-sample path's lever is its held-out fraction (measured by
`--test-fracs`), the walk-forward path's lever is its `(train_months,
test_months)` window configuration (measured by `--wf-windows` in the last
session), and the CPCV path's lever is its `n_splits` and its per-group
`test_size` -- still unmeasured.

## Why this is the next task

- It completes the comparison the reference document already sets up. "The
  three analysis paths answer it differently" names each path's
  configuration, and the two-path sweeps now sit next to it; the third
  path's configuration is the only one a reader cannot find a measurement
  behind.
- The trade-off is the same shape as the two that have been measured, and
  the CPCV path is the one the document says has the *lowest* floor of the
  three (0.45 - 1.04 at 2,500 bars against 1.24 - 2.23 for the
  out-of-sample path). Whether that floor is a property of the *path* or
  of its *configuration* is exactly the question this sweep answers: a
  different number of splits or a different per-group test fraction
  changes how many folds there are, how much each fold trains on, and how
  many out-of-sample observations are pooled.
- The method, the fixtures, the report shape and the pins all exist. The
  last two sweeps are the same code path with one parameter swept, so this
  is a repeat of a known shape, not a new design.

## Evidence

- `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`
  - `_run_cpcv` (~line 347) hard-codes `CPCV_N_SPLITS` / `CPCV_TEST_SIZE`
    (5 and 0.2) -- the sweep has to parameterise them, exactly as
    `_run_walk_forward` was parameterised for `--wf-windows`.
  - `measure_wf_window_sweep` and `_summarize_wf_window_sweep` are the
    pattern to follow; `measure_test_frac_sweep` is the older one.
  - `main` is where `--test-fracs` and `--wf-windows` are dispatched; the
    new flag must refuse `--data` for the same reason and must refuse to
    run alongside the other two sweeps.
- `skills/quantitative-backtesting/scripts/walk_forward.py`
  - `cpcv_analysis` (~line 3145) takes `n_splits` (>= 2, line 3300) and
    `test_size` (the fraction of each group used as that group's test
    set), plus `purge_size` and `embargo_size`.
  - The number of folds is combinatorial in `n_splits` (the framework
    iterates over split pairs), so `n_splits` changes the fold count and
    the pooled out-of-sample record at the same time.
- `skills/quantitative-backtesting/references/validation_methods.md`
  - "The three analysis paths answer it differently" -- where the CPCV
    path's configuration is named (5 splits, 20% of each group) and where
    the result belongs.
  - "How long should the walk-forward windows be?" -- the section to
    follow in shape, and the one to place the CPCV sweep next to.
- `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`
  - the thirteen `--wf-windows` pins registered in `TEST_REGISTRY` are the
  pattern: scope, parity with the framework's own block, the shipped
    configuration unchanged, the series named, `--data` refused, the
    capture being the tool's own `--json` output, the trimmed fixture, and
    the document's own limits.
- Constraint carried from the framework: `n_splits >= 2`, and
  `test_size` is a fraction *of each group*, not of the sample -- the
  framework's own message at `walk_forward.py:4683` says so, and a sweep
  that reported it as a fraction of the sample would misstate it.

## Bounded work

1. Add a CPCV configuration sweep to the measurement script: a
   fixed-sample-size sweep over `(n_splits, test_size)` on the **CPCV**
   path, measured on the same synthetic control fixture, naming the series
   it measured, refusing `--data` for the same reason the other two sweeps
   refuse it, and reporting the same numbers: test observations, minimum
   confirmable Sharpe and alpha, the deflation floors SR* and alpha*, the
   observed statistics, and the per-configuration inside/outside-the-bound
   flags.
2. Capture the measurement with its provenance (command, environment,
   fixture construction, script commit, bounds) in `results/resolution_floor/`,
   and a trimmed fixture in `tests/fixtures/`.
3. Pin it the way the window sweep is pinned: the sweep's numbers are the
   framework's own blocks (re-run directly), the capture is the tool's own
   `--json` output, the configuration is named, and the shipped 5 splits /
   20% configuration is unchanged.
4. Document it next to the other two sweeps: the numbers, the trade-off
   they expose, **what the sweep does not establish**, and the fact that
   no threshold, bound, criterion or verdict moves with it.

## Constraints

- No threshold, bound, criterion or verdict moves; `scripts/walk_forward.py`
  is not in this task's diff, and the shipped 5 splits / 20% configuration
  stays the default.
- A measurement beside the verdict, never part of it.
- The same plain style as the surrounding sections: no marketing
  adjectives, no claim beyond the measurement, and the synthetic fixture is
  named as a formula, not a market.
- The environment needs `numpy` and `pandas` (both installed);
  `matplotlib` is still missing, so `tests/test_reporting.py` cannot run
  until the full `requirements.txt` is installed.

## Subsequent options (after this task)

- Decide whether the pre-driver ladder fixture
  (`tests/fixtures/resolution_ladder_2500_to_50000.json`) stays a fixture
  or becomes a result file only: the re-capture fixture carries the driver
  and the status, so the older one is a second source of truth for the same
  ladder. This has been flagged twice and is still open.
- Measure the two sweeps on a real history. Both sweeps refuse `--data`
  today, because the fixture's numbers must not be reported under a real
  history's name. A real-history version would need the benchmark set
  resolved from the file's directory, the way `--data` already does for the
  ladder, and a decision about which windows are even meaningful on that
  history.
