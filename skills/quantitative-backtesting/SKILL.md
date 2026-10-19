---
name: quantitative-backtesting
description: This skill should be used when users want to design, implement, and validate systematic trading strategies through historical simulation. It provides workflows for data preparation, strategy development, performance evaluation, and risk analysis using Python libraries like pandas, numpy, and vectorbt.
license: Apache-2.0
metadata:
  category: development
---

# Quantitative Backtesting

This skill provides a comprehensive framework for systematic trading strategy development and validation through historical simulation. It covers the complete lifecycle from data ingestion and cleaning to strategy implementation, performance attribution, and risk analysis.

## When to Use This Skill

- Developing and testing systematic trading strategies on historical data
- Evaluating strategy performance metrics (Sharpe, Sortino, Calmar, max drawdown)
- Conducting walk-forward analysis and out-of-sample validation
- Analyzing transaction costs, slippage, and market impact
- Performing parameter optimization and robustness testing
- Generating strategy reports and tear sheets

## Core Capabilities

### 1. Data Preparation and Validation
- Load and clean OHLCV data from CSV, Parquet, or API sources
- Handle missing data, splits, dividends, and corporate actions
- Align multi-asset data to common timestamps
- Validate data quality with automated checks

### 2. Strategy Implementation
- Define entry/exit signals using technical indicators or custom logic
- Implement position sizing rules (fixed, volatility-targeted, Kelly)
- Support long/flat and long/short strategies
- Handle multiple timeframes and asset classes

### 3. Backtesting Engine
- Vectorized backtesting with vectorbt for performance
- Event-driven simulation for path-dependent strategies
- Realistic transaction cost modeling (commissions, spread, slippage)
- Portfolio-level backtesting with rebalancing logic

### 4. Performance Analysis
- Risk-adjusted returns (Sharpe, Sortino, Calmar, Omega)
- Drawdown analysis (max, average, recovery time)
- Trade-level statistics (win rate, profit factor, expectancy)
- Benchmark comparison and alpha/beta decomposition

### 5. Validation and Robustness
- Walk-forward analysis with expanding/rolling windows
- Monte Carlo simulation for return distribution
- Parameter sensitivity analysis
- Overfitting detection (combinatorially purged cross-validation)
- Multiple-testing correction via the Deflated Sharpe Ratio (Bailey & López de Prado)

### 6. Reporting
- Automated tear sheet generation
- Equity curve visualization
- Monthly/annual return heatmaps
- Trade distribution analysis
- Walk-forward / CPCV / Monte Carlo analysis rendering (via `analysis_results` parameter on `generate_tear_sheet`)

## How to Use

### Basic Usage: Simple Moving Average Crossover Backtest

```python
# User: "Run a backtest for a simple moving average crossover strategy on SPY"
```

The agent will:
1. Load or fetch SPY historical data
2. Implement SMA crossover signals (e.g., 20/50 day)
3. Run vectorized backtest with transaction costs
4. Generate performance report with key metrics

### Advanced Usage: Multi-Asset Portfolio with Walk-Forward Validation

```python
# User: "Create a multi-asset momentum strategy with walk-forward validation on a universe of 20 futures contracts"
```

The agent will:
1. Fetch/load data for all 20 futures contracts
2. Implement cross-sectional momentum ranking
3. Run walk-forward optimization with expanding window
4. Analyze parameter stability and out-of-sample performance

## Example

**User**: "Backtest a mean reversion strategy on SPY using Bollinger Bands with 2% transaction costs"

**Output**:
```
Strategy: Bollinger Bands Mean Reversion
Universe: SPY (2010-01-01 to 2024-01-01)
Parameters: Period=20, StdDev=2.0
Transaction Costs: 2 bps per trade

Performance Metrics:
- Total Return: 142.3%
- Annualized Return: 8.7%
- Sharpe Ratio: 1.34
- Sortino Ratio: 1.89
- Max Drawdown: -18.2%
- Calmar Ratio: 0.48
- Win Rate: 58.3%
- Profit Factor: 1.67
- Total Trades: 342
- Avg Trade Duration: 4.2 days

Risk Metrics:
- Volatility (annual): 12.4%
- VaR (95%): -1.8%
- CVaR (95%): -2.7%
- Skewness: -0.31
- Kurtosis: 4.2
```

## Resources

