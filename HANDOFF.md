# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("quantify how large a sample the pre-registered
criteria need -- and whether any sample size can confirm a plausible effect")
is done, and it **overturned the hypothesis the task was built on**: there
*is* a sample size at which criterion 2 can confirm a plausible effect.
Nothing in the framework's decision code was touched: the work is a
measurement tool, an executable check and a write-up.

### 1. The measurement tool

`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`
(written over the stub the previous session left behind):

- It runs the **shipped configuration** -- the worked example's grid, costs,
  benchmark set, 6-month walk-forward training window, 2-month test/step
  windows and 0.6/0.2/0.2 chronological split -- through the framework's own
  `out_of_sample_validation`, and reports the framework's own
  `summary["test_resolution"]` block (built by `_build_test_resolution`, the
  same builder the walk-forward, CPCV and out-of-sample paths attach to
  their summaries). It re-derives nothing, re-tunes nothing, and changes no
  threshold, no bound, no criterion and no verdict.
- It sweeps a ladder of sample sizes (default 500 / 1,000 / 2,500 / 5,000 /
  10,000 bars) over the **synthetic control fixture** (both the effect
  series and the no-effect series, over three seeds), and reports the
  minimum confirmable annualized Sharpe / alpha, the framework's own
  deflation benchmark `SR*` (`expected_max_sharpe`), the observed
  out-of-sample Sharpe, and whether criterion 2 is inside or beyond the
  plausibility bound at each rung.
- `--data FILE` measures the same curve on the **first N bars of a real
  history** (the benchmark set is resolved from the file's directory, as the
  worked example resolves it). On the shipped 504-bar sample it reproduces
  the example's own reported threshold exactly (4.1950).
- `summarize()` reports the crossing per size over the draws measured there
  (`first_size_all_within_bound` / `first_size_any_within_bound`), because
  the crossing moves with the draw.

### 2. The executable check

`skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`
(new, 4 tests):

| Test | What it pins |
| --- | --- |
| `test_the_resolution_improves_with_the_sample_size` | on the no-effect control, the minimum confirmable annualized Sharpe falls from above the 2.0 bound at 2,500 bars to at or below it at 10,000 bars, and the floor it converges onto (`expected_max_sharpe`) is below the bound |
| `test_the_crossing_is_not_a_property_of_one_random_draw` | at 10,000 bars criterion 2 is inside the sample's resolution on **every** draw measured (seeds 7, 1, 2024, both series), and at 2,500 bars it is outside the resolution on every one |
| `test_the_measurement_agrees_with_the_shipped_example_path` | the measurement's resolution equals the resolution the worked example's own `run_hypothesis_test` reports on the same data (so it measures the shipped configuration, not a private copy) |
| `test_the_measurement_moves_no_threshold_and_no_verdict` | the plausibility bounds are the framework's and unmoved, the summary reports a size and never a verdict |

### 3. The write-up -- including a correction

`references/validation_methods.md`:

- New section **"How much data does criterion 2 need?"** (after the
  positive control): the measured curve for both series, the explicit
  answer, the mechanism (`mde = sqrt(ann) * [SR* + z_target / sqrt(T-1)]`),
  and what the measurement does not establish.
- **A paragraph from the previous session was corrected.** It concluded from
  the control alone that "the dispersion does not shrink as the sample grows
  ... so no sample size may suffice at all". The measurement shows the
  opposite: the dispersion *does* shrink (the walk-forward training window
  expands, so the later trial Sharpes are more precise), the resolution
  falls, and criterion 2 becomes confirmable at a plausible effect size. The
  corrected paragraph keeps the true statement (the thresholds measured on
  the shipped samples are above 1.5) and drops the unsupported
  generalization.
- `SKILL.md` (script and test inventories, a tip, a Test Coverage bullet)
  and `examples/README.md` (a short note next to the example).

## What was verified

