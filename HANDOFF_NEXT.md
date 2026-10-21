# Next task — 2026-10-21 (session)

## Task

**Report an unpriceable alpha floor as unpriceable, not as 0.0000.**

The alpha floor (alpha*) is quoted by the resolution report and by the
summary. When the framework cannot price the alpha test on a path, it
carries placeholder zeros in the per-path block, and the report quotes them
as a measured floor — including telling the reader that "the floor does not
block criterion 5" on a path where criterion 5 was never evaluated.

## Evidence

- The `--data` path of `scripts/measure_resolution_vs_sample_size.py` was
  exercised for the first time in this repository's history, on the
  repository's own 504-bar sample:

  ```
  python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
      --data skills/quantitative-backtesting/assets/example_data/sample_ohlcv.csv \
      --sizes 504 --paths out_of_sample,walk_forward,cpcv
  ```

  The CPCV path cannot price the alpha test on 504 bars, and the framework
  says so in its own block:

  ```
  min_detectable_alpha: None
  observed_annualized_alpha: 0.0
  expected_max_alpha: 0.0
  strategy_alpha: 0.0
  benchmark_alphas: [0.0, 0.0]
  alpha_status: not_resolvable
  alpha_reason: zero_volatility
  ```

  but the report then prints:

  ```
  the alpha (alpha*) floor is at or under the plausibility bound at the
  largest measured sample size (504 bars): the floor does not block
  criterion 5 at that size
  what sets the alpha floor (alpha*): std(benchmark alphas, ddof=1) * sqrt(2 ln N) with N = 2
    strategy alpha: 0.0000; benchmark alphas: 0.0000, 0.0000
    benchmark alpha dispersion (ddof=1): 0.0000; alpha* from that dispersion: 0.0000; the framework's own alpha*: 0.0000
    the framework's floor is reproduced from the benchmark alphas, so a higher alpha floor means a bigger gap ...
  ```

  Both statements are wrong for that path: the floor is 0 because the test
  could not be priced, not because the benchmark dispersion is zero, and
  "the floor does not block criterion 5" is not established when criterion 5
  was not resolvable. The driver reports the identity as *reproduced* on a
  degenerate zero-dispersion draw, and the summary's
  `alpha_floor_beyond_plausible_bound` is `False` with
  `alpha_floor_at_largest_size == 0.0` — the summary says the alpha floor
  never blocks criterion 5 on a path where it blocked nothing because it
  was never measured.

- The mechanism is in the report, not in the framework: the framework's own
  `alpha_status` / `alpha_reason` are already in the per-path block
  (`_measure_path` copies them), and the *reporting* layer
  (`_alpha_floor_driver`, `_print_floor_status`, `_summarize_path`) is what
  reads the placeholders as measurements. `scripts/walk_forward.py` is not
  in this task's diff.

- Every block in the two committed synthetic captures is `resolvable`
  (checked: `results/resolution_floor/ladder_2500_to_50000.json`,
  `results/resolution_floor/ladder_2500_to_10000.json`), which is why the
  synthetic ladder never showed this.

## Bounded work

1. `scripts/measure_resolution_vs_sample_size.py`: make the alpha side
   distinguish "the framework could not price this criterion" from "the
   floor is zero".
   - `_alpha_floor_driver` and `_print_alpha_floor_driver` should report an
     unpriceable floor as unpriceable (with the framework's own reason),
     not quote a zero dispersion and call the identity reproduced;
   - `_print_floor_status` should not say "the floor does not block
     criterion N" for a floor that was never measured;
   - `_summarize_path` should not read a placeholder zero as a measurement
     in `alpha_floor_at_largest_size` / `alpha_floor_beyond_plausible_bound`
     / `alpha_floor_beyond_plausible_bound_at_largest_size`.
   Additive only: where the floor *was* measured, no existing key changes
   value, and no threshold, bound, criterion or verdict moves.
2. `tests/test_resolution_vs_sample_size.py`: pin the distinction — a
   measured floor still reports the driver and the identity (the existing
   pins must keep passing), and an unpriceable one says so instead of
   quoting zeros. The 504-bar `--data` measurement above is a cheap
   reproducer (a few seconds), or the block can be constructed directly.
3. `references/validation_methods.md`: state the distinction next to the
   alpha-floor discussion, so a reader is not told that a criterion that
   could not be evaluated did not block.

## Subsequent options (after this task)

- The 50,000-bar capture (`results/resolution_floor/ladder_2500_to_50000.json`
  and its fixture) still predates the driver keys, so a summary built from
  it still prints "not measurable on this ladder". The cheap re-capture
  (`results/resolution_floor/ladder_2500_to_10000.json` and
  `tests/fixtures/resolution_ladder_2500_to_10000.json`) carries the driver
  and is pinned, so this is a nice-to-have: the 50,000-bar rung alone costs
  ~17 min on this machine.
- The resolution ladder has still never been measured on a history long
  enough to say anything about the crossing: the longest real history in
  the repository is `assets/example_data/sample_panel_ohlcv.csv` (1,500
  bars) and `sample_ohlcv.csv` (504 bars), far below the 2,500-50,000-bar
  range where the crossings happen. The `--data` path works (exercised this
  session), but it needs a longer history than the repository carries.
- The held-out-fraction sweep is defined only for the out-of-sample path
  (the path that prices criterion 2 on the held-out window). The other two
  paths are configured in months, not in fractions, so they have no
  held-out fraction to sweep — worth stating explicitly in
  `references/validation_methods.md` if a reader asks why the sweep is
  one-path-only.