### scripts/
- `run_backtest.py` - Main entry point for running backtests with configurable parameters (supports `--n-trials` to report the Deflated Sharpe Ratio of the final backtest Sharpe; `--validate-point-in-time` / `--point-in-time-strict` to screen for look-ahead bias and data-integrity violations, aborting on violations in strict mode; `--multi-symbol` to load a multi-symbol panel, run survivorship-bias detection, and backtest a panel strategy; `--benchmark` to load a buy-and-hold baseline (e.g. SPY) and report alpha, beta, and correlation vs. the market)
- `data_loader.py` - Utilities for loading and validating market data from various sources (includes `DataProvenance` tracking, `validate_point_in_time`, `detect_survivorship_bias`, and `load_multi_symbol` for panel files with a `symbol`/`ticker` column)
- `strategy_builder.py` - Factory for creating common strategy templates (trend, mean reversion, momentum)
- `performance.py` - Comprehensive performance analytics and metric calculation.
  `calculate_metrics` computes risk-adjusted returns, drawdown statistics,
  trade-level analytics, benchmark comparison (single and multi-benchmark,
  with the Deflated Alpha Ratio multiple-testing correction applied per
  benchmark and in aggregate for 2+ benchmarks), and the Deflated Sharpe
  Ratio when `--n-trials` is reported. `generate_report` writes `metrics.json`
  and a text `report.txt` that mirrors the tear sheet, including the aggregate
  and per-benchmark Deflated Alpha sections.
- `walk_forward.py` - Walk-forward analysis, parameter optimization, CPCV, Monte Carlo simulation CLI, and Deflated Sharpe Ratio multiple-testing correction. Accepts `--multi-symbol` on every subcommand (`walk-forward`, `optimize`, `cpcv`, `monte-carlo`, `out-of-sample`): when set, loads the symbol panel via `load_multi_symbol()`, runs `detect_survivorship_bias()`, prints the survivorship report, persists `survivorship_bias.json`, and threads `survivorship_bias` + `bias_controls_engaged=True` into the summary JSON and tear sheet. When `--impact-coefficient > 0`, each analysis path also reports a market-impact-based **strategy capacity** estimate (`summary["capacity"]`, in notional) by inverting the impact model (`capacity = max_impact * ADV_notional / impact_coefficient`); the tear sheet renders it as a "Strategy Capacity (Notional)" row. Capacity is `None` when impact is disabled or ADV is not estimable, so the key is backward compatible.
- `monte_carlo.py` - Standalone Monte Carlo simulation (block bootstrap resampling, metric distributions, confidence intervals, probability of ruin). Re-exported from `walk_forward` for backward compatibility. On simulated paths where equity is wiped out (growth <= 0), the annualized return is recorded as -100% (a total loss) rather than NaN, so the metric distribution, summary statistics, and confidence intervals stay finite and interpretable; the true cumulative loss is preserved in `total_return`.
- `reporting.py` - Automated tear sheet and report generation
- `generate_sample_data.py` - Generates a sample OHLCV dataset for testing

### tests/
- `test_walk_forward.py` - Unit tests for walk-forward and parameter optimization
- `test_monte_carlo.py` - Unit tests for the standalone `monte_carlo.py` module (structure, block bootstrap, probability of ruin, short-series guard, and the `walk_forward` re-export identity). Also guards the bust-path invariant: simulated paths where equity is wiped out (growth <= 0) must not emit NaN in `annualized_return`, or the whole distribution, summary mean/std, and confidence intervals collapse to NaN. Use an explicit `seed` when reproducing bust-path counts — without one the simulation falls back to the global numpy RNG.
- `test_run_backtest.py` - Unit tests for the run_backtest CLI entry point and argument parsing
- `test_strategy_builder.py` - Unit tests for the strategy factory and registry
- `test_data_loader.py` - Unit tests for data loading and validation
- `test_performance.py` - Unit tests for performance metric calculation and annualization
- `test_reporting.py` - Unit tests for report generation, file output, and tear sheet generation

### references/
- `data_schema.md` - Expected data formats and column specifications
- `strategy_templates.md` - Pre-built strategy patterns and customization guide
- `metrics_definitions.md` - Mathematical definitions of all performance metrics
- `cost_models.md` - Transaction cost and slippage modeling approaches
- `validation_methods.md` - Walk-forward, Monte Carlo, and CPCV methodologies

### assets/
- `config_template.yaml` - Default configuration for backtest parameters
- `example_data/sample_ohlcv.csv` - Sample OHLCV data for testing

## Tips

