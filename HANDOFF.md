# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("focus on the falsifiable hypothesis example or
extend thin-evidence gating") is done. The example's `NOT SUPPORTED` verdict
was investigated, and the investigation found two real defects. Both are
fixed, and the example now reports what its verdict can and cannot mean.

### Finding 1 (defect): criteria 3 and 5 were the same statistic

`examples/falsifiable_hypothesis_example.py` read the primary benchmark's
`alpha_pvalue` for criterion 3 ("benchmark alpha p-value < 0.05"). In the
multiple-benchmark path the benchmark correction **rewrites** `alpha_pvalue`
with the deflated p-value and keeps the raw one in `alpha_pvalue_original`
(`scripts/walk_forward.py`, `_benchmark_list_alpha_correction`). So criterion 3
was silently testing the *corrected* p-value -- the same number criterion 5
tests (1 - DAR). On the shipped fixture both were 0.5622, the raw value
(0.8991) was never surfaced, and the advertised "benchmark-side data-mining
control" could never bind independently: criterion 5 was implied by criterion 3.

Fix: criterion 3 now reads `alpha_pvalue_original` (the raw, uncorrected
alpha t-test p-value) and criterion 5 keeps the corrected value. Both are
printed with explicit labels and both are returned in `observed`
(`benchmark_alpha_pvalue` = raw, `benchmark_alpha_pvalue_corrected` =
corrected, `benchmark_alpha_correction_applied` = whether a correction was
engaged at all). The criterion descriptions in `CRITERIA` say which is which.

### Finding 2 (defect): the verdict was reported without the test's resolution

With 100 test observations, the example's three significance criteria require
effects that no plausible strategy produces, so the verdict was close to a
foregone conclusion and said nothing about the strategy:

| Criterion | Required to pass | Observed |
| --- | --- | --- |
| 2 deflated Sharpe p < 0.10 | annualized Sharpe >= 4.1950 | -0.3581 |
| 3 raw benchmark alpha p < 0.05 | annualized alpha >= 38.02% | -2.43% |
| 5 Deflated Alpha Ratio > 0.90 | annualized alpha >= 35.34% | -2.43% |

Fix: the example now reports the **test resolution** -- the minimum
detectable effect of each statistical criterion at the sample size actually
available -- and names the criteria the sample cannot resolve. A failed
criterion that the sample cannot resolve is a statement about the sample, not
evidence against the hypothesis.

The verdict itself is **not** changed: it stays the conjunction of the
pre-registered criteria (a decision rule is not revisited after the result is
seen). The resolution is reported *beside* the verdict, and the console says
so in plain words ("HOW TO READ THIS VERDICT").

The plausibility bounds used to flag a criterion (`PLAUSIBLE_MAX_ANNUALIZED_SHARPE
= 2.0`, `PLAUSIBLE_MAX_ANNUALIZED_ALPHA = 0.10`) are stated assumptions,
declared in the module and printed with the result so they can be disputed.

### Finding 3 (labelling): "Test periods: 100" was not 100 periods

The framework's `test_n_periods` is `len(test_returns)` -- the number of test
**observations** (daily bars in the held-out window). The example printed it
as "Test periods", which reads as 100 independent periods. The example now
reports it as `test_n_observations` and prints "Test observations: 100
(daily bars in the held-out window, not independent periods)". The framework
key itself is unchanged (see "unresolved" below).

### New reusable helpers

`scripts/walk_forward.py` (next to `deflated_sharpe_ratio` /
`deflated_alpha_ratio`):

- `_normal_quantile(p)` -- inverse normal CDF, stdlib only (`statistics.NormalDist`).
- `_deflation_z_score(effect, effect_star, t_obs, skew, kurt)` -- the z-formula
  of both deflated statistics in one place; the minimum-detectable-effect
  helpers invert it, so forward and inverse cannot drift apart.
- `_solve_minimum_effect(target_z, effect_star, t_obs, skew, kurt)` -- the
  inversion (bracket expansion + bisection).
- `minimum_detectable_sharpe(deflated_sharpe, returns, target_p_value=0.10)` --
  the smallest annualized Sharpe whose deflated p-value reaches the target.
- `minimum_detectable_alpha(deflated_alpha, returns, target_p_value=0.10)` --
  the Deflated Alpha analogue (smallest annualized alpha).

