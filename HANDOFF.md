# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("give the `run_backtest.py` path its test resolution
too, and print the aggregate Deflated Alpha the resolution belongs to") is
done.

### 1. The primary backtest entry point now reports its test resolution

`skills/quantitative-backtesting/scripts/run_backtest.py`:

- The dangling import is gone. `from walk_forward import estimate_capacity,
  deflated_sharpe_ratio, minimum_detectable_sharpe` became
  `from walk_forward import (_build_test_resolution, _print_deflated_alpha,
  _print_test_resolution, estimate_capacity)`. `pyflakes` reported
  `deflated_sharpe_ratio` and `minimum_detectable_sharpe` as unused at HEAD;
  it now reports nothing for `run_backtest.py` (the five pre-existing
  warnings in `walk_forward.py` are unchanged).
- `main()` builds the block right after the metrics are computed
  (`run_backtest.py:1155`):

  ```python
  metrics["test_resolution"] = _build_test_resolution(
      metrics, results.get("returns")
  )
  ```

  The statistic is read straight out of `metrics` -- the Deflated Sharpe
  Ratio `calculate_metrics` attached, and the aggregate Deflated Alpha Ratio
  it attached for a multi-benchmark run -- and inverted on
  `results["returns"]`, **the same series `calculate_metrics` hands to
  `deflated_sharpe_ratio`** (`performance.py:645`). So the resolution
  reported is the resolution of *that* statistic, not of a re-derived one.
- The block is printed next to the Deflated Sharpe line
  (`run_backtest.py:1312`), with the same wording the three analysis paths
  use, labelled *"measurement, not a correction"*.
- The block is carried in the artifact: `metrics.json` now has a
  `test_resolution` key with the same numbers the console prints.

### 2. The aggregate Deflated Alpha Ratio is printed next to its resolution

`skills/quantitative-backtesting/scripts/walk_forward.py`:

- New helper `_print_deflated_alpha(deflated_alpha, indent="", label=...)`
  (`walk_forward.py:4542`), next to `_print_test_resolution`. It prints the
  ratio, the p-value, the expected maximum alpha and the benchmark count --
  all read from the `summary["deflated_alpha"]` dict the artifact already
  carries, nothing recomputed.