- Always start with in-sample development, then validate out-of-sample
- Use walk-forward analysis instead of single train/test splits
- Account for transaction costs from the beginning - they significantly impact net returns
- Test parameter stability across different market regimes
- Beware of look-ahead bias: ensure signals only use data available at decision time
- Correct for multiple testing: a grid search over many parameter combinations inflates in-sample Sharpe; compute the Deflated Sharpe Ratio before trusting a Sharpe estimate. Use `--deflate` for walk-forward/optimization/CPCV, or pass `--n-trials` to `run_backtest.py` or the `monte-carlo` subcommand to deflate a single backtest's final Sharpe by the number of development trials (the `monte-carlo` path also uses the optimization record's trial Sharpes for the cross-sectional estimator)
- **DSR methodology**: the Deflated Sharpe Ratio's formula, its degenerate (zero-variance) contract, its trial-counting basis per analysis path, and the cross-path parity invariant (the reported DSR p-value must not depend on which analysis path reported it) are documented in `references/validation_methods.md` under "Deflated Sharpe Ratio (Multiple-Testing Correction)" and "DSR Parity Invariant (Cross-Path Consistency)". The parity invariant and the degenerate contract are also executable-guarded in `tests/test_walk_forward.py`; a regression that breaks either fails those tests even while the artifact still looks well-formed.
- Consider regime-dependent performance (bull/bear/sideways markets)
- Document all assumptions and data sources for reproducibility
- Run `--validate-point-in-time` on every backtest to screen for temporal-order violations, duplicate timestamps, and signal/next-return correlation (a look-ahead indicator); add `--point-in-time-strict` to make violations fail the run
- The definitive look-ahead test in `validate_point_in_time` is the **next-period correlation** between signal changes and `close[t+1] - close[t]`: a signal at time `t` must not predict the return at `t+1`, because no future information is available at time `t`. The contemporaneous (same-bar) correlation between signal changes and `close[t] - close[t-1]` is NOT used as a violation: a signal generated at time `t` is legitimately allowed to use `close[t]`, and `close[t]` is a component of the same-bar return, so any `close[t]`-based strategy (SMA crossover, mean reversion, Donchian) shows non-trivial same-bar correlation by construction. Only the next-period test can distinguish a legitimate `close[t]`-based signal from a genuinely forward-looking one.
- The out-of-sample validation framework (`walk_forward.py out-of-sample`) enforces a **strict chronological train/validation/test split** via `_verify_split_separation`: the three splits must be pairwise disjoint and ordered (`train_end < val_start`, `val_end < test_start`), and the check result is recorded in `train_val_test_split.separation_check`. A leak here would silently produce an in-sample-optimistic result indistinguishable from a genuine out-of-sample one, so the check is a correctness guard, not a cosmetic one.
- The `--selection-criterion` flag (`best_oos_sharpe` default, or `most_stable` / `best_avg_sharpe`) chooses the final parameters from the validation phase. **Only `most_stable` selects on in-sample behavior** (how often each combo won the grid search); `best_oos_sharpe` and `best_avg_sharpe` select on each period/fold's **out-of-sample** test Sharpe (`test_sharpe`), never on `best_sharpe`, which is the in-sample training Sharpe the grid search ranked by. Selecting on `best_sharpe` would pick the combo that overfit its training window — the exact selection bias this framework exists to avoid. Each walk-forward period and CPCV fold now carries a `test_sharpe` key (OOS test Sharpe of the selected combo; `None` on degenerate/empty test windows), and the OOS summary carries `selected_params_avg_test_sharpe` (mean OOS test Sharpe of the selected combo across the periods/folds that chose it).
- For multi-symbol universes, run `--multi-symbol` to detect survivorship bias (late entries, early exits, insufficient history, data gaps) and review `survivorship_bias.json` before trusting panel results. The flag is accepted by every walk-forward subcommand (`walk-forward`, `optimize`, `cpcv`, `monte-carlo`, `out-of-sample`) as well as `run_backtest`; when set, the survivorship-bias report is persisted as `survivorship_bias.json` in the output directory and threaded into the summary JSON (`survivorship_bias`, `bias_controls_engaged=True`) so panel runs are auditable on the same file name across all CLIs.
- The CLI writes `data_provenance.json` (source path, checksum, filters, transformations, validation outcome) next to the results so every backtest is reproducible and auditable

## Common Use Cases

- Trend following strategy development on futures
- Mean reversion on equity indices or ETFs
- Statistical arbitrage pairs trading
- Factor-based long/short equity portfolios
- Cryptocurrency trading strategy validation
- Options strategy backtesting (with appropriate data)

## References