- **The answer to the open question: yes, there is such a sample size.** On
  the control's construction the minimum confirmable annualized Sharpe
  falls below the framework's 2.0 plausibility bound at a few thousand
  daily bars:

  | Bars | Test observations | Trials | Smallest confirmable annualized Sharpe (no-effect / effect) | SR* (no-effect / effect) | Criterion 2 |
  | --- | --- | --- | --- | --- | --- |
  | 500 | 98 | 13 / 4 | 3.8311 / 2.8591 | 1.7356 / 0.7768 | beyond the bound |
  | 1,000 | 198 | 50 / 53 | 3.1161 / 3.0915 | 1.6491 / 1.7752 | beyond the bound |
  | 2,500 | 498 | 233 / 189 | 2.3975 / 2.4011 | 1.4403 / 1.4985 | beyond the bound |
  | 5,000 | 998 | 510 / 434 | 1.9096 / 1.8373 | 1.2560 / 1.2135 | within the bound |
  | 10,000 | 1,998 | 1,047 / 897 | 1.7136 / 1.6012 | 1.2557 / 1.1584 | within the bound |
  | 25,000 | 4,998 | 2,641 / 2,210 | 1.3519 / 1.2037 | 1.0618 / 0.9208 | within the bound |
  | 50,000 | 9,998 | 5,347 / 4,424 | 1.1012 / 1.0100 | 0.8975 / 0.8098 | within the bound |

  The crossing itself: between 4,000 and 4,500 bars on the no-effect series
  (seed 7) and between 3,000 and 4,000 on the effect series (seed 7); later
  on the other seeds (5,000-6,000 on seed 2024, 6,000-10,000 on seed 1);
  **by 10,000 bars every draw measured is inside the bound** (1.52-1.82
  across three seeds and both series).
- **The shipped example's stdout is byte-identical.** Captured before and
  after the change and `diff`ed: no difference (97 lines, same verdict,
  same resolution block). The example and the shipped CSV were not edited.
