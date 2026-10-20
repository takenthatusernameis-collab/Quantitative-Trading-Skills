# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("build a positive control for the falsifiable-hypothesis
machinery") is done. Nothing in the framework's decision code was touched: the
control is a *fixture* plus *tests* that run the shipped example's own
criteria evaluation against it.

### 1. A new synthetic fixture with a known injected effect, and its no-effect control

`skills/quantitative-backtesting/scripts/generate_positive_control_data.py`
(new file):

- `generate_control_series(...)` builds the series from a written-out formula:
  5040 business days, 126-bar regimes (the length of the example's
  walk-forward training window), alternating `+0.4%` / `-0.4%` per-bar log
  drift (the **injected effect**), `N(0, 1%)` per-bar log noise, price
  `100 * exp(cumsum(log returns))`, OHLC derived from it. The return draws
  and the OHLC micro-structure use **separate** RNG streams, so the OHLC
  noise cannot perturb the return path.
- `write_control_fixture(directory, inject_effect=...)` writes the two files
  the example's `BENCHMARK_FILES` list resolves relative to the data file:
  `sample_ohlcv.csv` (the strategy's own series, which is also the primary
  buy-and-hold benchmark) and `sample_benchmark.csv` (an alternative
  benchmark drawn from the same construction with a different seed).
  `inject_effect=False` writes the **no-effect control**: the identical
  draws with the regime drift removed.
- The module docstring and the exported `FIXTURE_PURPOSE` label the fixture
  as a *test-machinery check on synthetic data* and state that it is not
  evidence about any security. `--out DIR` materializes it for inspection.

### 2. The control tests

`skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
was **extended** (8 -> 14 tests). The new tests:

| Test | What it pins |
| --- | --- |
| `test_the_synthetic_positive_control_returns_supported` | the example's own criteria return `SUPPORTED` on the effect series, all five criteria pass, and the verdict came through the shipped path (disjoint/chronological split, no train/test overlap, PIT passed, bias controls engaged) |
| `test_the_positive_control_effect_clears_the_reported_minimum_detectable_effect` | the observed effect exceeds the framework's own reported minimum detectable effect (so the verdict is a power statement, not luck), **and** no criterion is beyond the sample's resolution |
| `test_the_no_effect_control_returns_not_supported` | the matched no-effect series is `NOT SUPPORTED`, and the significance criteria are the ones that fail |
| `test_the_control_pair_differs_only_by_the_injected_effect` | the pair differs by exactly the injected drift and nothing else (the log-return difference equals the regime drift to 1.3e-15) |
| `test_the_control_verdict_is_not_a_property_of_one_seed` | the verdicts hold on further seeds (1 and 2024) |
| `test_the_control_fixture_is_labelled_as_synthetic_and_carries_no_security` | the purpose label says synthetic / not evidence, and the fixture carries no symbol/ticker/name column |

### 3. Documentation

- `references/validation_methods.md` -- new subsection **"A positive control:
  the machinery can say yes"** under "Test Resolution (Minimum Detectable
  Effect)": the construction table, the numbers the framework reports on the
  control, and an explicit "what the control does not establish" paragraph.
- `SKILL.md` -- the new script in the `scripts/` inventory, a new
  `tests/` inventory entry, a new tip ("the significance machinery is only
  half-demonstrated by a sample it cannot resolve"), and a `Test Coverage`
  bullet for the extended test file.
- `examples/README.md` -- a short note under `falsifiable_hypothesis_example.py`
  pointing at the control and restating that it says nothing about a market.

## What was verified

- **The shipped sample did not move.** `examples/falsifiable_hypothesis_example.py`
  stdout was captured before and after the change and `diff` reports the two
  files **byte-identical** (97 lines, same verdict, same resolution block).
  The example and the shipped CSV were not edited.
- **The control, effect series (seed 7)** -- `SUPPORTED`, all five criteria
  pass:

  ```
  1006 test observations, 435 parameter trials, 2 benchmarks
  observed out-of-sample Sharpe      3.1536   (min confirmable 1.8334)
  observed annualized alpha         40.77%   (min confirmable 8.91% / 8.20%)
  Deflated Alpha Ratio               1.000000
  raw benchmark-alpha p-value        1.5e-21
  Deflated Sharpe p-value            2.5e-05
  criteria beyond the sample's resolution:  none
  OOS total return 367.6%  vs  benchmark -16.3%
  selected params {'fast_period': 10, 'slow_period': 30}
  ```

  This is the first case in the repository where the significance criteria
  are demonstrably **within** the sample's resolution (1.83 < 2.0 and
  8.91% < 10%), i.e. the first case where a `SUPPORTED` verdict is
  informative rather than a statement about the sample size.
- **The control, no-effect series (seed 7)** -- `NOT SUPPORTED`: OOS Sharpe
  -0.1804, Deflated Sharpe p-value 0.998, DAR 0.5188; criteria 1, 2, 3 and 5
  fail, criterion 4 (return above the benchmark's) passes on a driftless path.
- **Not a lucky seed.** Across seeds 1, 3, 7, 11, 42 and 2024 the effect
  series is `SUPPORTED` and the no-effect series is `NOT SUPPORTED` in every
  case. The test pins seed 7 plus seeds 1 and 2024.
- **Whole skill suite**: 16/17 test files pass -- `test_cpcv` 29/29,
  `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` **14/14**
  (was 8/8), `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 34/34,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_test_resolution` 21/21,
  `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. Verified by stashing this
  session's changes and re-running at HEAD: the **same 9 failures, by name**.