- **Inspired by**: Quantitative trading frameworks from QuantConnect, Zipline, and vectorbt
- **Key Libraries**: pandas, numpy, vectorbt, empyrical, pyfolio
- **Methodology**: Based on Marcos López de Prado's "Advances in Financial Machine Learning"

## Test Coverage

This skill bundles a standard-library unit-test suite under `tests/` (pandas/numpy
are the only third-party imports, required by the scripts under test). Run each
file directly with Python:

```bash
python3 skills/quantitative-backtesting/tests/test_data_loader.py
python3 skills/quantitative-backtesting/tests/test_performance.py
python3 skills/quantitative-backtesting/tests/test_reporting.py
python3 skills/quantitative-backtesting/tests/test_run_backtest.py
python3 skills/quantitative-backtesting/tests/test_strategy_builder.py
python3 skills/quantitative-backtesting/tests/test_walk_forward.py
python3 skills/quantitative-backtesting/tests/test_cpcv.py
python3 skills/quantitative-backtesting/tests/test_monte_carlo.py
python3 skills/quantitative-backtesting/tests/test_generate_sample_data.py
```

- `test_data_loader.py` - CSV/Parquet loading, column/date handling, symbol
  filtering, and `validate_data` quality checks (missing columns, non-positive
  prices, high < low, duplicate dates, short series). Also covers
  `load_multi_symbol` provenance completeness: per-symbol `DataProvenance`
  carries a checksum and date range, and the expected cross-symbol duplicate
  timestamps of panel files do not trigger a spurious aggregate validation
  warning (per-symbol validation is authoritative).
- `test_performance.py` - `calculate_metrics` and `_annualization_factor`:
  total/annualized return, volatility, Sharpe/Sortino/Calmar, drawdown, VaR/CVaR,
  skew/kurtosis, and **trade-level metrics**. The trade suite is a regression
  guard for a defect where `avg_win`/`avg_loss`/`avg_trade_duration` were
  computed from `pnl` (currency) and then formatted as percent, producing
  impossible values such as "Avg Win: 577.46%". They are now derived from
  per-trade `return` fractions, `avg_trade_duration` is calendar days, and
  `profit_factor` follows the documented `sum(pnl>0)/abs(sum(pnl<0))` formula.
- `test_reporting.py` - `generate_report` file/header/trade-section output and
  `generate_tear_sheet` HTML + JSON summary generation (matplotlib optional).
  Covers capacity surfacing (row rendered + JSON key present when capacity is
  in the walk-forward/CPCV summary; row and key omitted when absent).
  Also covers the **multiple-testing correction** reporting: `generate_report`
  prints a "Multiple-Testing Correction" section and `generate_tear_sheet`
  renders a table plus a top-level `deflated_sharpe` key in the JSON summary
  when a `deflated_sharpe` dict is present, and both omit it when absent.
  Covers **per-benchmark Deflated Alpha reporting**: for the multi-benchmark
  `run_backtest` CLI path, `generate_report` renders a "Per-Benchmark
  Comparison" table (alpha, beta, correlation, corrected alpha p-value,
  deflated alpha, expected max alpha per benchmark) mirroring the tear sheet,
  `generate_tear_sheet` renders a "Per-Benchmark Comparison" table and surfaces
  a top-level `benchmark_metrics` list in the JSON summary, and both omit the
  per-benchmark detail when fewer than 2 benchmarks are present (single-
  benchmark runs keep the non-prefixed `alpha` / `beta` /
  `correlation_with_benchmark` keys). Covers **parameter sensitivity heatmap**: `generate_parameter_heatmap`
  produces a 2D heatmap figure for Sharpe/DSR/total-return across a two-parameter
  grid, handles degenerate DSR dicts (z_score=None) as NaN, and integrates into
  `generate_tear_sheet` when `parameter_optimization` results with exactly two
  varying parameters are available. Uses the stdlib `unittest` framework rather
  than the custom runner. Also covers **walk-forward / CPCV / Monte Carlo
  analysis rendering**: when `analysis_results` dict is passed to
  `generate_tear_sheet` with `walk_forward`, `cpcv`, and/or `monte_carlo` keys,
  the corresponding HTML sections (best params per period/fold, parameter
  stability, overfitting risk, DSR tables, confidence intervals, metric
  distributions, probability of ruin) and JSON summary entries are generated.
  A Monte Carlo equity curve fan chart (`monte_carlo_equity_curve.png`) is
  produced when `simulated_equity_curves` and matplotlib are available.
