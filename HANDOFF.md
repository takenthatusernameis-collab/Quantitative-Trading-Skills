# Handoff — 2026-10-21 (session)

## What changed

Completed the assigned task in `HANDOFF_NEXT.md`: **the committed resolution
ladder now carries the alpha-floor driver**, so a summary built from the
committed record says what sets the alpha floor at every measured rung
instead of saying the driver "is not measurable on this ladder".

No threshold, bound, criterion or verdict moved. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA
== 0.10`, `PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.00` and the shipped 0.6/0.2/0.2
split are untouched, and **the estimator itself was not touched**:
`scripts/walk_forward.py` and `scripts/measure_resolution_vs_sample_size.py`
are not in this session's diff at all. The only code change is a new test.

### 1. The re-captured ladder (`results/resolution_floor/ladder_2500_to_10000.json`)

The raw capture — the tool's own `--json` output (6 rows + the summary),
from

```
python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
    --sizes 2500,5000,10000 --paths out_of_sample,walk_forward,cpcv \
    --series both --seeds 7 --json
```

2,500 / 5,000 / 10,000 bars, seed 7, both series, all three paths. The
50,000-bar rung costs minutes per draw, so the whole ladder was not worth
re-running for the driver's own numbers; the cheap end of the same ladder is.

### 2. The trimmed fixture (`tests/fixtures/resolution_ladder_2500_to_10000.json`)

Six rows, with the same provenance shape as the 50,000-bar fixture (command,
description, environment, fixture construction, measured, measured_at_utc,
plausibility bounds, script commit), plus the split under
`provenance["measured"]["split"]`.

The trim keeps **every key the 50,000-bar fixture keeps** and *adds* the
driver keys: `strategy_alpha`, `benchmark_alphas`, `benchmark_alpha_std`,
`n_benchmarks`. The old capture is left exactly as it is — it is the record
of the long ladder, and the two agree.

### 3. The pin (`tests/test_resolution_vs_sample_size.py`)

New `test_the_re_captured_ladder_reports_what_sets_the_alpha_floor`:

- the fixture's provenance says what was measured (rungs, seed, draws per
  rung, the split);
- the identity is re-derived with the **standard library**
  (`statistics.stdev`, `math.sqrt(2 * math.log(n))`), not with the
  implementation's own estimator, and reproduces the framework's own
  `expected_max_alpha` on **all 18 row-and-path blocks**; the block's
  `benchmark_alpha_std` is the sample standard deviation and the block's
  `strategy_alpha` is the primary benchmark's alpha;
- the summary built from the fixture reports the driver for every path
  (`identity_holds_on_every_measured_draw is True`, 6 draws measured and 6
  checked), and every rung reports the dispersion its floor came from
  (`per_size_alpha[*].min/max_benchmark_alpha_std`);
- the printed report says what sets the floor and does **not** say
  "not measurable on this ladder";
- the re-capture is the *same measurement* as the older capture: every
  shared rung agrees to floating-point noise, so adding the driver moved no
  number.

The module docstring lists the new pin.

### 4. The docs

- `references/validation_methods.md`: the ladder section now names the
  second capture and says why it exists (the long capture predates the
  driver keys); the alpha-floor section gains a measured table of the driver
  at the largest rung of the re-capture, the count of blocks the identity
  holds on, and the per-rung keys that carry the driver.
- `SKILL.md`: the `test_resolution_vs_sample_size.py` entry names both
  captures and says which one carries the driver.

## What was actually verified

- **The capture was made from the tool itself** (the command above, run to
  completion) and the committed raw file is its stdout; the fixture is a
  trimmed copy of that file, checked value by value (252 values, all
  identical to 1e-12).
- **A summary built from the trimmed fixture reports the driver at every
  measured rung**, for all three paths, and the printed report says what
  sets the floor. The same summary built from the *older* fixture still
  prints "not measurable on this ladder" for all three paths — the contrast
  is the point of the new capture, and it is what the new pin asserts.
- **The driver reproduces the framework's own floor** on all 18 row/path
  blocks of the new capture (worst absolute difference below 1e-9 against
  the standard-library re-derivation; the framework's own numbers and the
  re-derived ones agree to the last floating-point bit in the printed
  output).
- **The re-capture did not move the measurement**: the 2,500 / 5,000 /
  10,000 rungs it shares with the 50,000-bar capture agree on every key —
  worst absolute difference 3.6e-15, worst relative difference 4.3e-14
  (floating-point noise between processes).
- **Negative controls**: five mutations applied one at a time to the
  fixture, the pinned test required to fail each time, the file restored
  byte-identically — 5/5.
  1. `benchmark_alphas` dropped from one block → fails (KeyError);
  2. `expected_max_alpha` changed on one rung → fails (the identity);
  3. `strategy_alpha` no longer the primary benchmark's alpha → fails;
  4. one measured number moved relative to the older capture → fails (the
     two captures must agree);
  5. the provenance's rung list changed → fails.
- `tests/test_resolution_vs_sample_size.py`: **30/30** (was 29; one new),
  11.4 min.
- **Neighbouring suites, re-run after the change**:
  `test_test_resolution.py` + `test_out_of_sample_window.py` +
  `test_test_window_observations.py` + `test_examples_coverage.py` +
  `test_falsifiable_hypothesis_example.py` = **78 passed**.
- `skills-ref validate skills/quantitative-backtesting/` → "Valid skill"
  (the CI validator used by `.github/workflows/validate-skills.yml`).

## What remains unresolved

- **The alpha floor is reported as 0.0000 on a path the framework could not
  price.** Found while exercising the `--data` path for the first time (see
  the next task): when the framework's alpha side is `not_resolvable`, the
  per-path block carries placeholder zeros and the report quotes them as a
  measured floor. **This is the next task.**
- The 50,000-bar capture still predates the driver keys, so a summary built
  from *it* still says "not measurable on this ladder". Re-capturing it
  would cost ~17 min for the 50,000-bar rung alone on this machine; the
  cheap capture now covers the driver's contract, so this is a
  nice-to-have, not a blocker.
- The resolution ladder has still never been measured on a history long
  enough to say anything about the crossing. The longest real history in
  the repo is `assets/example_data/sample_panel_ohlcv.csv` (1,500 bars) and
  `sample_ohlcv.csv` (504 bars), far below the 2,500-50,000-bar range where
  the crossings happen. The `--data` path was exercised for the first time
  this session on the 504-bar shipped sample (it works), but 504 bars is
  below the range that matters.
- The held-out-fraction sweep is defined only for the out-of-sample path
  (the path that prices criterion 2 on the held-out window). The other two
  paths are configured in months, not in fractions, so they have no
  held-out fraction to sweep — worth stating explicitly in
  `references/validation_methods.md` if a reader asks why the sweep is
  one-path-only.

## Approaches that failed

- None. The capture ran to completion on the first attempt, the five
  negative controls all behaved as required, and every suite passed on the
  first run.

## Next task (one, precise)

**Report an unpriceable alpha floor as unpriceable, not as 0.0000.**

Evidence: the `--data` path of
`scripts/measure_resolution_vs_sample_size.py` was exercised for the first
time this session, on the repository's own 504-bar history:

```
python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
    --data skills/quantitative-backtesting/assets/example_data/sample_ohlcv.csv \
    --sizes 504 --paths out_of_sample,walk_forward,cpcv
