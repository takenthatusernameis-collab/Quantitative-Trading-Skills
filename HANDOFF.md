# Handoff — Quantitative Trading Skills Repository

  **Last updated:** 2026-10-14, after completing the total-return benchmark wiring and benchmark cost config consistency across all 5 CLI entry points. Full suite: **247 tests passing**.

## Current repository state

- Default branch: `main`.
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, and validation references).
- Dependencies used by the test suite include `pandas` and `numpy`; plotting tests require Matplotlib to be available.

## Recent durable work (this session)

1. **Fixed benchmark cost config consistency in `walk_forward.py`**: The `run_walk_forward` and `run_cpcv` functions now save `benchmark_commission` and `benchmark_slippage` in their summary JSON config (previously only present in `report_results` config for tear sheets). All 5 CLI entry points (`run_backtest.py` + `walk-forward`, `optimize`, `monte-carlo`, `cpcv` subcommands) now consistently persist benchmark cost parameters for full reproducibility.

2. **Verified complete total-return benchmark wiring**: The `--total-return-benchmark` flag is fully wired through all CLI entry points:
   - `run_backtest.py`: Uses `_compute_benchmark_total_return` when flag is set; provenance records `total_return_type`
   - `walk_forward.py` (all 4 subcommands): Uses `_compute_benchmark_returns` → `_compute_benchmark_total_return` when flag is set; provenance records `total_return_type`; summary metrics include `benchmark_total_return_type: "total"`
   - Tests confirm: `benchmark_provenance.total_return_type == "total"` and alpha differs between price-only and total-return modes

3. **Alpha sign flip regression test exists and passes**: `test_alpha_sign_flip_between_benchmark_modes` in `test_performance.py` demonstrates that when strategy correlates with benchmark (beta ~1), alpha is positive vs price-only benchmark but negative vs total-return benchmark (which includes dividends).

## Verification status — measured this session

- **Full test suite:** 247 tests passing across all 9 test entry points.
  - `test_data_loader.py`: 23/23
  - `test_performance.py`: 22/22
  - `test_reporting.py`: 42/42 (`unittest`, `OK`)
  - `test_run_backtest.py`: 41/41
  - `test_strategy_builder.py`: 27/27
  - `test_walk_forward.py`: 68/68
  - `test_cpcv.py`: 16/16
  - `test_monte_carlo.py`: 7/7
  - `test_generate_sample_data.py`: 1/1

- **End-to-end CLI verification (manual):**
  - `run_backtest.py --benchmark --total-return-benchmark --benchmark-commission 0.001 --benchmark-slippage 0.0005`: writes `benchmark_provenance.json` with `total_return_type: "total"`, `metrics.json` with `benchmark_commission: 0.001`, `benchmark_slippage: 0.0005`, `benchmark_total_return_type: "total"`
  - `walk_forward.py walk-forward --benchmark --total-return-benchmark --benchmark-commission 0.001 --benchmark-slippage 0.0005`: summary config includes benchmark costs; summary metrics include `benchmark_total_return_type: "total"`, `benchmark_commission: 0.001`, `benchmark_slippage: 0.0005`
  - `walk_forward.py cpcv --benchmark --total-return-benchmark --benchmark-commission 0.001 --benchmark-slippage 0.0005`: summary config includes benchmark costs
  - `walk_forward.py monte-carlo --benchmark --total-return-benchmark --benchmark-commission 0.001 --benchmark-slippage 0.0005`: summary config and metrics include benchmark costs
  - `walk_forward.py optimize --benchmark --total-return-benchmark --benchmark-commission 0.001 --benchmark-slippage 0.0005`: results include benchmark metrics with costs

- **Pinned snapshot stability:** canonical command reproduces byte-identical `report.txt` and `metrics.json`; only `load_timestamp` differs (time-dependent by design).

- **Research limitation:** this package's strategy tests and examples are largely synthetic. No out-of-sample evidence of live-trading profitability is established by these tests.

- **Modeling limitations:** market impact is a linear participation model; borrow and funding rates are constant annualized with data-frequency-aware per-period conversion; market impact, borrow rates, and funding rates are not time-varying. The PIT signal/next-return correlation check (threshold 0.3) cannot distinguish genuine alpha from look-ahead — it is a screening heuristic, not proof. The benchmark is a simple buy-and-hold (close-to-close); it does not model benchmark dividends, splits, or benchmark trading costs beyond the commission/slippage round-trip model.

