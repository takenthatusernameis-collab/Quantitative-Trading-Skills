# Handoff — Quantitative Trading Skills Repository

  **Last updated:** 2026-10-14, after fixing the multi-benchmark CLI and adding a strict train/val/test separation invariant. Core tests: **all non-plotting tests passing**.

## Current repository state

- Default branch: `main`.
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, and validation references).
- Dependencies used by the test suite include `pandas` and `numpy`; plotting tests require Matplotlib to be available. Matplotlib is NOT installed in this environment; `test_reporting.py` has 9 pre-existing failures that are all matplotlib-dependent (heatmap figures and equity-curve PNGs) and are unrelated to any changes made this session (verified by stashing changes and re-running).

## Recent durable work (this session)

1. **Fixed the multi-benchmark CLI crash in `run_backtest.py`**: `--benchmark` uses `nargs="+"`, so `args.benchmark` is a list, but `main()` passed the whole list to `load_data(path)`, which expects a single path. This caused `TypeError: argument should be a str or an os.PathLike object ... not 'list'` and broke 3 tests (`cli_benchmark_writes_artifact_and_metrics`, `cli_total_return_benchmark_writes_provenance_and_differs_from_price`, `cli_total_return_benchmark_alpha_differs`). Fixed by looping over benchmark paths, loading each separately, and passing a list of DataFrames to `run_backtest()` when 2+ benchmarks are supplied. A single-element list still uses the single-benchmark path for backward compatibility.
2. **Added strict train/validation/test separation invariant**: New `_verify_split_separation(train_data, val_data, test_data, strict=True)` helper in `walk_forward.py` asserts the three splits are pairwise disjoint and chronologically ordered (`train_end < val_start`, `val_end < test_start`). It is called by `_split_train_val_test` and its result is recorded in `train_val_test_split["separation_check"]` for audit. 6 new tests in `test_walk_forward.py` cover the clean case and all three overlap/leak cases plus the empty-split case.
3. **Fixed two multi-benchmark bugs in the OOS CLI**: `run_out_of_sample_validation` crashed on `benchmark_provenance.to_dict()` when multiple benchmarks were supplied (provenance is a list), and on `_compute_benchmark_returns(benchmark, ...)` when `benchmark` is a list. Both are fixed; the report/tear sheet path now uses the first benchmark when multiple are supplied.
4. **Verified multi-benchmark Deflated Alpha end-to-end**: `run_backtest.py --benchmark A B` now emits `deflated_alpha` with `n_benchmarks=2` and corrected p-values; the OOS CLI prints original + corrected alpha p-values per benchmark.

## Verification status — measured this session

- `test_data_loader`: 23/23 passed.
- `test_performance`: 22/22 passed.
- `test_run_backtest`: 41/41 passed (was 38/41 before the fix).
- `test_strategy_builder`: 27/27 passed.
- `test_walk_forward`: exits 0 (full suite); 21/21 representative tests pass in isolation, including the 6 new separation invariant tests.
- `test_cpcv`: 16/16 passed.
- `test_monte_carlo`: 7/7 passed.
- `test_generate_sample_data`: 1/1 passed.
- `test_reporting`: 9 failures, all pre-existing and matplotlib-dependent (verified by stash).

## What remains unresolved

- No out-of-sample evidence of live-trading profitability is established; no production readiness claim is made.
- Benchmark model remains a simple buy-and-hold (close-to-close) with optional dividend adjustment and round-trip cost model. No split adjustment, no dynamic benchmark cost modeling, no benchmark-specific slippage/impact models.
- The PIT signal/next-return and same-bar correlation checks (threshold 0.3) are screening heuristics, not proof of look-ahead bias absence.
- Real data integration: Add example workflows with real market data (e.g., from vendor APIs or public sources) demonstrating the full pipeline from data loading through provenance, PIT validation, survivorship bias detection, benchmark comparison, and statistical significance testing. (No network access or data-vendor libraries are available in this environment, so this remains a documentation/spec task.)
- Benchmark cost model refinement: split adjustment, dynamic benchmark cost modeling, benchmark-specific slippage/impact models.

## Next high-value tasks (methodological priorities)

1. Real data integration: Add example workflows with real market data (e.g., from vendor APIs or public sources) demonstrating the full pipeline from data loading through provenance, PIT validation, survivorship bias detection, benchmark comparison, and statistical significance testing.
2. Benchmark cost model refinement: split adjustment, dynamic benchmark cost modeling, benchmark-specific slippage/impact models.
3. Multiple-testing correction for benchmark alpha is implemented (Deflated Alpha analogue) but only exercised via synthetic data; add a worked example with real data and document the interpretation.

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest test_strategy_builder test_walk_forward test_cpcv test_monte_carlo test_generate_sample_data; do
    python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

## Evidence and constraints for next agent

- The `walk_forward_analysis` function now collects per-period benchmark statistics in `period_benchmark_stats` and adds them to the summary as `benchmark_metrics_per_period` when a benchmark is provided.
- The `cpcv_analysis` function now collects per-fold benchmark statistics in `fold_benchmark_stats` and adds them to the summary as `benchmark_metrics_per_fold` when a benchmark is provided.
- The per-period benchmark statistics are computed using the same `_benchmark_stats` function, applying the benchmark expense ratio, commission, and slippage as configured.
- All performance tests pass, confirming backward compatibility and correctness of the new features when used.
- The benchmark expense ratio is applied as a periodic deduction: each period's benchmark return is reduced by `benchmark_expense_ratio / ann_factor`, simulating a constant annual fee deducted from the benchmark's net asset value (e.g., an ETF expense ratio).
- The new `benchmark_cost_is_periodic` parameter defaults to False, preserving the existing round-trip cost model. When set to True, benchmark trading costs (commission + slippage) are deducted each period as ` (benchmark_commission + benchmark_slippage) / ann_factor`.
- `_verify_split_separation` enforces that train/validation/test splits are pairwise disjoint and chronologically ordered; the result is recorded in `train_val_test_split["separation_check"]` in `out_of_sample_validation` summaries.
- `--benchmark A B` on `run_backtest.py` and the `out-of-sample` subcommand now work end-to-end and emit Deflated Alpha correction with `n_benchmarks=2`.

(End of file)