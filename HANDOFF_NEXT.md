# HANDOFF_NEXT

## What changed this session

Extended the falsifiable-hypothesis worked example to exercise the
multiple-benchmark Deflated Alpha Ratio as a data-mining-control
falsification criterion, per the prior handoff:

- `examples/falsifiable_hypothesis_example.py`:
  - Added a fifth pre-registered criterion `deflated_alpha_ratio_gt_0.90`
    ("Deflated Alpha Ratio > 0.90", corrected p-value < 0.10). This is the
    benchmark-side data-mining control: testing against multiple benchmarks is
    itself a multiple-testing problem, and this criterion requires the
    benchmark alpha to survive the Deflated Alpha Ratio correction for the
    number of benchmarks tested (N).
  - Switched from a single benchmark to a benchmark set (`BENCHMARK_FILES`,
    N=2), all net of the same commission/slippage as the strategy. The set is
    resolved relative to the strategy data file's directory, so
    `run_hypothesis_test(data_path)` takes one argument and exercises the
    multiple-benchmark path by default.
  - `observed` now carries `deflated_alpha_ratio`, `deflated_alpha_pvalue`, and
    `n_benchmarks`, sourced from the canonical aggregate `deflated_alpha` in
    the `out_of_sample_validation` summary.
- `tests/test_falsifiable_hypothesis_example.py`:
  - `test_falsifiable_hypothesis_example_runs_end_to_end` now asserts 5
    criteria and requires `n_benchmarks >= 2` plus the DAR fields.
  - The other two tests call `run_hypothesis_test(data_path)`.
- `tests/test_walk_forward.py::test_falsifiable_hypothesis_example_imports`:
  CRITERIA length assertion 4 -> 5.

## What was verified

- `python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`:
  3/3 passed.
- `python3 skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
  exits 0 and prints a well-formed 5-criterion verdict (NOT SUPPORTED on the
  sample data — a valid scientific outcome).
- Full quant backtesting suite: 375 passed, 0 failures.
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

## Next task (precise, bounded)

Verify the cross-sectional `deflated_alpha_ratio` estimator's
`expected_max_alpha` is annualized consistently with the fallback path
(`sr_star * strat_vol_ann * sqrt(ann_factor)`), and if any residual unit
mismatch exists between the two estimators, add a regression test pinning both
to an independent per-period recomputation. Do not commit unless explicitly
asked.

(End of file)