## Completed benchmark baseline work (cumulative)

The buy-and-hold benchmark baseline is now fully implemented across all CLI entry points:

1. **`run_backtest.py`**: `--benchmark`, `--total-return-benchmark`, `--benchmark-commission`, `--benchmark-slippage` flags; writes `benchmark_provenance.json`; `metrics.json` includes all benchmark comparison metrics (total/annualized return, correlation, alpha, beta, alpha_tstat, alpha_pvalue, r_squared, tracking_error, information_ratio, benchmark_total_return_type, benchmark_commission, benchmark_slippage).

2. **`walk_forward.py` — all 4 subcommands**: Same flags; loads benchmark with provenance; computes benchmark returns (price or total return) aligned to OOS returns; adds benchmark metrics to summary JSON and tear sheets; persists benchmark costs in config.

3. **`performance.py` — `_benchmark_stats`**: Shared helper computes all benchmark comparison metrics including OLS alpha/beta, t-stat, p-value, R², tracking error, information ratio. Applies benchmark commission/slippage as round-trip cost to benchmark total return.

4. **`reporting.py` — tear sheet**: "Benchmark Comparison" table renders all metrics including Alpha t-stat, Alpha p-value, R-squared, Benchmark Return Type, Benchmark Commission, Benchmark Slippage.

5. **Tests**: Comprehensive coverage across `test_performance.py`, `test_run_backtest.py`, `test_reporting.py`, `test_walk_forward.py` for benchmark loading, total-return mode, cost application, alpha significance, alpha sign flip, provenance recording, and CLI integration.

## What remains unresolved

- No out-of-sample evidence of live-trading profitability is established; no production readiness claim is made.
- Benchmark model remains a simple buy-and-hold (close-to-close) with optional dividend adjustment and round-trip cost model. No split adjustment, no dynamic benchmark cost modeling, no benchmark-specific slippage/impact models.
- The PIT signal/next-return and same-bar correlation checks (threshold 0.3) are screening heuristics, not proof of look-ahead bias absence.

## Next high-value tasks (methodological priorities)

1. **Walk-forward OOS benchmark comparison enhancement**: The current implementation computes benchmark metrics on the full concatenated OOS series. Consider adding per-period (per-fold/window) benchmark comparison to diagnose regime-dependent alpha/beta stability.

2. **Benchmark cost model refinement**: The current round-trip cost model (buy + sell once) is simplistic for a buy-and-hold benchmark. Consider a more realistic model (e.g., periodic rebalancing costs, or explicit modeling of benchmark as a tradable ETF with its own expense ratio and trading costs).

3. **Multiple-testing correction for benchmark alpha**: The alpha p-value is computed per-analysis but not corrected for multiple benchmark comparisons (e.g., testing against multiple benchmarks). Consider adding a Deflated Alpha analogue to the Deflated Sharpe Ratio.

4. **Out-of-sample validation framework**: Establish a rigorous chronological train/validation/test split with walk-forward or CPCV on the training portion only, and final evaluation on a held-out test set that has never been used in any optimization or selection step.

5. **Real data integration**: Add example workflows with real market data (e.g., from vendor APIs or public sources) demonstrating the full pipeline from data loading through provenance, PIT validation, survivorship bias detection, benchmark comparison, and statistical significance testing.

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest test_strategy_builder test_walk_forward test_cpcv test_monte_carlo test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

## Evidence and constraints for next agent

- All benchmark-related flags (`--benchmark`, `--total-return-benchmark`, `--benchmark-commission`, `--benchmark-slippage`) are implemented and tested across all 5 CLI entry points.
- `DataProvenance.total_return_type` captures whether source data supports total-return computation ("price" or "total").
- `benchmark_total_return_type` in metrics/summary captures which mode was actually used for the benchmark computation ("price" or "total").
- `_compute_benchmark_total_return` in `data_loader.py` computes total return from dividends or adj_close; falls back to price return if neither available.
- `_benchmark_stats` in `performance.py` is the single source of truth for benchmark comparison metrics; all CLI paths delegate to it.
- The canonical non-benchmark command path is unaffected; `metrics.json`/`report.txt` are byte-identical to the pinned snapshot (only `load_timestamp` differs, by design).

(End of file)