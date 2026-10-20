# Next task — 2026-10-20 (session)

## Task

**Report what sets the alpha floor: make the Deflated Alpha floor's driver visible in the
resolution report and in the reference docs, and pin the identity with a test.**

The framework reports `expected_max_alpha` — the deflation floor the alpha resolution
converges onto — as a bare number. This session established what that number is a function
of, and it is not what a reader would guess.

## Evidence

The Deflated Alpha floor is the cross-sectional dispersion of the **benchmark** alphas
scaled by the expected maximum of N draws:

```
alpha* = std(benchmark alphas, ddof=1) * sqrt(2 * ln(N)),   N = number of benchmarks
```

With the shipped two-benchmark set (the strategy's own series as the primary benchmark and
the alternative benchmark) that is `alpha* = 0.8326 * |alpha_strategy - alpha_benchmark|`.

Verified exactly — the framework's own `expected_max_alpha` divided by the formula's
prediction is **1.0000** in all four cases:

| Bars | Series | Strategy alpha | Benchmark alpha | Gap | Framework alpha\* | Formula |
| --- | --- | --- | --- | --- | --- | --- |
| 10,000 | effect | 0.026551 | 0.105321 | 0.078770 | 0.065580 | 0.065580 |
| 10,000 | no-effect | -0.021688 | -0.014591 | 0.007097 | 0.005909 | 0.005909 |
| 50,000 | effect | 0.047046 | 0.135285 | 0.088239 | 0.073464 | 0.073464 |
| 50,000 | no-effect | -0.027123 | -0.014862 | 0.012261 | 0.010208 | 0.010208 |

(Walk-forward path, seed 7, synthetic positive-control fixture; the alphas are the
framework's own, from `summary["benchmark_metrics"]` and `summary["deflated_alpha"]`.)

Two consequences, both worth stating in the docs:

- **The alpha floor tracks the strategy's own edge over the benchmark set, not the size of
  the parameter search.** The Deflated Sharpe floor is set by the dispersion of the trial
  Sharpes (the search); the Deflated Alpha floor is set by the spread of the *benchmark*
  alphas. A wider search does not raise it; a bigger edge does.
- **The floor does not go to zero with more data.** Only the estimation noise in the two
  alphas shrinks; the systematic gap survives. That is why the walk-forward path's
  criterion-5 crossing sits at 50,000 bars on this fixture: its floor plateaus at
  0.084-0.087 rather than falling away, and the alpha bound (0.10) is close to it.

The practical reading for a researcher: a *high* alpha floor is not a sign of a bigger
search or a worse test — it is a sign of a bigger gap between the strategy and its
benchmark set, and it is the number to read before asking for more data.

## Bounded work

1. `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`:
   `_measure_path` reads only `expected_max_alpha` from the framework's Deflated Alpha
   block. Add the floor's driver to the per-path block — the strategy's alpha, the
   dispersion of the benchmark alphas and the benchmark count — so the summary can say why
   the floor is where it is, and so the JSON carries the driver next to the number.
2. `skills/quantitative-backtesting/references/validation_methods.md`: a short subsection
   under the alpha-floor table ("The three analysis paths answer it differently") giving
   the identity, the measured numbers above, and what it means for reading the floor.
3. `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`: pin the
   identity against the framework's own block
   (`expected_max_alpha == std(trial alphas, ddof=1) * sqrt(2 ln N)`), so the documented
   formula and the code cannot drift apart. The measured ladder already in
   `tests/fixtures/resolution_ladder_2500_to_50000.json` does not carry the benchmark
   alphas, so this test should read them from a live measurement (cheap at 2,500 bars).

## Constraints

- Change no threshold, bound, criterion or verdict. `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10`
  and the 2.00 Sharpe bound stay; the shipped 0.6/0.2/0.2 split stays the default; the
  estimator itself is not to be touched.
- If the identity turns out to be a defect rather than a design choice — the framework's
  own docstring calls the cross-sectional estimator "conservative: they slightly overstate
  the Sharpe attainable from luck alone" — that is a separate finding to *report*, with
  the measurement, not to fix here.
- Keep the synthetic nature of the fixture stated wherever the numbers are reported: the
  fixture is a formula, not a market.

## Subsequent options (after this task)

- The resolution ladder has never been measured on a **real** history: the longest one in
  the repository is `assets/example_data/sample_panel_ohlcv.csv` (1,500 bars), far below the
  2,500-50,000 bar range where the crossings happen, so `--data FILE` has never been
  exercised on a history long enough to say anything about the crossing. That needs a
  longer history than the repository carries.
- The framework's `summary["test_resolution"]` block reports the trial and benchmark
  counts, the minimum detectable effects and the plausibility bounds — but not the realized
  volatility the minimum detectable effect is conditional on. Measured on the held-out test
  window's own returns: the control's window is more volatile than the null's (12.08%
  against 10.98% annualized at 5,000 bars), so the two fixtures' alpha MDEs differ at the
  same T and a reader comparing two runs at the same T could misread that as a
  sample-size difference. Whether to expose the conditioning is a reporting question to
  settle with evidence, not a threshold change. Blast radius: the block is written into the
  committed example artifacts (`examples/example_output/*.json`), so a new key means
  regenerating them.
- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`) carries the same
  mislabel the completed rename removed from `test_performance`: it is `len(val_returns)`
  (100 validation bars on the shipped sample), not a period count. Capture a pre-rename
  baseline fixture the same way `tests/fixtures/test_performance_pre_rename_baseline.json`
  was captured (same data / grid / split, provenance in the fixture) and extend
  `tests/test_test_window_observations.py` rather than writing a new harness.
- The held-out-fraction sweep is defined only for the out-of-sample path (the path that
  prices criterion 2 on the held-out window). The other two paths are configured in months,
  not in fractions, so they have no held-out fraction to sweep — worth stating explicitly
  in `references/validation_methods.md` if a reader asks why the sweep is one-path-only.
