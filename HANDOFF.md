# Handoff — 2026-10-20 (session)

## What changed

Completed the assigned task in `HANDOFF_NEXT.md`: the held-out-fraction sweep is now measured on the
**effect** series (the positive control) at 5,000 and 10,000 bars, and the control's discrimination is
pinned in the test suite.

**Measurement** (`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`,
`--sizes <n> --test-fracs 0.1,0.2,0.3 --series effect`, seeds 7/1/2024, `val_frac` 0.2,
`train_frac = 0.8 - test_frac`):

| series | bars | held-out | T | min detectable SR | SR* | min detectable alpha | alpha* | observed SR | observed alpha |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| effect | 5,000 | 10% | 498 | 2.08 - 2.44 | 1.20 - 1.55 | 11.8% - 18.4% | 0.6% - 8.1% | 2.51 - 3.72 | 40.4% - 44.9% |
| effect | 5,000 | 20% | 998 | 1.84 - 2.18 | 1.21 - 1.55 | 9.5% - 10.4% | 1.9% - 3.3% | 2.83 - 3.65 | 36.4% - 45.0% |
| effect | 5,000 | 30% | 1,498 | 1.76 - 2.18 | 1.25 - 1.67 | 7.1% - 10.0% | 0.8% - 4.3% | 2.75 - 3.50 | 37.0% - 41.1% |
| effect | 10,000 | 10% | 998 | 1.75 - 1.95 | 1.12 - 1.32 | 7.9% - 14.0% | 0.5% - 6.1% | 2.70 - 3.65 | 38.5% - 44.5% |
| effect | 10,000 | 20% | 1,998 | 1.60 - 1.82 | 1.16 - 1.38 | 6.1% - 9.0% | 0.8% - 3.6% | 3.39 - 3.56 | 40.4% - 42.0% |
| effect | 10,000 | 30% | 2,998 | 1.54 - 1.82 | 1.18 - 1.45 | 5.4% - 7.4% | 1.0% - 3.0% | 3.18 - 3.45 | 39.1% - 41.3% |

The same sweep on the **no-effect** series (the null calibration) was measured for the comparison, and
the two agree on the resolution: at every swept point the two series' minimum confirmable Sharpes are
within **0.40** annualized points and their minimum confirmable alphas within **5.1** percentage points.
What separates them is the **observed** statistic: the control's observed Sharpe is 2.51 - 3.72 (above
the framework's 2.00 plausibility bound) and its observed alpha 36% - 45% (above the 10% bound) on
every draw and every fraction; the null's observed Sharpe never reaches 0.35 and its observed alpha
never reaches 5.1%. **The resolution is a property of the sample; the observed statistic carries the
edge.** That is the discrimination the control is for, now measured rather than asserted.

Held-out-fraction trade-off, measured: at 10,000 bars, moving the held-out fraction from 10% to 30%
cuts the minimum confirmable Sharpe (2.08 - 2.44 -> 1.76 - 2.18 at 5,000 bars) while the floor SR*
rises only slightly (1.20 - 1.55 -> 1.25 - 1.67): the extra test observations outweigh the shorter
training window. The alpha bound is the stricter of the two -- at 10,000 bars the Sharpe bound is
already inside for every draw at a 10% held-out fraction, the alpha bound needs 20%.

**Tests** (`skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`, 16 -> 21):

1. `test_the_effect_series_sweep_matches_the_framework_own_block` -- the effect series' swept numbers
   are the framework's own `test_resolution` / `deflated_sharpe` / `deflated_alpha` blocks, read from a
   **directly re-run** `out_of_sample_validation` on the same fixture at the same split (5,000 and
   10,000 bars x 3 fractions). The observed statistics and the two bound flags are pinned too, and the
   flags are asserted to be exactly the framework's own comparison against the plausibility bounds.
2. `test_the_control_discriminates_the_effect_series_from_the_null` -- at every swept fraction and on
   every seed: the control's observed Sharpe and alpha exceed the plausibility bounds, the null's do
   not, the two observed Sharpes differ by more than 1.0, and the two series' minimum confirmable
   effects are within 0.5 Sharpe / 0.08 alpha of each other. The bounds are asserted to be the
   framework's own (2.0 / 0.10) and unchanged.
