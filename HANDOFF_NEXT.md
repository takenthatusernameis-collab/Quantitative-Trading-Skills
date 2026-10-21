# Next task — measure the walk-forward path's window lever

## Task

**Sweep the walk-forward path's own configuration (the training window and
the test window) at a fixed sample size, and report the same resolution
numbers the out-of-sample held-out-fraction sweep reports.**

The held-out-fraction sweep is measured on the out-of-sample path only,
because that path is the only one of the three whose split is expressed as
fractions of the sample: the walk-forward path is configured in *months* and
the CPCV path in a *number of splits and a per-group test fraction*. The
last session established and pinned that statement — and it also means the
walk-forward path has a lever of its own (`train_months`, `test_months`)
that has never been measured. The trade-off the out-of-sample sweep exposes
should appear there too: a longer training window gives a better-estimated
parameter selection but fewer windows fit in the sample, and a shorter test
window gives more, shorter out-of-sample observations.

## Why this is the next task

- The sweep's scope is now stated in the reference document, and the
  document says the other two paths are governed by "their own
  configurations". A reader who follows that pointer finds no measurement
  behind it: the walk-forward path's numbers in the three-path table are
  all at the shipped 6/2/2 configuration, and the document nowhere reports
  what a different window would do.
- It is the same kind of question the skill already answers for the
  out-of-sample path ("How much of the data should be held out?"), so the
  method, the fixtures, the report shape and the pins all exist and can be
  reused rather than reinvented.
- It compares two of the three analysis paths on the same footing, which is
  what the skill's purpose is: not one best-looking curve, but measured
  statements about which configuration can resolve what.

## Evidence

- `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`
  - `_run_walk_forward` (~line 318) hard-codes `WF_TRAIN_MONTHS` /
    `WF_TEST_MONTHS` / `WF_STEP_MONTHS` (line 209) — the sweep has to
    parameterise them.
  - `measure_test_frac_sweep` (~line 755) and `_summarize_test_frac_sweep`
    (~line 1280) are the existing pattern for a fixed-sample-size sweep, and
    `main` (~line 1952) is where `--test-fracs` is dispatched.
  - `walk_forward_analysis` already accepts `train_months`, `test_months`
    and `step_months`.
- `skills/quantitative-backtesting/references/validation_methods.md`
  - "How much of the data should be held out?" — the fraction sweep and its
    tables; the pattern to follow.
  - "The three analysis paths answer it differently" — where the three
    paths' configurations are now stated, and where a window sweep's result
    belongs.
- `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`
  - `test_test_frac_sweep_keeps_val_frac_and_sums_to_one` and the sweep's
    other pins — the pattern for the new pins.
- `skills/quantitative-backtesting/tests/test_walk_forward.py:1059` —
  `walk_forward_analysis` refuses `step_months < test_months`, so a
  test-window sweep must set the step with it (the non-overlapping step is
  `step_months == test_months`).

## Bounded work

1. Add a window sweep to the measurement script: a fixed-sample-size sweep
   over `(train_months, test_months)` on the **walk-forward** path, measured
   on the same synthetic control fixture, naming the series it measured
   (the null calibration and the positive control), refusing `--data` for
   the same reason the fraction sweep refuses it, and reporting the same
   numbers: test observations, minimum confirmable Sharpe and alpha, the
   deflation floors SR* and alpha*, the observed statistics, and the
   per-configuration inside/outside-the-bound flags.
2. Capture the measurement with its provenance (command, environment, fixture
   construction, script commit, bounds) in `results/resolution_floor/`, and
   a trimmed fixture in `tests/fixtures/`.
3. Pin it: the sweep's numbers are the framework's own blocks (re-run
   directly, as the fraction sweep's pins do), the capture is the tool's own
   `--json` output, the configuration is named, and the shipped 6/2/2
   configuration is unchanged.
4. Document it next to the fraction sweep: the numbers, the trade-off they
   expose, **what the sweep does not establish**, and the fact that no
   threshold, bound, criterion or verdict moves with it.

## Constraints

- No threshold, bound, criterion or verdict moves; `scripts/walk_forward.py`
  is not in this task's diff, and the shipped 6/2/2 configuration stays the
  default.
- A measurement beside the verdict, never part of it.
- The same plain style as the surrounding sections: no marketing adjectives,
  no claim beyond the measurement, and the synthetic fixture is named as a
  formula, not a market.
- The environment needs `numpy` and `pandas` installed (this session
  installed them; `matplotlib` is still missing, so `tests/test_reporting.py`
  cannot run until the full `requirements.txt` is installed).

## Subsequent options (after this task)

- Decide whether the pre-driver ladder fixture
  (`tests/fixtures/resolution_ladder_2500_to_50000.json`) stays a fixture or
  becomes a result file only: the re-capture fixture carries the driver and
  the status, so the older one is a second source of truth for the same
  ladder.
- The CPCV path's lever (the number of splits and the per-group test
  fraction) is the remaining unmeasured configuration of the three paths.
