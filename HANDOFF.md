# Handoff — 2026-10-21 (session)

## What changed

Completed the assigned task in `HANDOFF_NEXT.md`: **what sets the alpha floor is
now reported**, not just measured. The Deflated Alpha floor (alpha*) was quoted
as a bare number by the resolution report; the number is not what a reader
would guess, so the report now carries the driver that sets it and checks the
identity against the framework's own block.

No threshold, bound, criterion or verdict moved. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA
== 0.10`, `PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.00` and the shipped 0.6/0.2/0.2
split are untouched, and **the estimator itself was not touched**:
`scripts/walk_forward.py` is not in this session's diff at all.

### 1. The report carries the driver (`scripts/measure_resolution_vs_sample_size.py`)

- **New `_alpha_floor_driver(block)`** (measure_resolution_vs_sample_size.py:424):
  reconstructs alpha* from the block's own benchmark alphas --
  `alpha* = std(benchmark alphas, ddof=1) * sqrt(2 ln N)` -- and checks it
  against the framework's own `expected_max_alpha`. The check has three
  outcomes and all three are reported: it holds (the framework used the
  cross-sectional estimator), it fails (the framework used its i.i.d.-normal
  null fallback, so the floor is set by the sample size instead), or it cannot
  be checked (the benchmark alphas were not reported).
- **`_measure_path`** now filters the benchmark alphas exactly as the
  framework's own trial set does (finite alphas only), so the report's
  benchmark alphas *are* the alphas the floor was estimated from.
- **`_summarize_path`** now carries `alpha_floor_driver` per path: the
  identity, the benchmark count, the driver of the **worst draw at the largest
  measured rung** (the draw that sets the floor the summary quotes), the
  dispersion and strategy-alpha ranges over the ladder, and the check flag with
  the counts of draws measured and draws checked. Each rung of
  `per_size_alpha` also carries `min/max_benchmark_alpha_std` -- the dispersion
  the floor at that rung was estimated from.
- **`print_path_summary`** now prints what sets the floor (new
  `_print_alpha_floor_driver`), with the numbers that reproduce it:

  ```
  what sets the alpha floor (alpha*): std(benchmark alphas, ddof=1) * sqrt(2 ln N) with N = 2
    strategy alpha: -0.0325; benchmark alphas: -0.0325, -0.0392
    benchmark alpha dispersion (ddof=1): 0.0047; alpha* from that dispersion: 0.0055; the framework's own alpha*: 0.0055
    the framework's floor is reproduced from the benchmark alphas, so a higher alpha floor means a bigger gap between the strategy and its benchmark set -- not a bigger search, and not a worse test
  ```

- The module docstring gained a "WHAT SETS THE ALPHA FLOOR" section.

### 2. The reference doc (`references/validation_methods.md`)

The previous session's edit of this file was **broken**: it had replaced the
heading `#### What this does not establish` with the new section and left a
stray `"` at the end of it, so the caveat bullet list was orphaned under the
wrong heading. Repaired: the heading is restored, the stray quote is gone, and
the new section `#### What sets the alpha floor (alpha*)` now sits directly
after the alpha-floor table's discussion and before the caveats (it reads as
the explanation of the table that precedes it).

The section states the identity, the measured numbers, the two consequences (the
floor tracks the strategy's own edge over its benchmark set, not the size of
the search; and it does not fall to zero as the sample grows), and which report
keys carry the driver.

### 3. Tests (`tests/test_resolution_vs_sample_size.py`)

- `test_deflated_alpha_floor_identity_matches_benchmark_dispersion` was
  strengthened: the formula is now re-derived with the **standard library**
  (`statistics.stdev`, `math.sqrt(2 * math.log(n))`) instead of the
  implementation's own estimator, so the test is an independent check of the
  documented formula; and it now pins that the report's driver numbers *are*
  the framework's own (the block's `benchmark_alphas` equal the framework's
  `benchmark_metrics` alphas, `benchmark_alpha_std` equals the sample standard
  deviation, and the strategy's own alpha is the primary benchmark's alpha).