3. `test_the_effect_series_sweep_crossings_are_pinned` -- the control's crossings: at 5,000 bars no
   fraction brings every draw inside the Sharpe bound, fraction 0.2 brings some draw inside, and at
   fraction 0.1 every draw is still beyond the alpha bound; at 10,000 bars every draw is inside the
   Sharpe bound at every fraction and the alpha bound is inside for every draw from 0.2 on. The alpha
   crossing at 5,000 bars is a **hair's breadth** (seed 1: 10.41% against the 10% bound at 0.2, 9.99%
   at 0.3) and is deliberately reported rather than pinned.
4. `test_the_sweep_names_the_series_it_measured` -- a sweep table says which series it is.
5. `test_the_sweep_refuses_to_report_a_real_history_it_did_not_measure` -- `--data` + `--test-fracs`
   is refused.

**Three defects found in the measurement CLI while producing the assigned numbers**, all fixed in
`scripts/measure_resolution_vs_sample_size.py`:

- **The sweep measured the wrong series by default and never said so.** `--series both` (the default)
  maps to `inject_effect=None`, which is falsy, so the sweep silently measured the **no-effect** series
  while printing a table that named no series at all. Reproduced: `--sizes 10000 --seeds 7
  --test-fracs 0.2` and `--series no_effect` printed identical numbers (min SR 1.7136). The sweep now
  measures the series it is asked for, prints `--series both` as **both** tables (no_effect and effect),
  labels every table (`-- series: effect`), adds the series to the JSON, and
  `measure_test_frac_sweep` refuses `inject_effect=None` instead of silently meaning "no effect".
- **The sweep computed a full sample-size ladder and threw it away** (`measure_ladder` ran before the
  `--test-fracs` branch and its result was discarded). The ladder is now computed only when it is
  reported: `--sizes 10000 --seeds 7 --test-fracs 0.2 --series effect` went from 23.6 s to 6.5 s.
- **`--data FILE --test-fracs ...` reported the synthetic fixture's numbers under the real history's
  name** (the banner said "Source: <file>", the numbers came from the fixture). The combination is now
  refused with an argparse error; the ladder (`--sizes`) is the way to measure a real history.

Also: with `--json` the banner went to stdout and made the output unparseable. The banner now goes to
stderr, so `--json` emits JSON and nothing else (both the ladder and the sweep).

**Docs**: `references/validation_methods.md` gains "How much of the data should be held out?" (the two
measured tables, the trade-off, the discrimination, the near-tie, and what it does not establish);
`SKILL.md`'s entry for the script mentions the sweep, the series labelling and the `--data` refusal.

