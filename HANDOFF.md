# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("report the test resolution in the framework's own
verdicts, not only in the worked example") is done. All three analysis paths
now carry a consolidated `summary["test_resolution"]` block, and the CLI
prints it next to the Deflated Sharpe line.

### The new reporting-only block

`skills/quantitative-backtesting/scripts/walk_forward.py`:

- `_build_test_resolution(summary, returns, target_p_value=0.10)` -- builds
  the block from the aggregate `deflated_sharpe` / `deflated_alpha` the
  summary already carries and the return series they were computed on.
- `_test_resolution_message(resolution)` -- the one plain-English sentence the
  artifact carries and the console prints.
- `_print_test_resolution(resolution, indent="  ")` -- the console block, in
  the same style as `_print_thin_evidence_warning` /
  `_print_partial_selection_diagnosis`.
- `_format_optional_float(value, fmt)` -- shared "N/A"-safe formatter.
- `TEST_RESOLUTION_TARGET_P_VALUE = 0.10`, `PLAUSIBLE_MAX_ANNUALIZED_SHARPE
  = 2.0`, `PLAUSIBLE_MAX_ANNUALIZED_ALPHA = 0.10` -- the significance level
  the resolution is stated at, and the plausibility bounds (stated
  assumptions, reported with the result so they can be disputed).

Block shape:

| Key | Meaning |
| --- | --- |
| `n_test_observations` | `T`, the observations the statistic was computed on |
| `n_parameter_trials` | `N` of the Deflated Sharpe |
| `n_benchmarks` | `N` of the Deflated Alpha |
| `min_detectable_sharpe` / `min_detectable_alpha` | smallest annualized effect the statistic could confirm |
| `observed_annualized_sharpe` / `observed_annualized_alpha` | the observed effect, for comparison |
| `sharpe_status` / `alpha_status` | `resolvable` / `not_resolvable` / `not_applicable` |
| `sharpe_reason` / `alpha_reason` | why it is not resolvable |
| `sharpe_beyond_plausible_bound` / `alpha_beyond_plausible_bound` | is the required effect beyond what a plausible strategy produces? |
| `plausible_max_annualized_sharpe` / `plausible_max_annualized_alpha` | the bounds used |
| `message` | the statement the console prints |

### Where it is wired

- `walk_forward_analysis` (`summary["test_resolution"]`, built from
  `oos_returns`).
- `cpcv_analysis` (same, from the concatenated fold returns).
- `out_of_sample_validation` (same, from `test_returns`).
- CLI: `run_walk_forward`, `run_cpcv` and `run_out_of_sample_validation` print
  it immediately after the Deflated Sharpe line, labelled *"measurement, not
  a correction"*.

### Three deliberate properties

- **It changes no number.** The block is built from the statistics the
  verdict already rests on. No p-value, no verdict, no Sharpe, alpha or
  return moves.
- **An unresolvable statistic is never a number.** When the statistic and the
  return series do not match, the block reports `not_resolvable` with the
  reason (`returns_do_not_match_statistic`, `no_returns`, ...) and a `null`
  effect. A single-benchmark run has no Deflated Alpha statistic at all, so
  its alpha status is `not_applicable` (not "0.00%").
- **A run without a significance test says so.** With no `--deflate` and no
  benchmark set, both statuses are `not_applicable` and the message states
  that no significance test was run -- silence would be indistinguishable
  from a run that forgot to report the resolution.

### One source of truth for the plausibility bounds

`examples/falsifiable_hypothesis_example.py` previously declared its own
`PLAUSIBLE_MAX_ANNUALIZED_SHARPE` / `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`. It now
imports them from `walk_forward`, so the worked example and the library's
aggregate verdicts cannot drift apart. The values are unchanged (2.0 / 0.10)
and the example's output is byte-identical.

### What the resolution says on the shipped sample

Measured with `--deflate` on `assets/example_data/sample_ohlcv.csv`
(`fast_period` [5, 10] x `slow_period` [20, 30]):

| Path | Test observations | Parameter trials | Smallest confirmable annualized Sharpe | Observed | Deflated Sharpe p-value |
| --- | --- | --- | --- | --- | --- |
| walk-forward (12/3/3 months) | 189 | 12 | 2.9145 | 1.1613 | 0.5931 |
| CPCV (5 splits, test size 0.5) | 242 | 19 | 2.3573 | 0.1451 | 0.8233 |
| out-of-sample (0.6/0.2/0.2, 2 benchmarks) | 100 | 4 | 2.2878 | 0.8809 | 0.3427 |

Every threshold is an annualized Sharpe above the 2.0 plausibility bound, and
the two-benchmark out-of-sample run also reports a Deflated Alpha resolution
of 35.68% annualized alpha (observed 17.29%) against a 10% bound. So on the
shipped sample every significance verdict the framework reports is, in
substance, a statement about the size of the sample. That is the point of
reporting it next to the verdict.

### Documentation

- `references/validation_methods.md` -- new section "The framework's own
  verdicts report their resolution": the block shape, the three deliberate
  properties, and the table above.
- `SKILL.md` -- a new bullet under "Tips" (the framework-level resolution
  reporting), the "Validation and Robustness" capability line now says which
  paths report it, and the new test file is listed in the `tests/` inventory
  and in the "Test Coverage" command list.

## What was verified

