# Handoff — 2026-10-21 (session)

## What changed

Completed the assigned task in `HANDOFF_NEXT.md`: **an alpha floor the
framework could not price is now reported as unpriceable, not as 0.0000.**

No threshold, bound, criterion or verdict moved. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA
== 0.10`, `PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.00` and the shipped 0.6/0.2/0.2
split are untouched, and **the estimator itself was not touched**:
`scripts/walk_forward.py` is not in this session's diff at all. The framework's
own `alpha_status` / `alpha_reason` already carried the fact; it was only the
*report* that misread it.

### 1. The rule (`scripts/measure_resolution_vs_sample_size.py`)

A new helper, `_alpha_floor_measured(block)`, reads the framework's own
`alpha_status`: a block whose Deflated Alpha criterion could not be priced
carries a **placeholder** floor, not a measured floor of zero. On a
zero-volatility draw the strategy's alpha, every benchmark alpha and the
dispersion between them are all exactly zero, so the block's
`expected_max_alpha` is `0.0` because nothing could be estimated.

A block that carries no status at all (an older capture) is treated as
measured, so every committed capture keeps reporting the floor it reported.

### 2. The report no longer reads a placeholder as a measurement

- `_alpha_floor_driver` (`:451`) carries the framework's own `alpha_status` /
  `alpha_reason` and a new `floor_measured` flag, and claims neither the
  reconstruction (`alpha_star_from_dispersion`) nor the identity
  (`identity_holds`) for a draw whose alphas are placeholders.
- `_summarize_path` (`:900`) keeps the unpriceable draws apart from the
  measured ones. The floor the summary quotes is now the floor at the
  largest rung **whose floor was measured**; `alpha_floor_at_largest_size`
  is `None` (never `0.0`) when no rung's floor could be measured, and
  `alpha_floor_beyond_plausible_bound` /
  `alpha_floor_beyond_plausible_bound_at_largest_size` are `None` (unknown),
  not `False` ("measured, and not above the bound").
- New keys (all additive): `alpha_floor_measured`,
  `alpha_floor_at_largest_measured_size`, `alpha_floor_unmeasured_rungs`,
  `alpha_floor_unmeasured_reason`; per rung
  `per_size_alpha[*].draws_floor_unmeasured` and `floor_unmeasured_reason`;
  in the driver, `floor_measured`, `draws_unmeasured`, `unmeasured_rungs`,
  `unmeasured_reason`.
- `_print_floor_status` (`:1403`) and `_print_alpha_floor_driver` (`:1500`)
  report the fourth case -- the floor was never measured -- with the
  framework's own reason, and no longer say "the floor does not block
  criterion 5" or "the framework's floor is reproduced from the benchmark
  alphas" for a draw whose criterion was never evaluated.

### 3. The pins (`tests/test_resolution_vs_sample_size.py`)

Four new tests:

- `test_an_unpriceable_alpha_floor_is_reported_as_unpriceable` -- the live
  reproducer: the shipped 504-bar history measured with `--data`, whose
  CPCV path cannot price the Deflated Alpha criterion (the framework's own
  reason is `zero_volatility`). The summary reports the floor as not
  measured, and the printed report does not say the floor does not block
  criterion 5 and does not claim the identity was reproduced.
- `test_a_measured_alpha_floor_is_still_reported_with_its_driver` -- the
  control: the same history's out-of-sample path prices the criterion
  normally, and its floor, driver, identity check and conclusion are all
  still reported.
- `test_a_placeholder_floor_is_not_read_as_a_measurement` -- the rule
  itself on a block built to exercise it: the gate is the framework's own
  status, not the size of the number (a priced criterion with a zero floor
  is still a measurement).
- `test_every_test_in_this_file_is_registered` -- a pin that is not
  registered is not a pin (see below).

**Two tests that existed but never ran are now registered.** The runner
walks `TEST_REGISTRY`, and `test_the_summary_reports_what_sets_the_alpha_floor`
and `test_deflated_alpha_floor_identity_matches_benchmark_dispersion` were
defined in the file but missing from that list, so the suite reported itself
as passing while two of its checks were dormant. Both pass when run (checked
directly before registering them). The new registry pin compares the file's
`def test_` definitions with the registry, so the gap cannot recur.

The suite now runs **34** tests; it ran **28** before this session, and the
previous handoff's "30/30" was a miscount (two of those were the dormant
ones).

### 4. The docs

- `references/validation_methods.md`: a new section, "A floor that was never
  measured is not a floor of zero", next to the alpha-floor discussion: the
  table of what each key reports in the measured and unmeasured case, the
  504-bar reproducer, and the rule.
- `SKILL.md`: one sentence next to the alpha-floor driver -- a floor the
  framework could not *price* is reported as unpriceable rather than as a
  floor of zero.

## What was actually verified

- **The defect was reproduced first**, from the tool itself:

  ```
  python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
      --data skills/quantitative-backtesting/assets/example_data/sample_ohlcv.csv \
      --sizes 504 --paths out_of_sample,walk_forward,cpcv
  ```

  Before the change, the CPCV path printed "the alpha (alpha\*) floor is at
  or under the plausibility bound at the largest measured sample size (504
  bars): the floor does not block criterion 5 at that size" and "the
  framework's floor is reproduced from the benchmark alphas" -- on a draw
  whose criterion 5 was never evaluated and whose benchmark alphas are
  placeholders. After the change, the same command prints "the alpha (alpha\*)
  floor was not measured on this path: the framework could not price the
  alpha criterion (zero_volatility), so the floor it carries is a placeholder
  rather than a measurement, and nothing here settles criterion 5". The
  out-of-sample and walk-forward paths on the same history are unchanged
  (floors 0.0159 and 0.0650, drivers reported).
- **Nothing moved where the floor was measured.** The summary rebuilt from
  both committed captures (`results/resolution_floor/ladder_2500_to_50000.json`
  and `ladder_2500_to_10000.json`) was compared key by key with the summary
  committed in the capture itself: **no pre-existing key changed value** on
  any path, at any rung -- only the new keys were added.
- **Negative controls** (each applied alone, then reverted):
  1. the `_alpha_floor_measured` gate forced open -> the two unpriceable-floor
     pins fail, the measured-floor control still passes;
  2. one registry entry removed -> `test_every_test_in_this_file_is_registered`
     fails and names the missing test. 2/2.
- `tests/test_resolution_vs_sample_size.py`: **34/34** (was 28 registered;
  4 new, 2 previously dormant now registered).
- **Neighbouring suites, re-run after the change**:
  `test_test_resolution.py` (39) + `test_out_of_sample_window.py` (11) +
  `test_test_window_observations.py` (7) + `test_examples_coverage.py` (7) +
  `test_falsifiable_hypothesis_example.py` (14) = **78 passed**.
- `skills-ref validate skills/quantitative-backtesting/` -> "Valid skill"
  (the CI validator used by `.github/workflows/validate-skills.yml`).

## What remains unresolved

- **The same distinction has not been applied to criterion 2.** The Sharpe
  floor (SR\*) is reported through the same `_print_floor_status`, but only
  the alpha side is gated on the framework's status. The framework records
  the same record for criterion 2 (`sharpe_status` / `sharpe_reason`, copied
  by `_measure_path`), and the report's own table already prints "n/a" for a
  criterion it could not resolve, so the table and the summary can disagree.
  The reachable reasons are `target_unattainable` (a dispersed parameter
  grid on few observations), `returns_do_not_match_statistic`, `no_returns`
  and `insufficient_returns`. This is the next task.
- **The resolution ladder has still never been measured on a real history
  long enough to say anything about the crossing.** The `--data` path works
  (it was exercised for the first time in the previous session, and again
  this session on the 1,500-bar panel sample), but the longest real history
  in the repository is `assets/example_data/sample_panel_ohlcv.csv` (1,500
  bars) and `sample_ohlcv.csv` (504 bars), far below the 2,500-50,000-bar
  range where the crossings happen. At 1,500 bars the out-of-sample path's
  minimum confirmable Sharpe is 2.5806 -- still beyond the 2.0 bound. The
  crossings remain properties of the synthetic control fixture.
- The 50,000-bar capture still predates the driver keys, so a summary built
  from *it* still says "not measurable on this ladder" for the driver.
  Re-capturing it would cost ~17 min for the 50,000-bar rung alone on this
  machine; the cheap capture covers the driver's contract, so this is a
  nice-to-have, not a blocker.
- The held-out-fraction sweep is defined only for the out-of-sample path
  (the path that prices criterion 2 on the held-out window). The other two
  paths are configured in months, not in fractions, so they have no held-out
  fraction to sweep -- worth stating explicitly in
  `references/validation_methods.md` if a reader asks why the sweep is
  one-path-only.

## Approaches that failed

- None. The reproducer ran on the first attempt, the two negative controls
  both behaved as required, and every suite passed on the first run.

## Next task (one, precise)

**Capture the resolution curve on the longest real history in the repository,
and state honestly what it does and does not show.**

Evidence:

- The `--data` path of `scripts/measure_resolution_vs_sample_size.py` works
  on the longest real history the repository carries,
  `skills/quantitative-backtesting/assets/example_data/sample_panel_ohlcv.csv`
  (1,500 bars, `symbol` column, `sample_benchmark.csv` beside it):

  ```
  python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
      --data skills/quantitative-backtesting/assets/example_data/sample_panel_ohlcv.csv \
      --sizes 1500 --paths out_of_sample
  ```

  Measured this session: the out-of-sample path's minimum confirmable
  Sharpe at 1,500 bars is **2.5806** -- still beyond the 2.0 plausibility
  bound -- with SR\* 1.4980 and a minimum confirmable alpha of 2.3963. So
  the mechanism is visible on real data, and the crossing is not reached:
  the repository's data cannot settle "is there a sample size at which
  criterion 2 can confirm a plausible effect?" on a real history.
- The ladder has only ever been captured on the synthetic control fixture
  (`results/resolution_floor/ladder_2500_to_50000.json` and
  `ladder_2500_to_10000.json`). There is no committed real-data record, and
  the docs' "What this does not establish" says so in prose only.

Bounded work:

1. Capture the real-history curve at 500 / 1,000 / 1,500 bars (all three
   paths, `--data`), with its provenance -- command, environment, source
   file, script commit -- into `results/resolution_floor/`, and a trimmed
   fixture into `tests/fixtures/`, following the shape the two synthetic
   captures already use.
2. Pin it in `tests/test_resolution_vs_sample_size.py`: the capture is the
   tool's own `--json` output; the summary rebuilt from it agrees with the
   committed summary key by key; and the report says the crossing is not
   reached -- "no measured sample size brought criterion 2 within the
   plausibility bound on every draw measured at that size" -- without
   claiming anything about sample sizes the capture did not measure.
3. `references/validation_methods.md`: state the real-history measurement
   next to the synthetic curve, with the numbers, and say plainly that the
   crossing is a property of the fixture and has **not** been reproduced on
   a real history of the length the crossing needs (>= 10,000 bars for
   criterion 2, >= 25,000-50,000 for criterion 5).

Constraint: a measurement beside the verdict, never part of it. No threshold,
bound, criterion or verdict moves, and `scripts/walk_forward.py` is not in
that task's diff.