- **The shipped sample's own numbers are reproduced by the new tool**:
  `--data assets/example_data/sample_ohlcv.csv --sizes 504` reports the
  minimum confirmable annualized Sharpe **4.1950** -- the number the
  example prints ("Criterion 2 needs an annualized Sharpe of at least
  4.1950") -- and the observed Sharpe -0.3581, matching the shipped
  output.
- **The whole skill suite**: 18/18 test files pass except the pre-existing
  `test_reporting.py` failures -- `test_cpcv` 29/29, `test_data_loader`
  32/32, `test_examples_coverage` 7/7, `test_execution_warmup` 8/8,
  `test_falsifiable_hypothesis_example` 14/14, `test_generate_sample_data`
  2/2, `test_inert_param_grid` 27/27, `test_monte_carlo` 20/20,
  `test_no_selection_diagnosis` 34/34, `test_out_of_sample_window` 10/10,
  `test_panel_reference_pinned` 2/2, `test_performance` 33/33,
  **`test_resolution_vs_sample_size` 4/4 (new)**, `test_run_backtest`
  104/104, `test_strategy_builder` 33/33, `test_test_resolution` 21/21,
  `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. The failure names are the same
  nine as at HEAD.
- **Lint**: `pyflakes` reports nothing for the two new/changed Python
  files; `py_compile` is clean. The script's CLI runs, and its `--data` and
  synthetic paths both work.
- The skill's frontmatter was not modified, so `skills/marketplace.yaml`
  needs no regeneration.

## What remains unresolved

- **The floor is a property of the sample, and the shipped sample's floor is
  just above the bound.** On the shipped 504-bar sample the deflation
  benchmark `SR*` is **2.0138**: the 21 configurations its search evaluated
  were, on their own, expected to produce an annualized Sharpe of 2.01 from
  luck alone, so on that sample criterion 2 cannot confirm a plausible
  effect at *any* sample size. More data of the same kind helps (the
  1/sqrt(T) term), but the floor only falls if the *dispersion* of the trial
  Sharpes falls. Whether a real strategy's floor is below 2.0 is a
  property of that strategy on that data -- the framework already reports
  the number (`expected_max_sharpe`), and the new tool measures the whole
  curve on a real history with `--data`.
- **The resolution-vs-sample-size curve was measured on the out-of-sample
  path only** (the worked example's configuration). The walk-forward and
  CPCV paths build their own `summary["test_resolution"]` on a different
  return series (the concatenated out-of-sample windows of the search
  itself, not the held-out window), so their curves are not measured yet.
- **The framework's own key `test_n_periods`** (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to
  count periods. The example no longer misreports it; the framework's CLI
  and artifacts still do. Renaming or adding an alias changes the artifact
  shape, so it is deliberately left for a session that can also rebuild the
  parity harnesses.
- **The cost-sweep paths** (`run_backtest.py --commission/--slippage`) report
  a Sharpe per sweep point without a resolution, so a swept Sharpe carries
  the same defect the `run_backtest.py` path had.
- **`matplotlib` is missing from this environment**, so the reporting tests
  and the tear-sheet figure paths cannot be exercised here.
- A `RuntimeWarning: invalid value encountered in divide` from numpy's
  correlation computation appears on some runs (including on the no-effect
  control). It comes from the framework's own correlation over a
  zero-variance window (the long-only strategy is flat for a whole window),
  not from the new code; the verdict is unaffected.

## Approaches that failed and why

- **The hypothesis the task was built on failed.** The previous session's
  note predicted that "the number of trials grows with the sample, so the
  expected maximum grows with it" and that the resolution would therefore
  *not* fall below ~1.8-2.4 at any sample size. The measurement refutes it:
  the trial count does grow, but only through `sqrt(2 ln N)` (3.5 at
  N = 400, 4.1 at N = 4,400), and the *dispersion* the deflation benchmark
  is estimated from falls as the sample grows, because the walk-forward
  training window expands and the later trial Sharpes are estimated on
  more data. The first draft of the analysis, which assumed a fixed-length
  training window, reproduced the wrong prediction.
- **A sample-size ladder built on the control's own regime structure alone
  would have been circular.** The control's regime length equals the
  walk-forward training window on purpose, so the trial Sharpes stay
  comparable. The ladder therefore measures **both** the effect series and
  the no-effect series, and the no-effect series is the null calibration
  (with the drift removed the trial Sharpes are pure estimation noise,
  which is what `SR*` is meant to measure). The regime length turns out not
  to matter for the no-effect series at all (the drift is removed, so the
  series is the same random walk), and the measured curve is insensitive to
  it (identical to four decimal places at 63, 126 and 252 bars).
- **The curve is not monotone, and a single seed would have misreported
  it.** On seed 1 the effect series *rises* from 2.11 (3,000 bars) to 2.16
  (5,000 bars) before falling. The tool therefore reports the crossing per
  size over the draws measured at that size, and the test pins the crossing
  on three seeds rather than on one.
- **Reading the resolution off the walk-forward path's own aggregate was
  not attempted.** Its return series (the concatenated out-of-sample windows
  of the search) is not the held-out window, so its resolution is a
  different statistic; it is left for the next session rather than mixed
  into this one.

## What was deliberately not done

- **No threshold, bound, criterion or verdict was changed.** The measurement
  reads `minimum_detectable_sharpe` / `minimum_detectable_alpha` /
  `_build_test_resolution`; it does not re-derive or re-tune them.
  `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` (2.0) and
  `PLAUSIBLE_MAX_ANNUALIZED_ALPHA` (0.10) stay where they are, and the
  test asserts it.
- **The positive control's fixture and verdicts were not touched.**
  `scripts/generate_positive_control_data.py` is unchanged; the ladder
  regenerates the same construction at other lengths. The control's own
  verdicts (`SUPPORTED` / `NOT SUPPORTED`) and numbers are unchanged --
  `test_falsifiable_hypothesis_example.py` is still 14/14.
- **The shipped sample's output was not moved** (byte-identical, verified).
- **The fixture was not committed as data.** It is regenerated
  deterministically from the generator inside the test, so the repository
  does not carry ~1 MB of synthetic price rows.
- No MCP, plugin, marketplace or agent-tooling surface was touched.