No threshold, bound, criterion, verdict or number in the framework moved. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA
== 0.10` and the 2.00 Sharpe bound are untouched, and the shipped 0.6/0.2/0.2 split is unchanged.

## What was actually verified

- `tests/test_resolution_vs_sample_size.py`: **21/21** (`python3 skills/quantitative-backtesting/tests/
  test_resolution_vs_sample_size.py`, 8m07s; `pytest` collects the same 21).
- **Negative controls** (each mutation applied, the pinned test required to fail, the file restored):
  3/3 bit.
  1. the measurement ignores the series it is asked for -> `..._discriminates_the_effect_series_from_the_null`
     fails;
  2. the measurement reports a recomputed resolution instead of the framework's ->
     `..._effect_series_sweep_matches_the_framework_own_block` fails;
  3. the sweep table does not say which series it is -> `..._sweep_names_the_series_it_measured` fails.
- Neighbouring suites, all re-run after the change: `test_falsifiable_hypothesis_example.py` 14/14,
  `test_out_of_sample_window.py` 10/10, `test_examples_coverage.py` 7/7,
  `test_test_window_observations.py` 7/7, `test_walk_forward.py` 183/183, `test_test_resolution.py`
  38/38.
- `python3 -m py_compile` clean on both changed Python files.
- `skills-ref validate skills/quantitative-backtesting/` -> "Valid skill" (the CI validator used by
  `.github/workflows/validate-skills.yml`).
- CLI checked by hand: the labelled two-series sweep, the single-series sweep, the `--data` refusal
  (exit 2), and `--json` parsed with `json.load` for both the ladder and the sweep.

## What remains unresolved

- The resolution ladder is still measured only on the **synthetic** fixture. The longest real history in
  the repo is `assets/example_data/sample_panel_ohlcv.csv` (1,500 bars) and `sample_ohlcv.csv` (504
  bars), both far below the 2,500-10,000 bar range where the crossing happens, so the `--data` path of
  the script has never been exercised on a history long enough to say anything about the crossing.
  Measuring it needs a longer history than the repository carries.
- The **walk-forward path's alpha floor** is above the 10% plausibility bound at every measured rung
  (2,500-10,000 bars, three seeds), so the tool reports "no sample size would let this path confirm a
  plausible alpha". That is a statement about the *measured* range; whether a longer sample would bring
  the floor under the bound is unmeasured. (Measured at seed 7: the walk-forward alpha floor is 0.0026 -
  0.0466 at 5,000 bars and 0.0059 - 0.0656 at 10,000 bars, so the floor is below the bound on that
  seed; the "above the bound at every rung" verdict comes from the other seeds. The CPCV path's alpha
  floor at seed 7 is 0.0056 - 0.1228 at 5,000 and 0.0178 - 0.0492 at 10,000 bars.)
- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`) still carries the mislabel
  the previous session removed from `test_performance`: it is `len(val_returns)`, not a period count.
  The recipe (capture a pre-rename baseline the way
  `tests/fixtures/test_performance_pre_rename_baseline.json` was captured, then extend
  `tests/test_test_window_observations.py`) is in the previous `HANDOFF_NEXT.md`.
- The framework's `summary["test_resolution"]` block still does not report the realized volatility its
  minimum detectable effect is conditional on, so a reader comparing two runs at the same T can
  misread a volatility difference as a sample-size difference. Measured here on the held-out test
  window's own returns (the series the resolution is computed on): the control's window is more
  volatile than the null's -- 12.08% against 10.98% annualized at 5,000 bars, 11.99% against 11.31% at
  10,000 bars -- which is why the two fixtures' alpha MDEs differ at the same T.

## Approaches that failed

- The first negative-control mutation (A) matched no anchor and was **skipped, not passed**; I fixed the
  anchor and re-ran the whole set rather than reporting a partial result.
- A first attempt to edit the test file in one large `edit` call failed repeatedly (the tool rejected the
  oversized parameter). Worked around by writing the new section in three chunks and splicing it in with
  a script -- no content was lost, but the diff is what a hand-written insert would have produced.

## Next task (one, precise)

**Settle the walk-forward path's alpha floor: measure it at 25,000 and 50,000 bars, and check whether
the tool's "no sample size would let this path confirm a plausible alpha" message survives.**

Evidence: at three seeds the walk-forward path's alpha floor (alpha*) is above the 10% plausibility bound
at every rung measured so far (2,500 / 5,000 / 10,000 bars), and the summary prints the absolute
conclusion "no sample size would let this path confirm a plausible effect". Seed 7 alone gives floors of
0.0026 - 0.0466 at 5,000 bars and 0.0059 - 0.0656 at 10,000 bars -- **below** the bound -- so the floor
is only above it on the other seeds, and it falls as the sample grows. The question is whether it falls
under 0.10 at a larger sample, which would make the printed conclusion wrong.

Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py --sizes 25000,50000
--paths walk_forward,cpcv --series both`; the ladder row's `alpha_floor_at_largest_size` and
`alpha_floor_beyond_plausible_bound` flags are the numbers to read. Seed 7 at 10,000 bars costs ~25 s for
the full ladder, so the 25,000/50,000 rungs are minutes, not hours.

Constraint: change no threshold, bound, criterion or verdict. If a larger sample brings the floor under
the bound, the fix is to the *message* (say "no measured sample size" and report the largest rung
measured), not to the bound; if it does not, the message stands and the numbers go into
`references/validation_methods.md` next to the other paths' floors.
