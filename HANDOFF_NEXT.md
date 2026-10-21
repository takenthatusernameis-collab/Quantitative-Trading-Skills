# Next task — why the held-out-fraction sweep is out-of-sample only

## Task

**State explicitly in `references/validation_methods.md` why the held-out-fraction sweep (`--test-fracs`) is measured on the out-of-sample path only.**

The section "How much of the data should be held out?" shows the sweep's numbers and the trade-off it exposes (a larger held-out window buys test observations and costs training data), and the section "The three analysis paths answer it differently" states the per-path configurations. Neither says *why* the sweep touches one path: the walk-forward and CPCV paths are configured in **months** (6-month training window, 2-month test window, 1-month step), not in fractions of the sample, so `test_frac` has no meaning on them; the out-of-sample path is the only one whose split is expressed as fractions.

## Why this is the next task

It has been deferred twice (it is listed as a nice-to-have in the previous two handoffs and as a subsequent option in the last `HANDOFF_NEXT.md`). It is a documentation gap in the part of the methodology that a reader is most likely to misread: the sweep's table is a single-path table presented among three-path results, and nothing says the other two paths are absent by construction rather than by oversight.

## Evidence

- `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — `measure_test_frac_sweep` runs the out-of-sample path only; `WF_TRAIN_MONTHS` / `WF_TEST_MONTHS` / `WF_STEP_MONTHS` are the walk-forward path's units.
- `skills/quantitative-backtesting/references/validation_methods.md` — "How much of the data should be held out?" and "The three analysis paths answer it differently".
- `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` — `test_the_test_frac_sweep_keeps_val_frac_and_sums_to_one` and the sweep's other pins, which are out-of-sample-path only for the same reason.

## Bounded work

1. Add the reason to `references/validation_methods.md` (a short paragraph in the sweep's section, with a pointer to the per-path configurations).
2. Say what the sweep therefore does **not** establish (it is a statement about the out-of-sample path's split, not about the other two paths and not about the criteria).
3. Change no number, no threshold, no bound, no criterion and no verdict; no code change is required.

## Constraints

- No threshold, bound, criterion or verdict moves; `scripts/walk_forward.py` is not in this task's diff.
- A measurement beside the verdict, never part of it.
- The same plain style as the surrounding sections: no marketing adjectives, no claim beyond the measurement.

## Subsequent options (after this task)

- Decide whether the pre-driver ladder fixture (`tests/fixtures/resolution_ladder_2500_to_50000.json`) stays a fixture or becomes a result file only: the re-capture fixture now carries the driver and the status, so the older one is a second source of truth for the same ladder.
