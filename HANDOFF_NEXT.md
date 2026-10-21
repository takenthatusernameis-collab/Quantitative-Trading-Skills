# Next task — 2026-10-21 (session)

## Task

**Re-capture the resolution ladder so a summary built from it says what sets the
alpha floor.**

The per-path block of `scripts/measure_resolution_vs_sample_size.py` gained
`strategy_alpha` / `benchmark_alphas` / `benchmark_alpha_std` *after* the ladder
was captured, so neither `results/resolution_floor/ladder_2500_to_50000.json` nor
the trimmed `tests/fixtures/resolution_ladder_2500_to_50000.json` carries them.
A summary built from those rows reports "what sets the alpha floor: not
measurable on this ladder -- the benchmark alphas ... were not reported by the
framework", which is honest but thin: the ladder's whole point is to show the
crossing, and the crossing is now reported without the driver that sets the
floor at every rung.

## Evidence

- `results/resolution_floor/ladder_2500_to_50000.json` and
  `tests/fixtures/resolution_ladder_2500_to_50000.json` are the committed
  records. Inspect a row: the per-path block has `alpha_floor_driver: "not
  measurable on this ladder -- the benchmark alphas ... were not reported by the
  framework"`, because the keys the driver reads were added to the block after
  the capture.
- The driver itself is verified and pinned: `alpha* = std(benchmark alphas,
  ddof=1) * sqrt(2 ln N)`, checked against the framework's own
  `expected_max_alpha`, with three outcomes (holds / fails / cannot be checked).
  `tests/test_resolution_vs_sample_size.py` pins it (27/27, ~11.5 min), and the
  reference doc `references/validation_methods.md` states the identity and its
  two consequences. So the *mechanism* is not in question -- only the ladder
  record predates it.
- The 50,000-bar rung alone took ~17 min for two draws on this machine, so the
  full ladder is not worth re-running.

## Bounded work

1. Re-capture a **cheap** ladder that carries the driver: 2,500 / 5,000 / 10,000
   bars at one seed, both series (effect and no-effect), with the same provenance
   as the existing fixture (data source, seed, series labels, the rung list).
2. Write it to `results/resolution_floor/ladder_2500_to_10000.json` and trim a
   copy to `tests/fixtures/resolution_ladder_2500_to_10000.json` (the existing
   fixture's provenance block records the recipe; mirror it).
3. Verify that a summary built from the new ladder reports the driver at every
   measured rung -- i.e. `alpha_floor_driver` is no longer "not measurable" --
   and that the driver numbers reproduce the framework's own `expected_max_alpha`
   on the rungs where the identity holds.
4. Add a pin to `tests/test_resolution_vs_sample_size.py` that loads the new
   fixture and asserts the driver is measurable on it (the same shape as the
   existing pins against the 50,000-bar measurement).

Constraint: additive reporting only. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`,
`PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.00`, the 0.6/0.2/0.2 split, the estimators
and every verdict stay exactly as they are. The estimator
(`scripts/walk_forward.py`) is not in this task's diff.

## Subsequent options (after this task)

- The resolution ladder has never been measured on a **real** history: the
  longest one in the repository is `assets/example_data/sample_panel_ohlcv.csv`
  (1,500 bars), far below the 2,500-50,000 bar range where the crossings happen,
  so `--data FILE` has never been exercised on a history long enough to say
  anything about the crossing. That needs a longer history than the repository
  carries.
- The held-out-fraction sweep is defined only for the out-of-sample path (the
  path that prices criterion 2 on the held-out window). The other two paths are
  configured in months, not in fractions, so they have no held-out fraction to
  sweep -- worth stating explicitly in `references/validation_methods.md` if a
  reader asks why the sweep is one-path-only.

(End of file - total 94 lines)