```

The CPCV path cannot price the alpha test on 504 bars, and the framework
says so — but the report then quotes its placeholder zeros as a measured
floor. The CPCV block (`measure_real(..., 504)["paths"]["cpcv"]`) is:

```
min_detectable_alpha: None
observed_annualized_alpha: 0.0
expected_max_alpha: 0.0
strategy_alpha: 0.0
benchmark_alphas: [0.0, 0.0]
alpha_status: not_resolvable
alpha_reason: zero_volatility
```

and the printed report says, for that path:

```
  the alpha (alpha*) floor is at or under the plausibility bound at the
  largest measured sample size (504 bars): the floor does not block
  criterion 5 at that size
  what sets the alpha floor (alpha*): std(benchmark alphas, ddof=1) * sqrt(2 ln N) with N = 2
    strategy alpha: 0.0000; benchmark alphas: 0.0000, 0.0000
    benchmark alpha dispersion (ddof=1): 0.0000; alpha* from that dispersion: 0.0000; the framework's own alpha*: 0.0000
    the framework's floor is reproduced from the benchmark alphas, so a higher alpha floor means a bigger gap ...
```

Both statements are wrong for a path whose criterion 5 was never evaluated:
the floor is 0 because the test could not be priced, not because the
dispersion is zero; and "the floor does not block criterion 5" is not
established when criterion 5 was not resolvable. The driver even reports the
identity as "reproduced" on a degenerate zero-dispersion draw. The same
zero-dispersion case makes `alpha_floor_beyond_plausible_bound` false and
`alpha_floor_at_largest_size` 0.0, so the *summary* says the alpha floor
never blocks criterion 5 on a path where it blocked nothing because it was
never measured.

Bounded work:

1. `scripts/measure_resolution_vs_sample_size.py`: make the alpha side
   distinguish "the framework could not price this criterion" from "the
   floor is zero". The per-path block already carries the framework's own
   `alpha_status` / `alpha_reason`; the driver (`_alpha_floor_driver`) and
   the floor status (`_print_floor_status`) should report a floor that was
   never measured as unpriceable, and the summary's
   `alpha_floor_beyond_plausible_bound` / `alpha_floor_at_largest_size`
   should not read a placeholder zero as a measurement. Additive only: no
   existing key changes value where the floor *was* measured, and no
   threshold, bound, criterion or verdict moves.
2. `tests/test_resolution_vs_sample_size.py`: pin the distinction — a
   measured floor still reports the driver and the identity, and an
   unpriceable one says so instead of quoting zeros. Use the 504-bar
   `--data` measurement above as the reproducer (it is cheap: a few
   seconds) or construct the block directly.
3. `references/validation_methods.md`: state the distinction next to the
   alpha-floor discussion, so a reader is not told that a criterion that
   could not be evaluated did not block.

Constraint: additive reporting. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`,
`PLAUSIBLE_MAX_ANNUALIZED_SHARPE`, the 0.6/0.2/0.2 split, the estimators
and every verdict stay exactly as they are. `scripts/walk_forward.py` is
not in this task's diff: the framework's own `alpha_status` /
`alpha_reason` already carry the fact, it is only the *report* that
misreads it.

Subsequent option (smaller, mechanical): the held-out-fraction sweep is
one-path-only; say why in `references/validation_methods.md`.
