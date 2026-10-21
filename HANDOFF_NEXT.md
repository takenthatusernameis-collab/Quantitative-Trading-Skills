# Next task — 2026-10-21 (session)

## Task

**Capture the resolution curve on the longest real history in the repository,
and state honestly what it does and does not show.**

The resolution ladder -- "at the shipped configuration, how large must the
sample be before the pre-registered significance criteria can confirm an
effect of a plausible size?" -- has only ever been captured on the synthetic
positive-control fixture. The `--data` path that measures the same curve on
a real history works, but no real-history measurement is committed, so the
repository's only evidence for the crossing is a formula.

## Evidence

- The `--data` path of `scripts/measure_resolution_vs_sample_size.py` works
  on the longest real history the repository carries,
  `skills/quantitative-backtesting/assets/example_data/sample_panel_ohlcv.csv`
  (1,500 bars, a `symbol` column, with `sample_benchmark.csv` beside it for
  the two-benchmark Deflated Alpha path). Measured this session:

  ```
  python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
      --data skills/quantitative-backtesting/assets/example_data/sample_panel_ohlcv.csv \
      --sizes 1500 --paths out_of_sample
  ```

  The out-of-sample path at 1,500 bars: minimum confirmable annualized
  Sharpe **2.5806** (still beyond the 2.0 plausibility bound), SR\* 1.4980,
  minimum confirmable annualized alpha 2.3963, alpha\* 0.0109 (driver
  reported, identity reproduced). So the mechanism is visible on real data
  and the crossing is **not** reached: the repository's data cannot settle
  "is there a sample size at which criterion 2 can confirm a plausible
  effect?" on a real history.
- The committed captures are synthetic only:
  `results/resolution_floor/ladder_2500_to_50000.json` and
  `results/resolution_floor/ladder_2500_to_10000.json` (and their
  fixtures). `references/validation_methods.md` says in prose that "the
  crossing points are properties of the synthetic control fixture and of the
  shipped configuration, not promises about a real history" -- but there is
  no measured real-history record to show what the same curve looks like on
  the data the repository has.
- The previous session's task (now done) found the `--data` path's first
  exercise; this is the same path, used for what it is for.

## Bounded work

1. Capture the real-history curve at 500 / 1,000 / 1,500 bars, all three
   paths, with its provenance (command, environment, source file, script
   commit) into `results/resolution_floor/`, and a trimmed fixture into
   `tests/fixtures/`, following the shape the two synthetic captures
   already use (`provenance` + `rows`).
2. Pin it in `tests/test_resolution_vs_sample_size.py`:
   - the capture is the tool's own `--json` output;
   - the summary rebuilt from the fixture agrees with the committed summary
     key by key (as the synthetic capture's pin does);
   - the report says the crossing is **not** reached on this history
     ("no measured sample size brought criterion 2 within the plausibility
     bound on every draw measured at that size") and claims nothing about
     sample sizes the capture did not measure;
   - the alpha-floor driver is reported at every rung (the fixture carries
     the driver keys, so a summary built from it does not say "not
     measurable on this ladder").
3. `references/validation_methods.md`: state the real-history measurement
   next to the synthetic curve, with the numbers, and say plainly that the
   crossing is a property of the fixture and has **not** been reproduced on
   a real history of the length the crossing needs (>= 10,000 bars for
   criterion 2; 25,000-50,000 for criterion 5).

## Constraints

- A measurement beside the verdict, never part of it: no threshold, bound,
  criterion or verdict moves, and `scripts/walk_forward.py` is not in this
  task's diff.
- The 1,500-bar panel is the longest real history in the repository, so the
  honest result is "the crossing is out of reach with the data here" --
  that is the finding, not a failure to find one.

## Subsequent options (after this task)

- **Apply the "was it measured at all?" distinction to criterion 2.** The
  Sharpe floor (SR*) is printed through the same `_print_floor_status`
  (`scripts/measure_resolution_vs_sample_size.py:1403`) but only the alpha
  side is gated on the framework's status. The framework records the same
  record for criterion 2 (`sharpe_status` / `sharpe_reason`, copied by
  `_measure_path`), and the report's own table already prints "n/a" for a
  criterion it could not resolve, so the table and the summary can
  disagree. The reachable reasons are `target_unattainable` (a dispersed
  parameter grid on few observations), `returns_do_not_match_statistic`,
  `no_returns` and `insufficient_returns`.
- The 50,000-bar capture (`results/resolution_floor/ladder_2500_to_50000.json`
  and its fixture) still predates the driver keys, so a summary built from
  it still prints "not measurable on this ladder" for the driver. The cheap
  re-capture (`results/resolution_floor/ladder_2500_to_10000.json` and
  `tests/fixtures/resolution_ladder_2500_to_10000.json`) carries the driver
  and is pinned, so this is a nice-to-have: the 50,000-bar rung alone costs
  ~17 min on this machine.
- The held-out-fraction sweep is defined only for the out-of-sample path
  (the path that prices criterion 2 on the held-out window). The other two
  paths are configured in months, not in fractions, so they have no held-out
  fraction to sweep -- worth stating explicitly in
  `references/validation_methods.md` if a reader asks why the sweep is
  one-path-only.
