# Next task — 2026-10-20 (session)

## Task

**Settle the walk-forward path's alpha floor: measure it at 25,000 and 50,000 bars, and check whether
the tool's "no sample size would let this path confirm a plausible alpha" message survives. If it does
not survive, correct the message (not the bound).**

## Why this is the next thing

The held-out-fraction sweep on the positive control is done and pinned
(`tests/test_resolution_vs_sample_size.py`, 21/21, with three negative controls that fail when the thing
they pin is broken). The effect series' observed statistic clears the framework's plausibility bounds on
every draw while the null's does not, and the two series' minimum confirmable effects are nearly the
same -- so the machinery discriminates, and the resolution is a property of the sample.

What is left in the resolution work is a *stated conclusion that was never measured to its limit*. The
measurement tool reports, for the walk-forward path, that the alpha floor is above the 10% plausibility
bound at every measured rung and therefore that "no sample size would let this path confirm a plausible
effect". The ladder only went to 10,000 bars. A conclusion phrased as "no sample size" that rests on a
rung ladder is a conclusion about the *measured range*, and the floor is known to fall as the sample
grows -- so the message may be wrong, and the size at which it becomes right is exactly the kind of
number a research handoff should carry.

This is a measurement first and, at most, a wording fix second. No threshold moves.

## Evidence and constraints

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`. The numbers to
  read are in the per-path summary: `alpha_floor_at_largest_size` (alpha* at the largest rung measured)
  and `alpha_floor_beyond_plausible_bound` (was the floor above the 10% bound at *every* measured rung?).
  `--paths walk_forward,cpcv` measures the two paths that price their test on pooled out-of-sample
  returns; `--series both` measures the null calibration and the control.
- What is measured today (seed 7, both series, from `summary["by_path"]`):

  | Path | alpha* at 5,000 bars | alpha* at 10,000 bars | floor above the 10% bound? |
  | --- | --- | --- | --- |
  | out-of-sample | 0.0185 - 0.0219 | 0.0174 - 0.0240 | no |
  | walk-forward | 0.0026 - 0.0466 | 0.0059 - 0.0656 | no (seed 7) |
  | CPCV | 0.0056 - 0.1228 | 0.0178 - 0.0492 | no (seed 7) |

  Over three seeds (7, 1, 2024) the walk-forward path's floor **is** above the bound at every rung
  measured so far -- `tests/test_resolution_vs_sample_size.py` pins
  `by_path[WALK_FORWARD]["alpha_floor_beyond_plausible_bound"] is True` and
  `..._at_largest_size is True` -- so the other seeds carry the verdict, and the floor's seed-to-seed
  spread (0.0026 to 0.0656 at 10,000 bars on seed 7 alone) is as wide as the bound it is being compared
  against. That is the uncertainty to resolve, not a detail.
- Cost: the 5,000/10,000-bar full ladder is ~25 s per rung; 25,000 and 50,000 bars are minutes per rung
  (the fixture is regenerated at the requested length, so the sample size is not the limit).
- Constraint: change no threshold, bound, criterion or verdict. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`
  and the 2.00 Sharpe bound stay; the shipped 0.6/0.2/0.2 split stays the default. If the floor falls
  under the bound at a larger sample, the fix is to the *message* -- "no **measured** sample size", with
  the largest rung measured reported next to it -- not to the bound and not to the criterion.
- Verification: extend `tests/test_resolution_vs_sample_size.py` with the measured floors at the larger
  rungs, and -- if the message changes -- a test that the printed summary says "measured" and names the
  largest rung it measured. Keep the fixture's synthetic nature stated wherever the numbers are reported.

## Subsequent options (after this task)

- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`) carries the same mislabel the
  completed rename removed from `test_performance`: it is `len(val_returns)` (100 validation bars on the
  shipped sample), not a period count. If it is renamed to `val_n_observations`, capture a pre-rename
  baseline fixture the same way `tests/fixtures/test_performance_pre_rename_baseline.json` was captured
  (same data / grid / split, provenance in the fixture) and extend
  `tests/test_test_window_observations.py` rather than writing a new harness.
- The framework's own `summary["test_resolution"]` block reports `n_test_observations`, the trial and
  benchmark counts, the minimum detectable effects and the plausibility bounds -- but not the realized
  volatility the minimum detectable effect is conditional on. Measured here on the held-out test
  window's own returns (the series the resolution is computed on): the control's window is more
  volatile than the null's -- 12.08% against 10.98% annualized at 5,000 bars, 11.99% against 11.31% at
  10,000 bars -- so the two fixtures' alpha MDEs differ at the same T, and a reader comparing two runs
  at the same T could misread that difference as a sample-size difference. Whether to expose the
  conditioning in the block is a reporting question to settle with evidence, not a threshold change.
  Note the blast radius: the block is written into the committed example artifacts
  (`examples/example_output/*.json`), so a new key means regenerating them.
- The resolution ladder has never been measured on a **real** history: the longest one in the repository
  is `assets/example_data/sample_panel_ohlcv.csv` (1,500 bars), far below the 2,500-10,000 bar range
  where the crossing happens, so `--data FILE` has never been exercised on a history long enough to say
  anything about the crossing. That needs a longer history than the repository carries.
- The sweep is now defined only for the out-of-sample path (the path that prices criterion 2 on the
  held-out window). The other two paths are configured in months, not in fractions, so they have no
  held-out fraction to sweep -- worth stating explicitly in `references/validation_methods.md` if a
  reader asks why the sweep is one-path-only.