- New `test_the_summary_reports_what_sets_the_alpha_floor`: the summary carries
  the driver, the identity holds on every measured draw, the driver reported is
  the driver of the floor the summary quotes, and the printed report says what
  sets the floor and what a higher floor does and does not mean.
- The module docstring lists the new pin.

### 4. `SKILL.md`

The script's entry and the "criteria are not unsatisfiable" bullet now state
the identity and what a high alpha floor means ("a bigger gap, not a worse
test").

## What was actually verified

- **The documented numbers were re-measured from scratch** (50,000-bar
  walk-forward rung, seed 7, synthetic positive-control fixture, both series;
  ~17 min on this machine). All four numbers quoted in the reference doc are
  confirmed exactly, and the identity holds to the last floating-point bit
  (`alpha_star_from_dispersion == expected_max_alpha`):

  | Series | strategy alpha | benchmark alpha | gap | alpha* (framework) | alpha* (from the dispersion) |
  | --- | --- | --- | --- | --- | --- |
  | effect | 0.047046 | 0.135285 | 8.82pp | 0.073464 | 0.073464 |
  | no-effect | -0.027123 | -0.014862 | 1.23pp | 0.010208 | 0.010208 |

  (The doc rounds these to 4.70% / 13.53% / 7.35% and -2.71% / -1.49% /
  1.02%; both match.) The script that produced them is
  `/home/runner/work/_temp/kilo-tmp/kilo/verify_alpha_floor_50k.py`; its output
  is at `/home/runner/work/_temp/kilo-tmp/kilo/alpha_floor_50k.json`.
- **Negative controls**: three mutations applied one at a time, the pinned test
  required to fail, the file restored -- 3/3 bit.
  1. the summary drops `alpha_floor_driver` ->
     `..._the_summary_reports_what_sets_the_alpha_floor` fails (KeyError);
  2. the reported dispersion is computed with `ddof=0` instead of `ddof=1` ->
     `..._deflated_alpha_floor_identity_matches_benchmark_dispersion` fails
     (0.00332 against 0.00470);
  3. the driver is not printed ->
     `..._the_summary_reports_what_sets_the_alpha_floor` fails.
- `tests/test_resolution_vs_sample_size.py`: **29/29** (was 28; one new), 11.5 min.
  `pytest --collect-only` collects the same 29.
- **Neighbouring suites, re-run after the change**:
  `test_test_resolution.py` + `test_out_of_sample_window.py` +
  `test_test_window_observations.py` = **55 passed**;
  `test_examples_coverage.py` **7 passed**;
  `test_falsifiable_hypothesis_example.py` **14 passed**.
- `python3 -m py_compile` clean on both changed Python files.
- `skills-ref validate skills/quantitative-backtesting/` -> "Valid skill" (the
  CI validator used by `.github/workflows/validate-skills.yml`; installed from
  `git+https://github.com/agentskills/agentskills.git#subdirectory=skills-ref`).

## What remains unresolved

- **The committed ladder record predates the driver.** The per-path block
  gained `strategy_alpha` / `benchmark_alphas` / `benchmark_alpha_std` after
  the ladder was captured, so neither `results/resolution_floor/ladder_2500_to_50000.json`
  nor the trimmed `tests/fixtures/resolution_ladder_2500_to_50000.json` carries
  them; a summary built from those rows says "what sets the alpha floor: not
  measurable on this ladder -- the benchmark alphas ... were not reported by
  the framework", which is honest but thin. Re-capturing the full ladder is
  expensive (the 50,000-bar rung alone took ~17 min for two draws here); a
  cheap capture that carries the driver would be 2,500 / 5,000 / 10,000 bars
  at one seed, both series.
- The resolution ladder is still measured only on the **synthetic** fixture.
  The longest real history in the repo is `assets/example_data/sample_panel_ohlcv.csv`
  (1,500 bars) and `sample_ohlcv.csv` (504 bars), far below the range where
  the crossing happens, so the `--data` path of the script has still never been
  exercised on a history long enough to say anything about the crossing.
  Measuring it needs a longer history than the repository carries.
- The framework's `summary["test_resolution"]` block still does not report the
  realized volatility its minimum detectable effect is conditional on, so a
  reader comparing two runs at the same T can misread a volatility difference
  as a sample-size difference. **This is the next task.**
- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`)
  still carries the mislabel the completed rename removed from `test_performance`:
  it is `len(val_returns)` (100 validation bars on the shipped sample), not a
  period count. The recipe (capture a pre-rename baseline the way
  `tests/fixtures/test_performance_pre_rename_baseline.json` was captured, then
  extend `tests/test_test_window_observations.py`) is in `HANDOFF_NEXT.md`.
- The held-out-fraction sweep is defined only for the out-of-sample path (the
  path that prices criterion 2 on the held-out window). The other two paths are
  configured in months, not in fractions, so they have no held-out fraction to
  sweep -- worth stating explicitly in `references/validation_methods.md` if a
  reader asks why the sweep is one-path-only.

## Approaches that failed

- None in this session. The measurement ran to completion on the first attempt
  and the three negative controls all behaved as required. The one thing that
  needed repair was the *previous* session's edit of
  `references/validation_methods.md` (a clobbered heading and a stray quote),
  which is described above.

## Next task (one, precise)

**Report the volatility the minimum detectable effect is conditional on, so two
runs at the same sample size can be compared.**

Evidence: `summary["test_resolution"]` (built by `_build_test_resolution`,
`scripts/walk_forward.py:2272`) reports the trial and benchmark counts, the
minimum detectable effects and the plausibility bounds -- but not the realized
volatility those minimum detectable effects are conditional on. The alpha side
is volatility-scaled: the Deflated Alpha floor is
`alpha* = sr_star * strat_vol_ann * sqrt(ann_factor)`
(`scripts/walk_forward.py:1968`), i.e. proportional to the strategy's realized
annualized volatility on the test window, and `minimum_detectable_alpha`
(`scripts/walk_forward.py:2156`) inverts the DAR on that same scale. So two
runs at the same T have different alpha MDEs purely because their test windows
are more or less volatile, and a reader comparing the two would misread that as
a sample-size effect. Measured on the control fixture (seed 7, 5,000 bars): the
control's test window is 12.08% annualized against the null's 10.98%, and the
two fixtures' alpha MDEs differ at the same T.

Bounded work:

1. `scripts/walk_forward.py`: add the conditioning to the `test_resolution`
   block -- the realized annualized volatility of the very return series the
   statistic was computed on (`returns`), which is the series the block is
   already given -- and report it in the printed resolution
   (`_print_test_resolution`). Additive only: no existing key changes value and
   no threshold, bound, criterion or verdict moves.
2. **Measure first whether the conditioning applies to the Sharpe side too.**
   The Sharpe MDE is a Sharpe ratio and looks scale-free, but its floor
   `SR* = std(trial Sharpes) * sqrt(2 ln N)` is estimated from trial alphas
   divided by the strategy's volatility, so the claim "the volatility
   conditioning is an alpha-side issue only" is a hypothesis, not a fact. If a
   measurement contradicts it, report that rather than the expectation.
3. `references/validation_methods.md`: state the conditioning next to the
   resolution block, with the measured numbers, so two runs can be compared
   correctly.
4. `tests/test_test_resolution.py`: pin the new key against the series the
   block is built on, and pin that the existing keys do not move.

Constraint: the change is additive reporting. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`,
`PLAUSIBLE_MAX_ANNUALIZED_SHARPE`, the 0.6/0.2/0.2 split, the estimators and
every verdict stay exactly as they are.

Subsequent option (smaller, mechanical): the `val_n_periods` mislabel, with
the recipe above.
