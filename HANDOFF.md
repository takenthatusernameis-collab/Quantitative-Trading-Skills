# HANDOFF

## What changed this session

Extended the falsifiable-hypothesis worked example
(`skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`,
currently single-benchmark) to exercise the multiple-benchmark Deflated Alpha
Ratio as a data-mining-control falsification criterion, per the prior handoff.

- `examples/falsifiable_hypothesis_example.py`:
  - Added a fifth pre-registered falsification criterion:
    `deflated_alpha_ratio_gt_0.90` ("Deflated Alpha Ratio > 0.90", i.e.
    corrected benchmark-alpha p-value < 0.10). This is the benchmark-side
    data-mining control: testing against multiple benchmarks is itself a
    multiple-testing problem, and this criterion requires the benchmark alpha
    to survive the Deflated Alpha Ratio correction for the number of benchmarks
    tested (N). It is the analogue of criterion 2 (Deflated Sharpe Ratio),
    which corrects the parameter-grid selection bias.
  - Switched the example from a single benchmark to a benchmark set
    (`BENCHMARK_FILES`, N=2: the primary universe + an alternative benchmark),
    all net of the same commission/slippage as the strategy. The benchmark set
    is resolved relative to the strategy data file's directory, so
    `run_hypothesis_test(data_path)` takes one argument and the test exercises
    the multiple-benchmark path by default.
  - `observed` now carries `deflated_alpha_ratio`, `deflated_alpha_pvalue`, and
    `n_benchmarks`, sourced from the canonical aggregate `deflated_alpha` in
    the `out_of_sample_validation` summary (the same object the
    `_benchmark_list_alpha_correction` helper produces, already verified
    end-to-end earlier this session).
  - Docstring/methodology section updated to document the benchmark-selection
    correction.

- `tests/test_falsifiable_hypothesis_example.py`:
  - `test_falsifiable_hypothesis_example_runs_end_to_end` now asserts 5
    criteria (the 5-name set including `deflated_alpha_ratio_gt_0.90`),
    requires `n_benchmarks >= 2`, and requires `deflated_alpha_ratio` /
    `deflated_alpha_pvalue` present in `observed`.
  - The other two tests call `run_hypothesis_test(data_path)` (single-arg
    signature).

- `tests/test_walk_forward.py::test_falsifiable_hypothesis_example_imports`:
  - CRITERIA length assertion 4 -> 5 (the handoff noted this test had to be
    updated too).

No production methodology was removed; the example still runs end-to-end on
the shipped sample data and exits 0 (the verdict is NOT SUPPORTED on the sample
data — a valid scientific outcome, not a script failure).

## What was verified

- `python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`:
  3/3 passed.
- `python3 skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
  exits 0 and prints a well-formed 5-criterion verdict.
- Full quant backtesting suite: 375 passed, 0 failures (was 375; the count
  is unchanged because the new criterion was folded into the existing
  example test rather than added as a new test function).
- `python3 verify_end_to_end.py` exits 0.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_examples_coverage.py`:
  6 passed.

## What remains unresolved

None for this task.

## Approaches already tried and why

Single evidence-based extension; no failed approaches. The alternative of
keeping the example single-benchmark and only *mentioning* the DAR was
rejected because the handoff asked for the example to *exercise* the
multiple-benchmark DAR as a falsification criterion, which requires actually
passing a benchmark set through `out_of_sample_validation`.

## Next task (precise, bounded, evidence-based)

The quant backtesting library is complete and green (375 tests). A bounded
high-value candidate for the next agent: the `deflated_alpha_ratio` fallback
path (trial_alphas=None) is now unit-consistent, but the cross-sectional
estimator's `expected_max_alpha` annualization was corrected only for the
fallback path in the prior session. Verify the cross-sectional path's
`expected_max_alpha` is also annualized consistently (it should already be,
via `sr_star * strat_vol_ann * sqrt(ann_factor)`) and, if there is any
residual unit mismatch between the two estimators, add a regression test
pinning both to an independent per-period recomputation. Do not commit
anything unless explicitly asked.

(End of file)