- `test_run_backtest.py` - `run_backtest` end-to-end on synthetic data, the
  `signals_active` flat-strategy guard, `parse_args` CLI behavior, and **trade
  extraction across long/short flips**. Regression coverage for a defect where
  a direct `+1 -> -1` position flip (used by Bollinger Bands, Donchian Breakout
  and RSI mean reversion) was never closed out: the old extractor only fired on
  a return to zero, so one leg of the round turn leaked and the short leg was
  never recorded. The fix treats every position change as a trade boundary,
  closes the open leg and opens the new one at the same bar, and signs each
  PnL by the direction it was taken (long follows price, short moves opposite).
  Also covers **end-of-sample mark-to-market**: a position still open when the
  data ends (common for long-lookback momentum strategies) is closed at the
  last bar and flagged `closed_at_end`, so the trade ledger reconciles with
  the equity curve instead of silently dropping the leg. Finally, a
  parameterized audit runs every registered strategy and asserts each trade
  has finite `pnl`/`return`, `entry_date < exit_date`, and a `pnl` sign
  consistent with the position direction at entry (recomputed independently
  from the strategy's own shifted signals). Also covers **multi-asset
  panel integration**: `run_backtest` accepts dict-of-DataFrames and
  MultiIndex-column panel data for `CrossSectionalMomentum` and
  `DualMomentumStrategy`, and the trade ledger is validated (non-empty,
  well-formed) for both formats. The extractor iterates the position
  series, not `data`, because `len(data)` is the number of symbols (not
  bars) for a dict and `data.index` does not exist on dicts. Also covers
  **Deflated Sharpe Ratio surfacing in the main backtest path**:
  `--n-trials` threads the number of development trials through the
  results config, `calculate_metrics` deflates the final backtest
  Sharpe by it (importing `deflated_sharpe_ratio` from `walk_forward`
  lazily) into a `deflated_sharpe` metrics key, and   the surfaced DSR
  equals a direct `deflated_sharpe_ratio` call; without `--n-trials`
  no `deflated_sharpe` key is emitted (backward compatible).
  `parse_args` accepts `--n-trials` (default `None`).
  Also covers the **provenance / point-in-time / survivorship CLI
  integration**: `run_backtest` serializes the load-time
  `DataProvenance` (single and per-symbol panel forms) into
  `results["data_provenance"]` and omits the key when none was
  captured; `--validate-point-in-time` records the PIT outcome in
  `results["point_in_time_validation"]` (clean data passes, duplicate
  timestamps violate, dict panels are validated per symbol, non-strict
  runs still complete); `_handle_point_in_time_results` aborts only on
  violations in strict mode; `parse_args` accepts
  `--validate-point-in-time`, `--point-in-time-strict`, `--multi-symbol`
  (all default off). Two end-to-end `main()` tests verify the CLI
  writes `data_provenance.json` (source path, checksum, validation
  outcome) and that `--multi-symbol` writes `survivorship_bias.json`
  (surviving/entered/exited symbols, bias score) plus a per-symbol
  provenance artifact with checksums, while the panel backtest runs on
  the overlapping window.
- `test_strategy_builder.py` - strategy registry, `build_strategy`, defaults,
  binary long/flat signal generation with real crossovers, and multi-asset
  panel signal generation for `CrossSectionalMomentum` and
  `DualMomentumStrategy` (dict and MultiIndex formats, single-asset
  fallback warnings, quantile/ranking semantics). Covers `MeanReversionZScore`
  pairs trading on dict and MultiIndex panel data (two-asset entry/exit),
  three-asset rejection, single-asset fallback warning, and the
  `ols_hedge` spread method (rolling OLS hedge-ratio recovery on a known
  cointegrated pair, spread stationarity, backward-compatible defaults).
    - `test_walk_forward.py` - walk-forward windowing, parameter grid parsing,
      train/test separation, Monte Carlo simulation, **Deflated Sharpe Ratio
      multiple-testing correction** (`deflated_sharpe_ratio`, `apply_deflation`
      on `parameter_optimization` and `walk_forward_analysis`, CLI `--deflate`),
      the **`monte-carlo` CLI's `--n-trials` deflation** (the base backtest
      Sharpe is deflated via `calculate_metrics`, the optimization record's
      trial Sharpes give the cross-sectional `SR*` estimator, the surfaced DSR
      equals a direct `deflated_sharpe_ratio` call, and without `--n-trials` no
      `deflated_sharpe` key is emitted), **degenerate-window DSR coverage**
      (the aggregate DSR emits the conservative degenerate dict on constant
      OOS returns; the per-period/per-fold DSR — an in-sample deflation on the
      period's *training* returns — is reachable and non-degenerate on constant
      *test* windows and equals an independent grid-search recomputation, while
      a flat *training* window skips the period with no per-period DSR;
      `parameter_optimization(apply_deflation=True)` emits the degenerate dict
      for every ranked combo on constant returns, where zero-variance combos
      are ranked at Sharpe 0 rather than skipped; the `run_parameter_optimization --deflate` CLI
      writes the degenerate DSR dicts into `parameter_optimization.json` on constant returns), and
      **cost-coefficient sweeps** across all five validation modes (walk-forward,
      optimize, cpcv, monte-carlo, out-of-sample) for `--impact-coefficients`,
      `--borrow-costs`, `--funding-costs`, `--commissions`, and `--slippages`.
      Each sweep writes a `<mode>_<coefficient>_sweep.json` artifact whose
      per-row metrics record every cost parameter actually applied (so a sweep
      that varies commission leaves impact/borrow/funding at their single-run
      values), and returns degrade monotonically as the swept cost rises.
      Commission/slippage sweep coverage includes
      `test_cli_walk_forward_commission_sweep`,
      `test_cli_walk_forward_slippage_sweep`,
      `test_cli_optimize_commission_sweep`,
      `test_cli_optimize_slippage_sweep`,
      `test_cli_cpcv_commission_sweep`,
      `test_cli_cpcv_slippage_sweep`,
      `test_cli_monte_carlo_commission_sweep`,
      `test_cli_monte_carlo_slippage_sweep`,
      `test_cli_out_of_sample_commission_sweep`, and
      `test_cli_out_of_sample_slippage_sweep`, and
      multi-asset panel (dict and
      MultiIndex) walk-forward and Monte Carlo integration with
      `CrossSectionalMomentum` and `DualMomentumStrategy`.
      **`--multi-symbol` artifact parity across all five walk-forward
      subcommands**: `test_cli_multi_symbol_out_of_sample_*` (existing),
      plus `test_cli_multi_symbol_walk_forward_writes_survivorship_artifact`,
      `test_cli_multi_symbol_cpcv_writes_survivorship_artifact`, and
      `test_cli_multi_symbol_optimize_writes_survivorship_artifact`, which
      assert each subcommand persists `survivorship_bias.json` and records
      `multi_symbol=True` in its summary config; and
      `test_cli_walk_forward_no_benchmark_does_not_crash`, a regression for an
      `UnboundLocalError` on `benchmark_returns_list` in the benchmark-less
      walk-forward report path.
  - `test_cpcv.py` - CPCV fold structure, purge/embargo behavior, parameter
    stability calculation, summary metrics, **Deflated Sharpe Ratio
    correction** (`apply_deflation` on `cpcv_analysis`), CLI integration,
    and multi-asset panel (dict and MultiIndex) CPCV integration with
    `CrossSectionalMomentum` and `DualMomentumStrategy`.
  - `test_generate_sample_data.py` - Sample data generation creates valid OHLCV
  CSV with expected shape and constraints.