- **Lint**: `pyflakes` reports nothing for the two changed Python files;
  `py_compile` is clean. The CLI entry point runs and materializes the
  fixture.

## What remains unresolved

- **The finding the control produced: the pre-registered criteria are hard to
  satisfy at plausible effect sizes.** Criterion 2 is a *deflated* Sharpe
  test, and its deflation benchmark (the expected maximum Sharpe over the
  parameter grid) is estimated from the **dispersion of the trial Sharpes**.
  That dispersion does not shrink as the sample grows -- the number of trials
  grows with the number of validation windows, so the expected maximum grows
  with it -- while the `1/sqrt(T)` term shrinks. Measured on the shipped
  paths and on the control, the smallest confirmable annualized Sharpe was
  4.20 (the worked example, 100 test observations), 2.29-2.91 (the other
  shipped paths), and 1.83-2.40 on the synthetic controls at 498-1006 test
  observations. An annualized Sharpe of 1.5 -- a plausible result for a good
  strategy -- is below every one of those thresholds. **No sample size has
  yet been shown at which criterion 2 becomes confirmable at the stated
  plausibility bound.** That is the open question; see HANDOFF_NEXT.md.
- **The framework's own key `test_n_periods`** (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to count
  periods. The example no longer misreports it; the framework's CLI and
  artifacts still do. Renaming or adding an alias changes the artifact
  shape, so it is deliberately left for a session that can also rebuild the
  parity harnesses.
- **The cost-sweep paths** (`run_backtest.py --commission/--slippage`) report
  a Sharpe per sweep point without a resolution, so a swept Sharpe carries
  the same defect the `run_backtest.py` path had.
- **`matplotlib` is missing from this environment**, so the reporting tests
  and the tear-sheet figure paths cannot be exercised here.
- A `RuntimeWarning: invalid value encountered in divide` from numpy's
  correlation computation appears on some no-effect control runs. It comes
  from the framework's own correlation over a zero-variance window (the
  long-only strategy is flat for a whole window), not from the new code; the
  verdict is unaffected.
- The fixture is **not committed as CSV data**: it is regenerated
  deterministically from the generator inside the test, so the repository
  does not carry ~1 MB of synthetic price rows.

## Approaches that failed and why

- **Regimes shorter than the indicator warm-up.** With 63-bar regimes the
  crossover's slow SMA (up to 50 bars) cannot identify a leg, the strategy's
  edge collapses, and the control returned `NOT SUPPORTED` (Deflated Sharpe
  p-value 0.877). The regime length has to exceed the longest lookback in
  the grid with room to spare.
- **Regimes longer than the held-out window.** With 1250-bar regimes and a
  5000-bar sample the 998-bar test window fell entirely inside one leg, the
  strategy was flat for the whole window, and the OOS Sharpe was -1.879 --
  `NOT SUPPORTED` again, this time with no valid selection. The regime
  length must be short enough that the test window contains both a rising
  and a falling leg.
- **Regimes long enough to be tradeable but not commensurate with the
  training window (e.g. 250-bar regimes in a 2500-bar sample).** This works
  (the control passed) but the trial Sharpes become heterogeneous -- some
  windows are entirely inside a rising leg, others entirely inside a falling
  one -- so the dispersion that feeds the deflation benchmark inflates and
  the minimum confirmable Sharpe rises to 3.05-4.17 annualized, above the
  plausibility bound. The shipped control uses a regime length equal to the
  walk-forward training window (126 bars) precisely so every validation
  window contains the same mix of one rising and one falling regime and the
  trial Sharpes stay comparable.
- **The first generator draft drew the OHLC micro-noise from the same RNG
  stream as the returns**, so the OHLC noise could have perturbed the return
  path. The generator now uses a separate stream (`seed + 1`) for the OHLC
  and volume.

## What was deliberately not done

- **No verdict, threshold, criterion or p-value was changed.** The control
  asserts; it does not decide. The example's criteria, the plausibility
  bounds and the resolution reporting are untouched, and the shipped
  sample's output is byte-identical.
- **The control's effect size was not tuned to sit inside the plausibility
  bounds.** It is set where the framework's own reported minimum detectable
  effect can be cleared, and the fact that the required effect is far
  outside the bounds is reported as a finding rather than engineered away.
- **The fixture was not committed as data.** A deterministic generator plus
  a seeded construction is reproducible and keeps the repository free of a
  megabyte of synthetic price rows.
- No MCP, plugin, marketplace or agent-tooling surface was touched. The
  skill's frontmatter was not modified, so `skills/marketplace.yaml` needs
  no regeneration.