- **Numeric parity, HEAD vs working tree.** A parity harness
  (`/home/runner/work/_temp/kilo-tmp/kilo/parity.py`) runs the walk-forward
  (single and multi benchmark), CPCV (single and multi benchmark) and
  out-of-sample (walk-forward and CPCV validation) paths on 600 deterministic
  synthetic daily bars and dumps every summary key. Baseline captured at
  HEAD (`ed044d4`), re-run on the working tree:
  **no numeric difference in any key outside the new `test_resolution`
  block, and `test_resolution` is the only key added** (the one error path --
  an out-of-sample run whose CPCV validation selected nothing -- adds no
  key, because it never reaches the statistics).
- **New test file**: `skills/quantitative-backtesting/tests/test_test_resolution.py`
  -- **14/14 pass**. It pins that all three paths report the block, that the
  block agrees with `minimum_detectable_sharpe` / `minimum_detectable_alpha`
  (and with the pre-existing `summary["minimum_detectable_*"]` keys), that an
  unmatched or missing return series is reported as `not_resolvable` with a
  reason and a `null` effect, that the plausibility flags agree with the
  bounds, that building the block **mutates nothing** and carries no verdict
  key, that a run without deflation says there is no resolution, and that the
  walk-forward and out-of-sample CLIs print the block next to the Deflated
  Sharpe line with the same number the artifact carries.
- **Whole skill suite**: 16/17 test files pass -- `test_cpcv` 29/29,
  `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 8/8,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 34/34,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_test_resolution` 14/14,
  `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. Verified by stashing this
  session's changes and re-running at HEAD: the same 9 failures. Not caused
  by this session.
- **The three CLIs were run end to end** with `--deflate` on the shipped
  sample (`walk-forward`, `cpcv`, `out-of-sample`); each prints the
  resolution block, and each writes the same numbers into its summary JSON.

## What remains unresolved

- **The `run_backtest.py` path still has no resolution** -- and it carries
  the evidence of an unfinished edit. The previous session's commit
  `ed044d4` changed the import to
  `from walk_forward import estimate_capacity, deflated_sharpe_ratio, minimum_detectable_sharpe`
  but **never used either name**: `run_backtest.py:1282` reads a local
  `dsr` dict out of `metrics`, so `deflated_sharpe_ratio` and
  `minimum_detectable_sharpe` are unused imports. The primary backtest entry
  point therefore prints a Deflated Sharpe Ratio with a p-value and no
  statement of what that test could have detected at all -- the exact defect
  this session fixed in the other three paths. This is the next task.
- **The three CLIs never print the aggregate Deflated Alpha Ratio.** They now
  print its *resolution* ("smallest confirmable annualized alpha 35.68%")
  but not the statistic the resolution belongs to (the DAR and its p-value),
  even though `summary["deflated_alpha"]` carries it. The per-benchmark
  corrected alpha p-value is printed, but that is a different statistic from
  the canonical aggregate DAR.
- **The framework's own key `test_n_periods`** (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to count
  periods. The example no longer misreports it; the framework's CLI and
  artifacts still do. Renaming or adding an alias changes the artifact
  shape, so it is deliberately left for a session that can also rebuild the
  parity harnesses.
- **Whether the example's criteria are satisfiable at all** has only been
  shown analytically (the minimum detectable effect). There is still no
  positive control: no run of the same machinery against a series with a
  known effect, so the claim "the test would have said yes to a large enough
  effect" is still an inference from the formula rather than an executed
  observation.
- `matplotlib` is missing from this environment, so the reporting tests and
  the tear-sheet figure paths cannot be exercised here.
- The parity harness lives in a temporary directory
  (`/home/runner/work/_temp/kilo-tmp/kilo/parity.py`) and will not survive
  the container; it is rebuildable from the description above.

## Approaches that failed and why

- A first attempt at editing `run_backtest.py`-adjacent code in this session
  accidentally created **two** copies of `_format_optional_float` (the edit
  inserted a copy instead of moving one). Caught by a `grep -n` count
  immediately after; fixed by removing both copies and re-inserting a single
  one above its first use, so the helper is now defined before the resolver
  that calls it. No behavioural difference; the file parses and the suite is
  green.
- The first parity-harness run reported "No valid parameters selected from
  validation phase" for the CPCV-based out-of-sample configuration. That is
  the framework's own diagnosis firing correctly (with `--cpcv-test-size 0.2`
  and 5 splits the effective out-of-sample fraction is 4% and no combination
  can take a position), not a harness bug. The harness keeps that
  configuration as a useful error-path case and adds CPCV runs with a larger
  test size where statistics exist.

## What was deliberately not done

- **No verdict, threshold or p-value was changed.** The resolution is
  reported *beside* the verdict, never folded into it. Changing a decision
  rule after seeing the result is the thing this framework exists to
  prevent.
- **The plausibility bounds are framework constants, not per-run inputs.**
  They are reported in every block and printed with the verdict so they can
  be disputed, but they never move a number.
- **The `run_backtest.py` path was left alone** even though it is the most
  obvious remaining gap, so that this session's parity claim covers exactly
  the three paths it claims to cover. It is the next task, with the dangling
  import as the evidence.
- No MCP, plugin, marketplace or agent-tooling surface was touched. The
  skill's frontmatter was not modified, so `skills/marketplace.yaml` needs
  no regeneration.