- Wired into the three analysis CLIs, each immediately after its Deflated
  Sharpe line and before the resolution block:
  `run_cpcv` (`walk_forward.py:7119`), `run_walk_forward`
  (`walk_forward.py:8225`) and `run_out_of_sample_validation`
  (`walk_forward.py:9943`, labelled *"Deflated Alpha Ratio (test)"* to match
  that path's *"Deflated Sharpe Ratio (test)"*).
- Wired into `run_backtest.py` as well (`run_backtest.py:1308`), for the same
  reason: the run_backtest path now prints an alpha resolution, so the
  statistic that resolution belongs to has to be visible next to it.

### Three deliberate properties

- **It changes no number.** The resolution is built from the statistics the
  verdict already rests on, and the Deflated Alpha line prints numbers that
  are already in `summary["deflated_alpha"]` / `metrics["deflated_alpha"]`.
  No p-value, no verdict, no Sharpe, alpha or return moves.
- **The resolution is of the statistic it is printed next to.** The
  observation count and the observed effect in the block are the Deflated
  Sharpe Ratio's own `n_observations` and `sharpe_ratio`. A return series
  that does not match is reported as `not_resolvable` with the reason
  `returns_do_not_match_statistic` and a `null` effect -- never as a number.
- **A run without a significance test says so.** With no `--n-trials` and no
  benchmark set, both statuses are `not_applicable` and the message states
  that no significance test was run.

### What the new lines say on the shipped sample

`run_backtest.py`, on `assets/example_data/sample_ohlcv.csv`
(`--n-trials 12`, two benchmarks):

```
Deflated Sharpe Ratio: 0.0004 (p-value 0.9996, expected max Sharpe 1.5779, 12 trials)
Deflated Alpha Ratio: 0.0998 (p-value 0.9002, expected max alpha 3.99%, 2 benchmarks)
  Test resolution (measurement, not a correction):
    503 test observation(s), 12 parameter trial(s), 2 benchmark(s).
    Deflated Sharpe: smallest confirmable annualized Sharpe 2.5064 (observed -0.7783)
    Deflated Alpha: smallest confirmable annualized alpha 18.52% (observed -10.43%)
    Beyond the plausibility bound (annualized Sharpe <= 2.00, annualized alpha <= 10.00%):
      - Deflated Sharpe
      - Deflated Alpha
    A threshold the sample cannot resolve measures the sample, not the strategy.
```

The walk-forward CLI (12/3/3 months, `--deflate`, two benchmarks) now prints:

```
Deflated Sharpe Ratio: 0.4069 (p-value 0.5931, expected max Sharpe 1.4323, 12 trials)
Deflated Alpha Ratio: 0.6329 (p-value 0.3671, expected max alpha 14.87%, 2 benchmarks)
```

### Documentation

- `references/validation_methods.md` -- two new subsections under "The
  framework's own verdicts report their resolution": "The primary backtest
  entry point reports it too" (which series the block is built on, and why)
  and "The aggregate Deflated Alpha Ratio is printed next to its resolution".
- `SKILL.md` -- the "Validation and Robustness" capability line now names
  the `run_backtest` path as well; the `test_test_resolution.py` inventory
  entry describes the new coverage; a new tip states that a resolution
  without its statistic is not checkable.

## What was verified

- **Numeric parity, HEAD vs working tree.** A parity harness
  (`/home/runner/work/_temp/kilo-tmp/kilo/parity.py`) runs nine CLI
  configurations -- `run_backtest` (plain, `--n-trials`, `--n-trials` with
  two benchmarks), walk-forward, CPCV and out-of-sample (each plain and with
  two benchmarks) -- and flattens every artifact JSON to
  `{dotted_path: scalar}`. Baseline captured at HEAD (`d0f190d`), re-run on
  the working tree: **no numeric difference in any key outside the new
  `test_resolution` block, and `test_resolution` is the only key added**
  (the only other differences are the wall-clock `load_timestamp` values,
  which change on every run and are excluded). The three analysis paths'
  artifacts are otherwise identical, which confirms the Deflated Alpha line
  is console-only.
- **New test file** `skills/quantitative-backtesting/tests/test_test_resolution.py`
  -- **21/21 pass** (was 14). The seven new tests:
  - `test_the_run_backtest_cli_reports_the_test_resolution` -- the CLI prints
    the block next to its Deflated Sharpe line, `metrics.json` carries it,
    and the block's `n_test_observations` / `n_parameter_trials` /
    `observed_annualized_sharpe` are the Deflated Sharpe Ratio's own, and
    `n_benchmarks` / `observed_annualized_alpha` are the Deflated Alpha
    Ratio's own.
  - `test_the_run_backtest_resolution_is_built_on_the_statistics_own_series`
    -- builds the block the way `run_backtest` builds it
    (`calculate_metrics` + `_build_test_resolution(metrics,
    results["returns"])`) and pins that it equals
    `minimum_detectable_sharpe(metrics["deflated_sharpe"],
    results["returns"])`, and that a different series resolves to
    `not_resolvable`.
  - `test_the_run_backtest_cli_says_so_when_no_significance_test_was_run`.
  - `test_the_aggregate_deflated_alpha_is_printed_next_to_the_resolution`.
  - `test_the_walk_forward_cli_prints_the_aggregate_deflated_alpha`.
  - `test_the_cpcv_cli_prints_the_aggregate_deflated_alpha`.
  - `test_the_out_of_sample_cli_prints_the_aggregate_deflated_alpha`.
- **Whole skill suite**: 16/17 test files pass -- `test_cpcv` 29/29,
  `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 8/8,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 34/34,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_test_resolution` 21/21,
  `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. Verified by stashing this
  session's changes and re-running at HEAD: the **same 9 failures, by name**
  (diff of the two failure lists is empty apart from the run time).
- **Lint**: `pyflakes` on the three changed Python files reports only the
  five pre-existing `walk_forward.py` warnings (an unused
  `resolve_impact_aggregation` import and four f-strings without
  placeholders). The two new "imported but unused" warnings that the
  dangling import produced at HEAD are gone.

## What remains unresolved

- **Whether the example's criteria are satisfiable at all** has only been
  shown analytically (the minimum detectable effect). There is still no
  positive control: no run of the same machinery against a series with a
  known effect, so the claim "the test would have said yes to a large enough
  effect" is still an inference from the formula rather than an executed
  observation. **This is the next task.**
- **The framework's own key `test_n_periods`** (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to count
  periods. The example no longer misreports it; the framework's CLI and
  artifacts still do. Renaming or adding an alias changes the artifact
  shape, so it is deliberately left for a session that can also rebuild the
  parity harnesses.
- **`matplotlib` is missing from this environment**, so the reporting tests
  and the tear-sheet figure paths cannot be exercised here.
- The parity harness lives in a temporary directory
  (`/home/runner/work/_temp/kilo-tmp/kilo/parity.py`) and will not survive
  the container; it is rebuildable from the description above.

## Approaches that failed and why

- The first attempt at the CPCV CLI test used the CLI's default CPCV
  settings (`--n-splits 10 --test-size 0.1`). That is the framework's own
  "no parameter could be selected" diagnosis firing correctly: the
  effective out-of-sample fraction is `test_size / n_splits` = 1%, so no
  combination can take a position in a 5-bar window, and no statistic --
  hence no Deflated Alpha -- exists to print. The test now passes
  `--n-splits 5 --test-size 0.5`, the configuration the framework's own
  reference measurements use.

## What was deliberately not done

- **No verdict, threshold or p-value was changed.** The resolution and the
  Deflated Alpha line are reported *beside* the verdict, never folded into
  it. Changing a decision rule after seeing the result is the thing this
  framework exists to prevent.
- **The plausibility bounds are framework constants, not per-run inputs.**
  They are reported in every block and printed with the verdict so they can
  be disputed, but they never move a number.
- **`run_backtest.py` was not given a Deflated Alpha line of its own
  wording.** It reuses `_print_deflated_alpha`, so the four CLIs cannot
  drift apart.
- No MCP, plugin, marketplace or agent-tooling surface was touched. The
  skill's frontmatter was not modified, so `skills/marketplace.yaml` needs
  no regeneration.
