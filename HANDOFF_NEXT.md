# Next task — 2026-10-21 (session)

## Task

**Report the volatility the minimum detectable effect is conditional on, so two
runs at the same sample size can be compared.**

The framework reports the smallest effect each significance criterion could
have confirmed (`summary["test_resolution"]`). It does not report the realized
volatility that minimum detectable effect is conditional on, so two runs at the
same T look comparable when they are not.

## Evidence

The alpha MDE is a volatility-scaled quantity:

- the Deflated Alpha floor is `alpha* = sr_star * strat_vol_ann * sqrt(ann_factor)`
  (`scripts/walk_forward.py:1968`) -- proportional to the strategy's realized
  annualized volatility on the test window;
- `minimum_detectable_alpha` (`scripts/walk_forward.py:2156`) inverts the DAR
  on that same scale, so the MDE it reports moves with the volatility of the
  series the statistic was computed on.

Measured on the control fixture (seed 7, 5,000 bars): the control's test window
is **12.08%** annualized against the null's **10.98%**, and the two fixtures'
alpha MDEs differ at the same T. A reader comparing two runs at the same T can
therefore misread a volatility difference as a sample-size difference.

The block that carries the resolution is `_build_test_resolution`
(`scripts/walk_forward.py:2272`); it already receives the very return series
the statistic was computed on (`returns`), so the conditioning is available
without recomputing anything.

## Bounded work

1. `scripts/walk_forward.py`: add the conditioning to the `test_resolution`
   block -- the realized annualized volatility of that same return series -- and
   report it in the printed resolution (`_print_test_resolution`). Additive
   only: no existing key changes value, and no threshold, bound, criterion or
   verdict moves.
2. **Measure before assuming whether the Sharpe side is affected too.** The
   Sharpe MDE is a ratio and looks scale-free, but its floor
   `SR* = std(trial Sharpes) * sqrt(2 ln N)` is estimated from trial alphas
   divided by the strategy's volatility, so "the volatility conditioning is an
   alpha-side issue only" is a hypothesis, not a fact. If a measurement
   contradicts it, report the measurement.
3. `references/validation_methods.md`: state the conditioning next to the
   resolution block, with the measured numbers, so two runs at the same T are
   compared correctly.
4. `tests/test_test_resolution.py`: pin the new key against the series the
   block is built on, and pin that the existing keys do not move.

## Constraints

- Additive reporting only. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`,
  `PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.00`, the shipped 0.6/0.2/0.2 split, the
  estimators and every verdict stay exactly as they are.
- The framework's own numbers are the source of truth: the new key must be the
  volatility of the series the statistic was computed on, not a recomputation
  from a different series.
- `PLAUSIBLE_*` and the estimators live in `scripts/walk_forward.py`; the
  resolution block is attached by all three analysis paths and by
  `scripts/run_backtest.py`, so the change shows up in four CLIs.

## Subsequent options (after this task)

- **The committed ladder record predates the driver.** The per-path block of
  `scripts/measure_resolution_vs_sample_size.py` gained `strategy_alpha` /
  `benchmark_alphas` / `benchmark_alpha_std` after the ladder was captured, so
  neither `results/resolution_floor/ladder_2500_to_50000.json` nor the trimmed
  `tests/fixtures/resolution_ladder_2500_to_50000.json` carries them and a
  summary built from those rows reports "not measurable on this ladder". A
  cheap capture that does carry the driver: 2,500 / 5,000 / 10,000 bars, one
  seed, both series, with provenance as in the existing fixture. The full
  ladder is not worth re-running (the 50,000-bar rung alone took ~17 min for
  two draws).
- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`)
  carries the same mislabel the completed rename removed from `test_performance`:
  it is `len(val_returns)` (100 validation bars on the shipped sample), not a
  period count. Capture a pre-rename baseline fixture the same way
  `tests/fixtures/test_performance_pre_rename_baseline.json` was captured (same
  data / grid / split, provenance in the fixture) and extend
  `tests/test_test_window_observations.py` rather than writing a new harness.
- The resolution ladder has never been measured on a **real** history: the
  longest one in the repository is `assets/example_data/sample_panel_ohlcv.csv`
  (1,500 bars), far below the 2,500-50,000 bar range where the crossings
  happen, so `--data FILE` has never been exercised on a history long enough to
  say anything about the crossing. That needs a longer history than the
  repository carries.
- The held-out-fraction sweep is defined only for the out-of-sample path (the
  path that prices criterion 2 on the held-out window). The other two paths are
  configured in months, not in fractions, so they have no held-out fraction to
  sweep -- worth stating explicitly in `references/validation_methods.md` if a
  reader asks why the sweep is one-path-only.