`scripts/performance.py`:

- `t_critical_value(df, two_sided_alpha=0.05)` -- the inverse of the skill's
  own `_t_two_sided_pvalue` (bisection, no SciPy). Used for the raw alpha
  t-test's minimum detectable effect.

`examples/falsifiable_hypothesis_example.py`:

- `_alpha_regression_df(test_returns, benchmark_frame)` -- degrees of freedom
  of the benchmark alpha regression (aligned observations minus two).
- `_test_resolution(summary, test_returns, benchmark_frame, primary_bench)` --
  assembles the resolution block and flags the criteria beyond it.

### Documentation

- `SKILL.md` -- new bullet under "Tips" (the verdict-resolution rule) and a
  new line under "Validation and Robustness".
- `references/validation_methods.md` -- new section "Test Resolution
  (Minimum Detectable Effect)" with the helpers, the reading rule, and the
  table of required vs observed effects.
- `examples/README.md` -- a section for `falsifiable_hypothesis_example.py`
  (it was not documented there before).

## What was verified

- `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`:
  8/8 pass (5 new). The suite now shares one pipeline run between the tests
  instead of running it per test.
- `skills/quantitative-backtesting/tests/test_walk_forward.py`: 183/183 pass
  (6 new: the z-mirror, both round trips, the sample-size monotonicity, the
  graceful degradation, and `t_critical_value`).
- Whole skill suite, every test file: 15/16 files pass --
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 8/8,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 34/34,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. Verified by stashing this
  session's changes and re-running at HEAD: the same 9 failures, same count.
  Not caused by this session.
- The example runs end to end on the shipped sample and prints the resolution
  section, the flagged criteria, and the "HOW TO READ THIS VERDICT" note.

## What remains unresolved

- The framework's own key `test_n_periods` (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to count
  periods. The example no longer misreports it, but the framework's CLI and
  artifacts still do. Renaming or adding an alias changes the artifact shape,
  so it is deliberately left for a session that can also rebuild the parity
  harnesses.
- The resolution analysis exists only in the worked example. The library's own
  verdicts (walk-forward / CPCV / out-of-sample aggregates) do not yet report
  a minimum detectable effect next to the Deflated Sharpe / Deflated Alpha
  numbers they carry.
- Whether the example's criteria are *satisfiable at all* has only been shown
  analytically (the minimum detectable effect). There is no positive control:
  no run of the same machinery against a series with a known effect, so the
  claim "the test would have said yes to a large enough effect" is still
  an inference from the formula rather than an executed observation.
- `matplotlib` is missing from this environment, so the reporting tests and
  the tear-sheet figure paths cannot be exercised here.

## Approaches that failed and why

- The first full-suite run used a shell `for f in skills/.../test_*.py` loop
  inside a background process; the loop variable did not expand and every
  invocation ran `python3` against the working directory
  ("can't find '__main__' module"). Replaced with a Python driver
  (`/home/runner/work/_temp/kilo-tmp/kilo/run_suite.py`) that globs the test
  files and runs each with `subprocess` -- the glob then works and the
  per-file summary is captured.
- One new test asserted `minimum_detectable_alpha(dsr, ...)["reason"] ==
  "no_deflated_alpha"`. A Deflated Sharpe result *is* a dict, so the helper
  got past the type check and failed later with `no_expected_max_alpha`.
  Fixed the assertion to the reason the code actually produces, and the
  distinction is now documented in the test.
- The suite driver initially resolved the repository root from
  `Path(__file__).parent`, which pointed at the temporary directory and found
  0 test files. Fixed by pinning the repository path.

## What was deliberately not done

- The verdict vocabulary was **not** extended (no "INCONCLUSIVE" verdict) and
  the pre-registered criteria were **not** re-thresholded. Both would be
  decisions made after seeing the result, which is the thing this framework
  exists to prevent. The resolution is reported as interpretation, not as a
  change to the decision rule.
- The plausibility bounds are module constants in the example, not framework
  defaults, so no other path's numbers move.
- No parity harness was rebuilt this session (the previous session's harnesses
  lived in a temporary directory that was wiped). No framework number changed:
  the new helpers are additive functions, `t_critical_value` is additive, and
  the only behaviour change is inside the worked example.