The canonical rendered outputs in `test_output/` are regenerated from
`assets/example_data/sample_ohlcv.csv` via
`python3 skills/quantitative-backtesting/scripts/run_backtest.py --data skills/quantitative-backtesting/assets/example_data/sample_ohlcv.csv --params '{"fast_period": 10, "slow_period": 30}' --output skills/quantitative-backtesting/test_output`
(the pinned snapshot uses `fast_period=10`/`slow_period=30`, not the
20/50 defaults) and serve as a pinned regression snapshot; they are not
proof of profitability.

## End-of-Sample Trade Closes

A position still open when the data ends is closed at the last bar's close
and flagged `closed_at_end: True` in the trade dict (the exit is forced by
the sample boundary, not by a signal). This keeps the trade ledger
reconciling with the equity curve instead of silently dropping the leg.

The flag is surfaced in consumers so a backtest whose ledger is largely
end-of-sample artifact is not mistaken for genuine entry/exit activity:

- `performance.calculate_metrics` exposes `trades_closed_at_end` (count) and
  `pct_trades_closed_at_end` (fraction of the ledger).
- `performance.generate_report` prints an "End-of-Sample Closes" section when
  present, and omits it when there are no forced closes.
- `reporting.generate_tear_sheet` renders both keys in the Trade Analytics
  table.
- Definitions are in `references/metrics_definitions.md` under
  "Trades Closed at End of Sample".