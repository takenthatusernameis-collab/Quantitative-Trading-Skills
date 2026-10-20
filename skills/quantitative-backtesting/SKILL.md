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
- Test resolution (minimum detectable effect): how large an effect the held-out sample could have detected at all (reported by the walk-forward, CPCV and out-of-sample paths as `summary["test_resolution"]`, by the primary backtest entry point as `metrics["test_resolution"]`, and printed next to the Deflated Sharpe line)

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
- `run_backtest.py` - Main entry point for running backtests with configurable parameters (supports `--n-trials` to report the Deflated Sharpe Ratio of the final backtest Sharpe; `--validate-point-in-time` / `--point-in-time-strict` to screen for look-ahead bias and data-integrity violations, aborting on violations in strict mode; `--multi-symbol` to load a multi-symbol panel, run survivorship-bias detection, and backtest a panel strategy; `--benchmark` to load a buy-and-hold baseline (e.g. SPY) and report alpha, beta, and correlation vs. the market). When `--impact-coefficient > 0`, it also reports a market-impact-based **strategy capacity** estimate (`results["capacity"]`, in notional, mirrored into `metrics["capacity"]`) by inverting the impact model via `estimate_capacity`; capacity is `None` when impact is disabled or ADV is not estimable, so the key is backward compatible. A **panel** is priced with the same shared convention as the walk-forward / CPCV / out-of-sample paths (see `utils.py`): the portfolio return is the mean of the per-asset returns, the market-impact cost is computed per asset on the equal-weighted basket convention, and the capacity estimate is the least-liquid-binds basket capacity — so panel results from this CLI and from `walk_forward.py` are directly comparable. A panel run also surfaces a **panel book diagnostic** (`results["book_diagnostic"]`, mirrored into `metrics["book_diagnostic"]`, printed by the CLI and rendered in the tear sheet): the per-asset book the strategy actually holds against the engine's net-exposure pricing of the panel. It is a measurement only — no return, cost, impact or capacity number changes — and it is `None` for a single asset or a strategy that does not expose a book. When the engine refuses to backtest a strategy because its net exposure is flat, the error now states that the strategy does hold a book (gross book, periods with a book) so the net-exposure convention is not mistaken for a flat strategy. `--panel-pricing {net-exposure,book}` selects how a panel is priced **and costed**: `net-exposure` (the default, and the convention every published number was produced under) prices `net_exposure x mean(asset returns)` and charges the costs on the net exposure; `book` prices the true per-asset book return `sum_i w_i r_i` of the strategy's target weights, makes the "does this strategy take a position?" test book-aware (so a market-neutral book is backtested instead of being rejected), and charges the costs on the book itself (gross turnover, short legs, gross exposure, per-asset market impact). The mode is recorded in `results["panel_pricing"]`, `results["config"]["panel_pricing"]` / `["panel_pricing_effective"]`, the CLI stdout and the tear sheet ("Panel Pricing"). The **execution warmup** the run applied is recorded the same way: `results["config"]["warmup_convention"]` and `results["config"]["execution_warmup_bars"]`, plus a CLI line next to the pricing mode, so the number of leading bars that are not tradable is never a matter of guesswork (see `references/validation_methods.md`, "Recording the Warmup Convention").
- `utils.py` - Shared helpers used by every backtest path: `_annualization_factor`, plus the two shared market-model definitions that keep `run_backtest.py` and `walk_forward.py` in agreement: `build_market_model` (normalizes a single asset, a MultiIndex panel and a dict panel into one representation; a panel's return is the mean of the per-asset returns) and `market_impact_cost` (per-asset notional `|position_change| * equity / n_assets` measured against each asset's own ADV, with the portfolio cost = the equal-weighted mean of the per-asset impacts). It also owns the **panel book diagnostic**: `strategy_target_weights` (reads a strategy's optional per-asset book, `None` when it has none), `compute_book_diagnostic` (gross book, book net exposure vs the priced net exposure, book turnover vs the charged turnover, the cost basis, the return gap between the engine's pricing and the book return `sum_i w_i r_i`, and the market-impact participation measurement) and `aggregate_book_diagnostics` (the per-window aggregate). The **market-impact participation measurement** lives here too: `impact_participation_dilution` (the panel mean the model charges vs the mean over the names that actually traded vs the dollar-consistent notional-weighted aggregation, with the exact `panel == (k / n) * traded_only` identity) and `format_impact_dilution_lines` (the shared CLI block). The **panel pricing modes** live here too: `resolve_panel_pricing` (validates `net-exposure` / `book`), `held_book_weights` (the book actually held: the target weights lagged by `1 + latency` and scaled by the fill rate; a `nan` warmup reproduces the walk-forward path's "first defined position is entered for free" convention), `book_return_from_held` / `book_return_series` (the true book return `sum_i w_i r_i`), `book_is_active` (the book-aware "does this strategy take a position?" test: a market-neutral book has a positive gross exposure), and the **book cost basis**: `book_gross_turnover` (`sum_i |dw_i|`), `book_cost_components` (transaction on the gross turnover, borrow on the short legs, funding on the gross exposure), `book_market_impact_cost` (per-asset notional `|dw_i| * equity` against that asset's own ADV, portfolio cost = the equal-weighted mean) and `book_trade_ledger` (one round trip per asset and direction, priced at the asset's own close, with the sign carried by the weight). The **execution warmup conventions** live here too: `EXECUTION_WARMUP_BARS` / `RUN_BACKTEST_WARMUP_BARS`, the two convention names (`WARMUP_CONVENTION_WALK_FORWARD`, `WARMUP_CONVENTION_RUN_BACKTEST`) and `execution_warmup_metadata(convention, latency)`, the single definition of how many leading bars each convention removes.
- `data_loader.py` - Utilities for loading and validating market data from various sources (includes `DataProvenance` tracking, `validate_point_in_time`, `detect_survivorship_bias`, and `load_multi_symbol` for panel files with a `symbol`/`ticker` column)
- `strategy_builder.py` - Factory for creating common strategy templates (trend, mean reversion, momentum). `StrategyBase.generate_target_weights(data)` is the optional per-asset **book accessor**: it returns a weight frame whose net exposure matches the strategy's scalar signal, or `None` (the default) when the strategy does not model a book. `CrossSectionalMomentum` (long `+1/n_assets` per name, short `-1/n_assets` per name) and `DualMomentumStrategy` (`1/n_selected` per selected name) implement it, so the engine can measure the book it prices.
- `performance.py` - Comprehensive performance analytics and metric calculation.
  `calculate_metrics` computes risk-adjusted returns, drawdown statistics,
  trade-level analytics, benchmark comparison (single and multi-benchmark,
  with the Deflated Alpha Ratio multiple-testing correction applied per
  benchmark and in aggregate for 2+ benchmarks), and the Deflated Sharpe
  Ratio when `--n-trials` is reported. `generate_report` writes `metrics.json`
  and a text `report.txt` that mirrors the tear sheet, including the aggregate
  and per-benchmark Deflated Alpha sections.
- `walk_forward.py` - Walk-forward analysis, parameter optimization, CPCV, Monte Carlo simulation CLI, and Deflated Sharpe Ratio multiple-testing correction. Accepts `--multi-symbol` on every subcommand (`walk-forward`, `optimize`, `cpcv`, `monte-carlo`, `out-of-sample`): when set, loads the symbol panel via `load_multi_symbol()`, runs `detect_survivorship_bias()`, prints the survivorship report, persists `survivorship_bias.json`, and threads `survivorship_bias` + `bias_controls_engaged=True` into the summary JSON and tear sheet. When `--impact-coefficient > 0`, each analysis path also reports a market-impact-based **strategy capacity** estimate (`summary["capacity"]`, in notional) by inverting the impact model (`capacity = max_impact * ADV_notional / impact_coefficient`); the tear sheet renders it as a "Strategy Capacity (Notional)" row. Capacity is `None` when impact is disabled or ADV is not estimable, so the key is backward compatible. Capacity is also reported **per regime**: `period["capacity"]` (walk-forward), `fold["capacity"]` (CPCV), and `validation_performance["capacity"]` / `test_performance["capacity"]` (out-of-sample), so capacity degradation across folds/periods/windows is observable; the CLI artifacts persist them as `capacity_per_period` / `capacity_per_fold`, and the tear sheet renders a "Capacity (Notional)" column in the per-period and per-fold tables. Because that reading only sees the *last* bar of a window, each regime also carries a **capacity trend** (`period["capacity_trend"]`, `fold["capacity_trend"]`, `validation_performance["capacity_trend"]`, `test_performance["capacity_trend"]`, `summary["capacity_trend"]`): the distribution of the per-period capacity readings inside the window (`min_capacity`, `median_capacity`, `max_capacity`, `last_capacity`, and the `min_to_median_ratio` / `last_to_median_ratio` degradation ratios). The walk-forward and CPCV summaries also report `summary["oos_min_capacity"]`, the worst capacity seen in any out-of-sample window. The trend is `None` when impact is disabled or ADV is not estimable, and it never changes the existing `estimated_capacity` number. For a multi-asset panel the basket is treated as equal-weighted, so the least liquid constituent binds the portfolio capacity (`capacity = n_assets * max_impact * min_i(ADV_notional_i) / impact_coefficient`). Every analysis path also reports a **panel book diagnostic** (`period["book_diagnostic"]`, `fold["book_diagnostic"]`, `validation_performance["book_diagnostic"]` / `test_performance["book_diagnostic"]`, `summary["book_diagnostic"]`): the per-asset book the strategy actually holds (gross book, book net exposure vs the priced net exposure, book turnover vs the turnover the cost model charges) against the framework's net-exposure pricing of a panel, plus the return gap between the engine's P&L and the book P&L. It is a measurement only -- no return, cost, impact or capacity number changes -- and it is `None` for a single asset or a strategy that does not expose a book. See `references/cost_models.md`, "Panel book diagnostic (measurement only)". `--panel-pricing {net-exposure,book}` is accepted on every subcommand and selects how a panel is priced **and costed**: `net-exposure` (the default) prices `net_exposure x mean(asset returns)` and charges the costs on the net exposure, `book` prices the true per-asset book return `sum_i w_i r_i`, makes the grid search's "takes a position?" test book-aware (a market-neutral book is traded, not skipped) and charges the costs on the book (gross turnover, short legs, gross exposure, per-asset impact). The mode is recorded in `summary["panel_pricing"]`, the CLI stdout and the tear sheet ("Panel Pricing"). See `references/cost_models.md`, "Panel pricing modes (`--panel-pricing`)". Market impact on a **multi-asset panel** is modeled per asset on the same equal-weighted convention (`|position_change| * equity / n_assets` traded in each asset, each asset measured against its own ADV, portfolio cost = mean of the per-asset impacts), which keeps the dict and MultiIndex panel formats identical; previously the panel path produced an **empty** return series, which silently dropped every grid configuration and made panel runs with impact report "no signal" (regression-guarded in `tests/test_walk_forward.py`).
- `monte_carlo.py` - Standalone Monte Carlo simulation (block bootstrap resampling, metric distributions, confidence intervals, probability of ruin). Re-exported from `walk_forward` for backward compatibility. On simulated paths where equity is wiped out (growth <= 0), the annualized return is recorded as -100% (a total loss) rather than NaN, so the metric distribution, summary statistics, and confidence intervals stay finite and interpretable; the true cumulative loss is preserved in `total_return`.
- `reporting.py` - Automated tear sheet and report generation
- `generate_sample_data.py` - Generates a sample OHLCV dataset for testing
- `generate_positive_control_data.py` - Generates the **synthetic positive
  control** for the falsifiable-hypothesis machinery: a series built by a
  known formula with a known injected effect (alternating trend regimes, one
  rising and one falling per 126 bars, +/-0.4% per-bar log drift, 1% per-bar
  noise, 5040 bars) plus a **no-effect control** built from the identical
  draws with the drift removed. It is a check on the test machinery, not
  evidence about any security: the file names (`sample_ohlcv.csv`,
  `sample_benchmark.csv`) are the ones the worked example's `BENCHMARK_FILES`
  list resolves, and the fixture is written into a directory of the caller's
  choosing (`--out`). See `references/validation_methods.md`, "A positive
  control: the machinery can say yes".
- `measure_resolution_vs_sample_size.py` - Measures the **test resolution as
  a function of sample size** at the worked example's configuration: it
  rebuilds the synthetic control fixture at each rung of a sample-size ladder
  and reports the framework's own `summary["test_resolution"]` (the smallest
  annualized Sharpe / alpha the pre-registered significance criteria could
  have confirmed at that sample size) plus the deflation benchmark `SR*`
  (`expected_max_sharpe`) the resolution converges to. It calls
  `walk_forward.out_of_sample_validation` and
  `walk_forward._build_test_resolution`; it re-derives nothing and changes
  no threshold, bound, criterion or verdict. `--data FILE` measures the same
  curve on the first N bars of a real history. The measured answer: the
  resolution *improves* with the sample and crosses below the 2.0
  plausibility bound at a few thousand daily bars, so the shipped sample's
  verdict is a statement about its 504 bars rather than about the criteria.
  See `references/validation_methods.md`, "How much data does criterion 2
  need?".

### tests/
- `test_walk_forward.py` - Unit tests for walk-forward and parameter optimization
- `test_monte_carlo.py` - Unit tests for the standalone `monte_carlo.py` module (structure, block bootstrap, probability of ruin, short-series guard, and the `walk_forward` re-export identity). Also guards the bust-path invariant: simulated paths where equity is wiped out (growth <= 0) must not emit NaN in `annualized_return`, or the whole distribution, summary mean/std, and confidence intervals collapse to NaN. Use an explicit `seed` when reproducing bust-path counts — without one the simulation falls back to the global numpy RNG.
- `test_run_backtest.py` - Unit tests for the run_backtest CLI entry point and argument parsing
- `test_strategy_builder.py` - Unit tests for the strategy factory and registry
- `test_data_loader.py` - Unit tests for data loading and validation
- `test_performance.py` - Unit tests for performance metric calculation and annualization
- `test_reporting.py` - Unit tests for report generation, file output, and tear sheet generation
- `test_execution_warmup.py` - Unit tests for the execution-warmup metadata: every
  result artifact records the warmup convention it applied
  (`warmup_convention`, `execution_warmup_bars`) and the recorded count is
  checked against the number of bars that are actually missing from the
  reported return series, so the metadata cannot drift away from the
  behaviour it describes. See `references/validation_methods.md`,
  "Recording the Warmup Convention".
- `test_out_of_sample_window.py` - Unit tests for the out-of-sample
  validation window and its diagnosis: the walk-forward window is shortened
  to the largest value that still yields a period when the requested one
  does not fit the training split (and left untouched when it does), the
  adaptation is recorded in `summary["walk_forward_window"]`, a validation
  phase that cannot select reports its **cause**
  (`summary["no_selection_diagnosis"]`) instead of one generic sentence,
  the CLI writes that diagnosis to `out_of_sample_summary.json` and exits
  non-zero, and an inert parameter grid is reported as the null experiment
  it is (`summary["inert_grid_params"]`). See
  `references/validation_methods.md`, "The Walk-Forward Window Inside the
  Training Split".
- `test_inert_param_grid.py` - Unit tests for inert parameter grids on every
  analysis path: the measurement itself (a grid key the strategy does not
  read is flagged, a live key is not), the recording of the finding in the
  walk-forward, CPCV and out-of-sample summaries and in
  `parameter_optimization_inert_grid.json`, the single CLI warning printed
  next to the ranking / selection it qualifies, and the invariant that the
  measurement changes no return, cost, impact, capacity or selection
  number. The key that matters only in *combination* with another key is
  never accused (the demonstration strategy whose `threshold` is read only
  in the `mode == "b"` branch), the shipped strategies keep the verdicts
  they had before the check became exhaustive, and a bounded check says so
  in the message. See `references/validation_methods.md`, "Inert Parameter
  Grids".
- `test_no_selection_diagnosis.py` - Unit tests for the "no parameter could
  be selected" diagnosis on the standalone paths: the standalone CPCV and
  walk-forward analyses record `summary["no_selection_diagnosis"]` (same
  `{cause, message, details}` shape as the out-of-sample path) when no
  fold / period could select a parameter, the message names the window
  length and the effective out-of-sample fraction
  (`test_size / n_splits`), the remedy names flags the path's own
  subcommand accepts, a run that *does* select a parameter carries no
  diagnosis, the overfitting-risk verdict is `null` ("not applicable") when
  nothing could be selected and unchanged when it could, and the diagnosis
  changes no number. See `references/validation_methods.md`, "When No
  Parameter Can Be Selected".
- `test_test_resolution.py` - Unit tests for the **test resolution** (minimum
  detectable effect) reporting: the walk-forward, CPCV and out-of-sample paths
  each attach `summary["test_resolution"]`, the primary backtest entry point
  attaches `metrics["test_resolution"]` built on the very return series its
  Deflated Sharpe Ratio was computed on, the block agrees with the
  `minimum_detectable_sharpe` / `minimum_detectable_alpha` helpers it is built
  from, a statistic whose return series does not match is reported as "not
  resolvable" with a reason instead of a number, a threshold beyond the
  stated plausibility bound is flagged, the block mutates nothing and carries
  no verdict, a run without a significance test says so, the CLI prints it
  next to the Deflated Sharpe line, and the aggregate Deflated Alpha Ratio
  the alpha resolution belongs to is printed next to that resolution. The
  **cost sweeps** are covered too: every sweep point carries the resolution of
  its own statistics, the sweep table prints that threshold beside the swept
  Sharpe and flags the points the sample cannot distinguish from zero (on
  magnitudes, so a large negative Sharpe is not flagged), a sweep without a
  significance test says so, and a sweep point reports exactly what the single
  run at the same coefficient reports. See
  `references/validation_methods.md`, "Test Resolution (Minimum Detectable
  Effect)".
- `test_falsifiable_hypothesis_example.py` - Unit tests for the worked
  example's pre-registered falsification test and for the **synthetic
  positive control**: the example's own criteria machinery must return
  `SUPPORTED` on a series with a known injected effect and `NOT SUPPORTED`
  on the matched no-effect series, the observed effect must exceed the
  framework's own reported minimum detectable effect, the control pair must
  differ by exactly the injected drift, the verdict must survive a change of
  seed, and the fixture must be labelled as synthetic and carry no security
  identifier. The control checks the decision machinery, not any market. See
  `references/validation_methods.md`, "A positive control: the machinery can
  say yes".
- `test_resolution_vs_sample_size.py` - Unit tests for the **resolution as a
  function of sample size**: the minimum confirmable annualized Sharpe falls
  as the sample grows and crosses below the framework's plausibility bound at
  a few thousand daily bars (the answer to the question the shipped samples
  left open -- their thresholds are a statement about their size, not about
  the criteria), the crossing is not an artefact of one random draw, the
  measurement agrees with the worked example's own shipped path (so it
  measures the shipped configuration and not a private copy of it), and it
  moves no threshold, no bound, no criterion and no verdict. The data is the
  synthetic positive-control fixture. See `references/validation_methods.md`,
  "How much data does criterion 2 need?".

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
- **Empty summaries are explicit, not silent**: when a walk-forward or CPCV run
  never takes a position in any period/fold, `summary["total_oos_return"]` is
  `None` (JSON `null`, CLI `N/A`) rather than `0.0`, and
  `summary["periods_with_position"]` / `summary["folds_with_position"]`
  reports how many periods/folds actually took a position. `0.0` means
  positions were taken and compounded to zero; `None` means none were ever
  taken. The two are distinct outcomes and must not be conflated by consumers
  (sweep writers, tear sheets, and the CLI render `None` as `N/A`). Documented
  in `references/validation_methods.md` under the walk-forward and CPCV
  "Output" sections.
- **The execution warmup is recorded, not assumed**: the two entry points
  warm up differently on purpose -- `walk_forward.py` drops the first
  `latency + 2` bars of every window (`warmup_convention` =
  `"walk_forward_drop_undefined"`), `run_backtest.py` opens the position on
  the first executable bar and drops 1 (`"run_backtest_open_first_executable"`).
  Every result artifact reports both `warmup_convention` and
  `execution_warmup_bars`, so a consumer never has to infer the convention
  from the shape of the return series, and the one-bar difference between the
  entry points is explained rather than accidental. The recorded count is the
  *execution* warmup; a strategy's own indicator warmup removes further bars
  on top of it. Documented in `references/validation_methods.md` under
  "Recording the Warmup Convention" and guarded by
  `tests/test_execution_warmup.py`.
- **`--fill-rate` scales the position, it does not model a partial fill**: the achieved position is `fill_rate * target_position` on every bar, so every position-change-based cost (commission, slippage, market impact) and every exposure-based cost (borrow, funding) scales linearly with it. Default `1.0` (full fill, backward compatible) is bitwise identical to no fill modeling. A `--fill-rates` sweep therefore measures position-size (leverage) sensitivity, not execution realism: the per-bar return series is exactly `fill_rate` times the full-fill series, the Sharpe is not scale-invariant (the risk-free rate is not scaled with the returns), the unfilled part of the order is charged nothing, and `estimate_capacity()` reports capacity at full fill. Do not read a fill-rate sweep as evidence that a strategy survives realistic execution. The convention is decided and pinned by `tests/test_run_backtest.py` (`test_run_backtest_fill_rate_scales_position_elementwise`) and documented in `references/validation_methods.md` under "Fill rate: decided convention".
- **Capacity is a point-in-time reading; the trend is the distribution**: the
  market-impact capacity estimate uses the *last* bar's ADV, so a liquidity
  squeeze that happened *inside* a window is invisible to it. Each regime
  therefore also carries a `capacity_trend` (min / median / max capacity and
  the `min_to_median_ratio` / `last_to_median_ratio` degradation ratios), and
  the walk-forward / CPCV summaries carry `oos_min_capacity` (the worst
  capacity in any out-of-sample window). Quote the trend, not only the
  point-in-time number, when judging whether a strategy can be scaled.
  Documented in `references/cost_models.md` under "Strategy Capacity
  Estimation".
- **The capacity estimate depends on the book the strategy actually holds**:
  the basket rule assumes an equal-weight basket that rebalances `1/n` per
  constituent, so it is an approximation for any other book. In
  `--panel-pricing book` mode the engine therefore reports a second,
  book-based capacity next to the basket one: the equity level at which the
  strategy's *own* rebalances reach the impact threshold,
  `min_i ( max_impact * ADV_i / (|dw_i| x impact_coefficient) )`. A book that
  trades more per period supports *less* capital than the basket rule
  reports; the two agree exactly for a book that trades `1/n` per
  constituent every period. Report both numbers, and state which convention
  each one uses.
- **A panel backtest prices net exposure, not the book**: a multi-asset
  portfolio is priced as `net_exposure x mean asset return`, one scalar per
  period, so a long/short book cannot be represented by it. Every panel run
  therefore carries a **panel book diagnostic** (`book_diagnostic`: gross
  book, book net exposure vs the priced net exposure, book turnover vs the
  turnover the cost model charges, and the return gap between the engine's
  P&L and the book P&L `sum_i w_i r_i`). It is measurement only — no return,
  cost, impact or capacity number changes — and it is `None` for a single
  asset or a strategy that does not expose a book. Read it before quoting a
  panel result: with symmetric quantiles the cross-sectional momentum
  signal is flat by construction, so the engine reports "no position" while
  the strategy holds a market-neutral book whose rotation is charged no
  impact at all. Documented in `references/cost_models.md` under "Panel book
  diagnostic (measurement only)".
- **`--panel-pricing book` prices and costs the book instead of measuring the
  gap**:
  the default `net-exposure` mode is the convention every published number
  was produced under (and is bit-identical to it), but it cannot represent a
  long/short book. With `--panel-pricing book` the portfolio return is the
  true per-asset book return `sum_i w_i r_i`, and the "does this strategy
  take a position?" test becomes book-aware, so the symmetric-quantile
  cross-sectional momentum (a market-neutral book) is backtestable instead
  of being rejected or skipped by the grid search. The **cost basis changes
  with the mode**: in `book` mode the transaction cost is charged on the
  book's gross turnover `sum_i |dw_i|` (not on `|d net exposure|`), borrow on
  its short legs `sum_i max(-w_i, 0)`, funding on its gross exposure
  `sum_i |w_i|`, and market impact per asset (`|dw_i| x equity` against that
  asset's own ADV). A book-mode number is therefore a *costed* number: on a
  900-bar 5-asset market-neutral cross-sectional book the total return moves
  from +16.3% (uncosted book) to -15.7% (costed book). The trade ledger is
  also built from the book (one round trip per asset and direction, priced at
  each asset's own close), so a market-neutral book finally has trade-level
  statistics. The **capacity** is reported twice in this mode: the
  basket-based estimate (an equal-weight basket that rebalances `1/n` per
  constituent, least liquid name binding) and, next to it, the **book-based**
  estimate `min_i ( max_impact * ADV_i / (|dw_i| x impact_coefficient) )` --
  the equity level at which the strategy's *own* rebalances reach the impact
  threshold (`results["capacity_book"]`, `summary["capacity_book"]`,
  `periods[i]["capacity_book"]`, `folds[i]["capacity_book"]`,
  `validation_performance["capacity_book"]`, `test_performance["capacity_book"]`,
  each with a `capacity_book_trend` distribution and, for the walk-forward /
  CPCV summaries, `oos_min_capacity_book`). The two rules agree exactly for a
  book that trades `1/n` per constituent every period; a book that trades
  more per period supports less capital. The book-based capacity is reported
  in `book` mode only, so the default path keeps a single capacity number.
  Residual approximation: the impact stays the equal-weighted mean of the
  per-asset impacts over the whole panel -- it is flagged in the CLI, the tear
  sheet and `references/cost_models.md`, and its size is now *measured* (see
  the next bullet).
  Every panel number must state its mode (`panel_pricing` in the results /
  summary, "Panel Pricing" in the tear sheet). Documented in
  `references/cost_models.md` under "Panel pricing modes (`--panel-pricing`)".
- **The market-impact model's participation dilution is measured, not
  assumed**:
  the panel impact model charges the equal-weighted mean of the per-asset
  impacts over the *whole* panel, so a period in which only `k` of `n` names
  trade is charged `1 / n` of the participation its traded names consumed.
  Every panel run therefore reports the impact the run charged next to the
  impact the names that traded would have paid
  (`impact_charged_bps`, `impact_traded_only_bps`, `impact_dilution_bps`,
  `impact_notional_weighted_bps`, `impact_participation_ratio` and the
  dilution as a fraction of the gross book return) in the panel book
  diagnostic, in the CLI output and in the tear sheet. It is measurement
  only -- no charged cost, return, capacity or Sharpe number changes. The
  measurement shows that the "conservative" alternative (the mean over the
  traded names) would *overcharge* the impact by `n / k` for the books this
  framework produces, because such a book trades only `k / n` of its equity
  in the `k` names it touches: the dollar-consistent aggregation of a linear
  impact model is the notional-weighted one, and switching to it is a
  separate, number-changing decision. Documented in
  `references/cost_models.md` under "Market-impact participation (measurement
  only)".
- Consider regime-dependent performance (bull/bear/sideways markets)
- Document all assumptions and data sources for reproducibility
- Run `--validate-point-in-time` on every backtest to screen for temporal-order violations, duplicate timestamps, and signal/next-return correlation (a look-ahead indicator); add `--point-in-time-strict` to make violations fail the run
- The definitive look-ahead test in `validate_point_in_time` is the **next-period correlation** between signal changes and `close[t+1] - close[t]`: a signal at time `t` must not predict the return at `t+1`, because no future information is available at time `t`. The contemporaneous (same-bar) correlation between signal changes and `close[t] - close[t-1]` is NOT used as a violation: a signal generated at time `t` is legitimately allowed to use `close[t]`, and `close[t]` is a component of the same-bar return, so any `close[t]`-based strategy (SMA crossover, mean reversion, Donchian) shows non-trivial same-bar correlation by construction. Only the next-period test can distinguish a legitimate `close[t]`-based signal from a genuinely forward-looking one.
- The out-of-sample validation framework (`walk_forward.py out-of-sample`) enforces a **strict chronological train/validation/test split** via `_verify_split_separation`: the three splits must be pairwise disjoint and ordered (`train_end < val_start`, `val_end < test_start`), and the check result is recorded in `train_val_test_split.separation_check`. A leak here would silently produce an in-sample-optimistic result indistinguishable from a genuine out-of-sample one, so the check is a correctness guard, not a cosmetic one.
- The **validation phase runs inside the training split**, so the walk-forward window has to fit it: one period needs `train_months + test_months` of calendar span. A window that does not fit yields **zero** periods, so no parameter can be selected — which is why the default 12 + 3 month window aborted on the shipped one-year sample. The window is now resolved against the training split before the phase runs (`_resolve_walk_forward_window`): a window that fits is used unchanged, a window that does not fit is shortened **on the training side only** (the out-of-sample test window and the validation/test splits are never touched), and the resolution is printed and recorded in `summary["walk_forward_window"]` (`requested` / `effective` / `adapted` / `train_span_months` / `effective_periods` / `reason`). An adapted window is a methodology choice, so it is never implicit.
- A validation phase that still selects nothing now **names its cause** instead of reporting "No valid parameters selected from validation phase": `summary["no_selection_diagnosis"].cause` is `no_validation_windows` (the window does not fit the training split) or `no_position_in_validation_window` (every grid combination stayed flat over the out-of-sample window — typically an indicator warm-up longer than the window). The CLI prints the diagnosis and writes it to `out_of_sample_summary.json`, so a failed run still leaves a machine-readable record of why it failed.
- **Every path that can select nothing says why.** The standalone `cpcv` and
  `walk-forward` analyses record the same `summary["no_selection_diagnosis"]`
  (same `{cause, message, details}` shape) when *no* fold / period could
  select a parameter, and their CLIs print it next to the fold / period
  count. A run that selects a parameter carries no diagnosis. The remedy in
  the message names the flags the path's own subcommand accepts (`--test-size`
  / `--n-splits` for `cpcv`, `--train-months` / `--test-months` for
  `walk-forward`, `--cpcv-test-size` / `--cpcv-n-splits` and
  `--wf-train-months` / `--wf-test-months` for `out-of-sample`), so the
  suggested fix can actually be applied. The diagnosis is a measurement: it
  changes no return, cost, impact, capacity or selection number.
- **A run in which only *some* windows select a parameter says which windows
  were flat and why.** "2 of 5 folds selected" is compatible with "the three
  flat folds were too short to trade" (a design problem) and with "the
  strategy never triggers on 60% of the sample" (a finding about the
  strategy), and the two need opposite remedies, so the count alone says
  nothing. Such a run records `summary["partial_selection_diagnosis"]` (the
  same `{cause, message, details}` shape) with a per-window breakdown: the
  cause, the window's length, its empty out-of-sample record, and the tally
  of what happened to every combination. The cause is **measured inside the
  search** (`selection_outcomes` on the period / fold record), not inferred
  from the empty result: a window in which no combination took a position
  (`no_position_in_validation_window`) and a window in which every
  combination took a position but the *training* split produced a constant
  return series (`no_estimable_training_sharpe`) look identical from the
  outside and need opposite remedies. The diagnosis also separates "the flat
  window was too short" from "the signal never triggered on it" by comparing
  the flat window's length with the shortest window in which the strategy
  did trade. The categorical overfitting-risk verdict keeps its value, and
  gains an `overfitting_risk_reason` that states how many of the windows it
  rests on. The all-flat case is unchanged (`no_selection_diagnosis`). See
  `references/validation_methods.md`, "When Only Some Windows Select a
  Parameter".

  - **A verdict that rests on windows the strategy barely traded in is weak
  evidence.** The aggregate out-of-sample Sharpe and the parameter stability
  ratio say nothing about *how much* of the windows the verdict rests on the
  strategy actually held a position: a "low" overfitting-risk rating earned on
  two windows that each traded for one bar reads as a finding about the
  strategy when it is mostly a finding about the windows. When a run is in
  the partial state it records `summary["thin_evidence_warning"]` -- a
  measurement, so it changes no number -- with a per-window breakdown of the
  windows the verdict rests on in which the strategy held a position for at
  most 20% of the **executable** bars (the window's length minus the warmup
  bars the run drops, so the fraction is stable across the two warmup
  conventions). The CLI prints it next to the verdict, and the artifact
  carries the same message. A run in which every window the verdict rests on
  traded in at least that fraction carries no warning. Guarded by
  `tests/test_no_selection_diagnosis.py`.

- **A significance test that cannot detect a plausible effect has not
  falsified anything.** With `T` observations, the threshold "deflated
  p < 0.10" requires the effect to exceed a certain size; when that size is
  implausible the criterion is measuring the sample, not the strategy. The
  worked example `examples/falsifiable_hypothesis_example.py` therefore
  reports the **test resolution** beside the verdict: the smallest annualized
  Sharpe / alpha each statistical criterion requires at the sample size
  actually available (`walk_forward.minimum_detectable_sharpe` and
  `walk_forward.minimum_detectable_alpha` invert the Deflated Sharpe Ratio
  and the Deflated Alpha Ratio), and it names the criteria the sample cannot
  resolve. On the shipped sample (100 test observations) those thresholds are
  an annualized Sharpe of 4.20, an annualized alpha of 38.0% (raw alpha
  t-test) and 35.3% (deflated) — all beyond what a plausible strategy
  produces, so their failure is a statement about the size of the held-out
  sample. The verdict itself is **not** changed by this: it stays the
  conjunction of the pre-registered criteria (a decision rule is not
  revisited after the result is seen), and the resolution is reported beside
  it. Two wiring rules keep the two alpha p-values distinguishable: the raw
  and the multiple-testing-corrected p-value are different statistics (the
  correction overwrites `alpha_pvalue` and keeps the raw one in
  `alpha_pvalue_original`), and the held-out window is counted in
  **observations**, not periods. Guarded by
  `tests/test_falsifiable_hypothesis_example.py` and
  `tests/test_walk_forward.py`.

- **The framework's own verdicts now report their resolution too.** The
  aggregate significance statistics carried by the walk-forward, CPCV and
  out-of-sample summaries (`summary["deflated_sharpe"]`,
  `summary["deflated_alpha"]`) are accompanied by
  `summary["test_resolution"]`: the number of test observations and parameter
  trials behind them, the smallest annualized Sharpe / alpha each statistic
  could have confirmed, and whether that threshold exceeds the stated
  plausibility bound (`PLAUSIBLE_MAX_ANNUALIZED_SHARPE = 2.0`,
  `PLAUSIBLE_MAX_ANNUALIZED_ALPHA = 0.10`). The primary backtest entry point
  (`run_backtest.py`) reports the same block under
  `metrics["test_resolution"]`, built from the statistics
  `calculate_metrics` attached and inverted on `results["returns"]` — the same
  series those statistics were computed on — so the resolution reported is the
  resolution of *that* statistic. The CLI prints it next to the Deflated
  Sharpe line, labelled *"measurement, not a correction"*. A statistic whose
  return series does not match the one it was computed on is reported as
  **not resolvable** with a reason, never as a number. The block changes no
  number: it is reporting-only, and a run without a significance test says so
  instead of staying silent. Guarded by
  `tests/test_test_resolution.py`.

- **A resolution without its statistic is not checkable.** The alpha
  resolution belongs to the *aggregate* Deflated Alpha Ratio (the DAR over the
  benchmark set), so all four CLIs print that statistic next to the
  resolution — `Deflated Alpha Ratio: 0.6329 (p-value 0.3671, expected max
  alpha 14.87%, 2 benchmarks)`. The numbers are the ones the artifact already
  carries under `summary["deflated_alpha"]`; nothing is recomputed and no
  reported number changes. (The per-benchmark corrected alpha p-value the
  CLIs also print is that benchmark's own DAR p-value; for the primary
  benchmark it coincides with the aggregate's, so what the aggregate line
  adds is the ratio itself, the expected maximum alpha and the benchmark
  count.) Guarded by `tests/test_test_resolution.py`.

- **A swept Sharpe without its resolution is a comparison the sample may not
  support.** A cost sweep reports one Sharpe per cost level, and the table
  invites the comparison "Sharpe 1.42 at 2 bps" against "Sharpe 0.31 at 8
  bps" — a difference the sample may not be able to see. Every sweep point of
  `run_backtest.py`'s cost sweeps (`--commissions`, `--slippages`,
  `--impact-coefficients`, `--borrow-costs`, `--funding-costs`, `--fill-rates`,
  `--latencies`) therefore carries the same `test_resolution` block, built by
  the framework's own `_build_test_resolution` from the statistics
  `calculate_metrics` produced for that coefficient, and the sweep table
  prints that threshold beside the Sharpe (`minSR`) and marks the points the
  sample cannot distinguish from zero (`below resolution`). The comparison is
  on magnitudes — `|Sharpe| < minSR` — so a large *negative* Sharpe is not
  flagged; and "below resolution" is a statement about the sample, not a
  negative result about the strategy. A sweep run without `--n-trials` carries
  no significance test, so the columns are `n/a` and the console says so. The
  sweep point and the single run at the same coefficient report the same
  numbers and the same block. Guarded by `tests/test_test_resolution.py`;
  the section is `references/validation_methods.md`, "Cost sweeps report the
  resolution of every point".

- **The significance machinery is only half-demonstrated by a sample it
  cannot resolve.** On the shipped samples every significance threshold sits
  beyond the plausibility bound, so those runs show that the machinery can
  *fail* — they cannot show that it can say *yes* when it should. The missing
  half is a **positive control**: a synthetic series with a known injected
  effect on which the example's own pre-registered criteria return
  `SUPPORTED`, together with a no-effect control (the identical construction
  with the effect removed) on which they return `NOT SUPPORTED`. The
  control's data is generated by `scripts/generate_positive_control_data.py`
  and is a check on the decision machinery only: it is produced by a formula,
  describes no real security, and the numbers it yields are properties of
  that formula and of the machinery. On the control the observed effect also
  exceeds the framework's own reported minimum detectable effect, so the
  `SUPPORTED` verdict is a power statement rather than luck. Guarded by
  `tests/test_falsifiable_hypothesis_example.py`; the construction and the
  reported numbers are in `references/validation_methods.md`, "A positive
  control: the machinery can say yes".

- **A threshold beyond the plausibility bound is a statement about the
  sample, and the sample size moves it.** The significance criteria are not
  unsatisfiable at plausible effect sizes: the minimum annualized Sharpe
  criterion 2 can confirm falls as the sample grows, because the held-out
  window lengthens (the `1 / sqrt(T)` term) and because the walk-forward
  training window expands, which makes the trial Sharpes the deflation
  benchmark is estimated from more precise. Measured at the shipped
  configuration, criterion 2 needs an annualized Sharpe of 4.20 on the
  shipped 504-bar sample, 2.40 at 2,500 bars and 1.71 at 10,000 bars — so it
  *can* confirm a plausible effect once a few thousand daily bars are
  available. The floor it converges onto is the framework's own
  `expected_max_sharpe` (SR\*), which is reported in every Deflated Sharpe
  block: no sample size can confirm an effect below it, so read that number
  before asking for more data. `scripts/measure_resolution_vs_sample_size.py`
  measures the whole curve (on the synthetic control fixture, or on the
  first N bars of a real history with `--data`). Guarded by
  `tests/test_resolution_vs_sample_size.py`; the curve and the mechanism are
  in `references/validation_methods.md`, "How much data does criterion 2
  need?".

- **The CPCV test window is a fraction of each group, so the effective
  out-of-sample fraction is `test_size / n_splits`.** At the default
  `--test-size 0.1 --n-splits 10` that is **1%**, and on the shipped 504-bar
  sample every fold's test window holds **5 bars** — shorter than the
  indicator warm-up, so nothing can be selected and every fold reports
  `best_params_per_fold: null`. The diagnosis states the window length and
  the effective fraction. The default is a design question, not a bug to be
  silently patched: changing it changes every CPCV number.
- **The overfitting-risk verdict is not applicable when nothing could be
  selected.** It is derived from the parameter stability, which exists only
  when a parameter was selected: with no selection the verdict is `null`
  ("unknown" in the CLI) plus an `overfitting_risk_reason`, not "low" and
  not "high". Before this, CPCV reported `high` and walk-forward reported
  `low` for the same state — a categorical verdict on a run that could not
  trade, which reads as a finding about the strategy when it is a fact about
  the window. Guarded by `tests/test_no_selection_diagnosis.py`.
- A parameter grid whose values do **not** change the strategy's behaviour is a null experiment: the "search" over it cannot change any result, yet the artifact would report it as a selected parameter. **Every** analysis path now detects it (`_inert_param_grid_keys` / `_inert_grid_report`): the out-of-sample path (`summary["inert_grid_params"]`), the walk-forward path and the CPCV path (both in their `summary`), and the parameter-optimization path (recorded in `parameter_optimization_inert_grid.json` next to the ranked list, because the ranking artifact is a plain list). Each CLI prints the warning exactly once, next to the ranking / selection it qualifies, so the console and the artifact say the same thing. It is a **warning, not an error**: the same grid may be non-inert on other data, and the measurement is a screen over the data the path prices, so it never changes a return, cost, impact, capacity or selection number. The check compares each key across **every** combination of the other grid keys' values, so a parameter that matters only in combination with another parameter (one the strategy reads only inside a branch) is never accused of being inert; the comparison is bounded at 16 combinations per key, and a grid that exceeds the bound falls back to the first combination **and the message says the check was bounded**, so a partial answer is never reported as a complete one. Check the strategy's parameter names before trusting a selection — `sma_crossover` reads `fast_period` and `slow_period`, so a grid over `lookback` searches nothing.
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
python3 skills/quantitative-backtesting/tests/test_execution_warmup.py
python3 skills/quantitative-backtesting/tests/test_out_of_sample_window.py
python3 skills/quantitative-backtesting/tests/test_inert_param_grid.py
python3 skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py
python3 skills/quantitative-backtesting/tests/test_examples_coverage.py
python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py
python3 skills/quantitative-backtesting/tests/test_test_resolution.py
python3 skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py
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
  in the walk-forward/CPCV summary; row and key omitted when absent) and
  per-period / per-fold capacity rendering (a "Capacity (Notional)" column in
  the per-period and per-fold tables, "N/A" when the estimate is absent), plus
  the capacity-trend rendering (a "Strategy Capacity Min (Notional)" summary
  row and a "Capacity Min (Notional)" column, omitted / "N/A" when the trend
  is absent).
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
  Also covers the **panel book diagnostic section**: the tear sheet renders a
  "Panel Book Diagnostic" table (gross book, book vs priced net exposure,
  book turnover vs charged turnover, return gap) and a top-level
  `book_diagnostic` key in the JSON summary when the diagnostic is present,
  and omits both when it is absent.
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
  from the strategy's own shifted signals).   Also covers **multi-asset
  panel integration**: `run_backtest` accepts dict-of-DataFrames and
  MultiIndex-column panel data for `CrossSectionalMomentum` and
  `DualMomentumStrategy`, and the trade ledger is validated (non-empty,
  well-formed) for both formats. The extractor iterates the position
  series, not `data`, because `len(data)` is the number of symbols (not
  bars) for a dict and `data.index` does not exist on dicts. Also covers the
  **panel book diagnostic**: a panel run surfaces
  `results["book_diagnostic"]` (gross book, book net exposure vs the priced
  net exposure, book turnover vs the turnover the cost model charges, the
  return gap against the book return `sum_i w_i r_i` recomputed
  independently in the test), a single asset or a strategy without a book
  surfaces `None`, and the flat-net-exposure guard now explains that the
  strategy does hold a book even though the engine reports no position.
  Also covers the **panel pricing modes**: `--panel-pricing book` prices
  the panel as the true per-asset book return `sum_i w_i r_i` and makes the
  "takes a position?" test book-aware, so the symmetric-quantile
  cross-sectional momentum (a market-neutral book) is backtested instead of
  raising, and its reported return equals the book return recomputed by
  hand; the two modes differ by exactly the measured `return_gap`; the
  default mode is `net-exposure` and reproduces the explicit mode
  bit-for-bit; a strategy without a book falls back to net-exposure pricing
  with the fallback recorded (`panel_pricing_effective`); a single asset is
  unaffected. Also covers the **book cost basis**: the transaction cost of a
  book is charged on its gross turnover (recomputed by hand from the
  strategy's own weights), the borrow cost on its short legs, the market
  impact per asset against that asset's own ADV (and it scales with the fill
  rate), the book is charged a strictly larger cost than the flat net
  exposure it replaces, the book mode builds a trade ledger (one round trip
  per asset and direction, priced at the asset's own close) so the
  trade-level statistics exist for a market-neutral book, and the
  net-exposure numbers are unchanged by all of it (pinned).
  Also covers
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
  Also covers **cross-path parity for panels**: the same panel, strategy and
  cost assumptions produce identical return values through `run_backtest.py`
  and through `walk_forward.py`'s return calculator, for both the
  MultiIndex and the dict panel format
  (`test_run_backtest_panel_matches_walk_forward_return_calculator`,
  `test_run_backtest_dict_panel_matches_walk_forward_return_calculator`).
  The panel return convention is pinned to the mean of the per-asset
  returns rather than the return of the mean price series
  (`test_run_backtest_panel_uses_mean_of_per_asset_returns`), the panel
  impact cost is pinned to the per-asset model rather than an aggregated
  pseudo-asset ADV
  (`test_run_backtest_panel_impact_splits_notional_across_assets`), and the
  panel capacity is pinned to the least-liquid-binds basket estimate
  (`test_run_backtest_panel_capacity_binds_on_least_liquid_constituent`).
- `test_strategy_builder.py` - strategy registry, `build_strategy`, defaults,
  binary long/flat signal generation with real crossovers, and multi-asset
  panel signal generation for `CrossSectionalMomentum` and
  `DualMomentumStrategy` (dict and MultiIndex formats, single-asset
  fallback warnings, quantile/ranking semantics). Also covers the optional
  **book accessor** `StrategyBase.generate_target_weights`: it returns
  `None` by default (a strategy without a book is unchanged), the
  cross-sectional book's net exposure equals the scalar signal exactly, the
  symmetric-quantile book is open (gross book > 0) while its net exposure is
  flat, and the dual-momentum book is long-only and equally weighted.
  Covers `MeanReversionZScore`
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
      **Capacity surfacing**: `estimate_capacity` on a single asset, on a
      multi-asset panel (equal-weighted basket whose least liquid member binds
      the portfolio capacity), and on the per-regime keys
      (`period["capacity"]`, `fold["capacity"]`,
      `validation_performance["capacity"]`, `test_performance["capacity"]`),
      plus the CLI artifacts `capacity_per_period` / `capacity_per_fold` and
      the out-of-sample `validation_capacity` / `test_capacity` summary keys.
      **Capacity trend**: the per-window distribution of the capacity readings
      (`min_capacity` / `median_capacity` / `max_capacity` / `last_capacity`
      and the two degradation ratios) on `period["capacity_trend"]`,
      `fold["capacity_trend"]`, the per-split and summary `capacity_trend`
      keys, and the `oos_min_capacity` aggregate; `None` when impact is
      disabled or ADV is not estimable, and the point-in-time
      `estimated_capacity` number is unchanged.
      **Book-based capacity**: the capacity implied by the strategy's own
      trade sizes (`results["capacity_book"]`, `summary["capacity_book"]`,
      `period["capacity_book"]`, `fold["capacity_book"]`, the out-of-sample
      per-split keys, each with a `capacity_book_trend` distribution and
      `oos_min_capacity_book` on the walk-forward / CPCV summaries); it agrees
      exactly with the basket estimate for a book that trades `1/n` per
      constituent every period, is lower for a book that trades more per
      period, and is `None` outside the `book` pricing mode.
      **Panel book diagnostic**: the per-window `period["book_diagnostic"]` /
      `fold["book_diagnostic"]` records, the aggregated
      `summary["book_diagnostic"]`, the out-of-sample per-split
      `validation_book_diagnostic` / `test_book_diagnostic` keys, and the CLI
      artifact rows; `None` for a single asset or a strategy without a book.
      **Market-impact participation**: the three aggregations of the impact
      model recomputed by hand from the strategy's own weights (the panel
      mean, the mean over the names that traded, and the notional-weighted
      dollar cost), the exact `panel == (k / n) * traded_only` identity, the
      reported `impact_*` keys in both pricing modes, their absence when
      impact is disabled, and the guarantee that no charged number moves
      (`test_impact_participation_does_not_move_any_charged_number`).
      **Panel pricing modes**: `panel_pricing="book"` prices the panel as
      the true per-asset book return `sum_i w_i r_i` and makes the grid
      search's "takes a position?" test book-aware, so a market-neutral book
      is traded instead of being skipped (the net-exposure mode skips every
      combination of the symmetric-quantile cross-sectional momentum); the
      two modes differ by exactly the measured `return_gap`; the summary
      records `panel_pricing`; the out-of-sample path prices the held-out
      window under the selected mode; and the **book cost basis** charges the
      out-of-sample record its own transaction costs (the book gross
      turnover), so the costed book record is strictly below the uncosted
      one while the two modes still report the same bars.
  - `test_cpcv.py` - CPCV fold structure, purge/embargo behavior, parameter
    stability calculation, summary metrics, **Deflated Sharpe Ratio
    correction** (`apply_deflation` on `cpcv_analysis`), CLI integration,
    multi-asset panel (dict and MultiIndex) CPCV integration with
    `CrossSectionalMomentum` and `DualMomentumStrategy`, and **capacity
    surfacing**: the aggregate `summary["capacity"]`, the per-fold
    `fold["capacity"]` (present on every fold, `None` when impact is
    disabled), the per-fold `fold["capacity_trend"]` and the
    `summary["oos_min_capacity"]` aggregate, and a regression guard that a
    multi-asset panel no longer raises when market impact is enabled. Also
    covers the **panel book diagnostic**: every fold carries a
    `fold["book_diagnostic"]` (gross book, book vs priced net exposure) and
    the summary carries the aggregate `summary["book_diagnostic"]`; a
    single-asset run has neither. Also covers the **panel pricing modes**:
    under `panel_pricing="book"` a market-neutral book is traded in every
    fold (the net-exposure mode skips all of them), the two modes differ by
    exactly the measured `return_gap`, and the net-exposure numbers are
     unchanged (the pinned `total_oos_return`).
     Also covers the **pinned cross-run regression values**: the reference
     `total_oos_return`, the selected `lookback` per fold and the number of
     usable OOS bars are asserted, and
     `test_cpcv_pinned_number_is_reproducible_from_first_principles`
     re-derives the whole CPCV pipeline independently (own fold construction,
     own cross-sectional signal, own lag-1 execution, own
     `mean of per-asset returns` pricing, own cost term, own warmup handling,
     own product) and requires the framework to agree with it, so the pin
     checks the *methodology* rather than the code's own last output. The
     cross-run values are compared with a relative tolerance, never with
     exact `==`: the last bits of a compounded float move with the
     numpy/pandas build. See `references/validation_methods.md` under "The
     Warmup Bars of a Window" and "Reproducing the Pinned CPCV Number".
  - `test_generate_sample_data.py` - Sample data generation creates valid OHLCV
    CSV with expected shape and constraints.
  - `test_out_of_sample_window.py` - the out-of-sample validation window and
    its diagnosis: the window is shortened on the training side only when
    the requested one does not fit the training split (and left untouched
    when it does), the adaptation is recorded in
    `summary["walk_forward_window"]`, a validation phase that cannot select
    reports its cause in `summary["no_selection_diagnosis"]` and the CLI
    writes that diagnosis to `out_of_sample_summary.json`, and an inert
    parameter grid is reported in `summary["inert_grid_params"]`.
  - `test_inert_param_grid.py` - inert parameter grids on **all four**
    analysis paths: the measurement flags a grid key the strategy does not
    read (`lookback` for `sma_crossover`) and leaves a live key alone; a
    key that only matters in *combination* with another key is not accused
    either (the demonstration strategy reads `threshold` only in the
    `mode == "b"` branch); the walk-forward, CPCV and out-of-sample
    summaries record the finding, the parameter-optimization path hands it
    to the caller and the CLI writes it to
    `parameter_optimization_inert_grid.json`; each CLI prints the warning
    **exactly once** (the analysis functions never print) next to the
    ranking / selection it qualifies; and the measurement changes no number
    (the ranking with and without the report is identical, and the
    walk-forward summary differs only in the two keys that carry the
    finding).
  - `test_no_selection_diagnosis.py` - the "no parameter could be selected"
    diagnosis on the standalone paths: the standalone CPCV and walk-forward
    summaries record `summary["no_selection_diagnosis"]` (the same
    `{cause, message, details}` shape the out-of-sample path uses) when no
    fold / period could select anything; the cause is
    `no_position_in_validation_window`; the message names the window length
    and the effective out-of-sample fraction (`test_size / n_splits`), and
    the remedy names flags that the path's own subcommand accepts (checked
    against its `--help` output); a run that does select a parameter carries
    no diagnosis and keeps its categorical overfitting verdict, while a run
    that cannot select reports `null` / "unknown" plus a reason; and the
    diagnosis changes no number. The same file covers the **partial**
    selection (some windows selected, some did not): the run's facts are
    pinned so the demonstration cannot rot into a hypothetical, the artifact
    records `summary["partial_selection_diagnosis"]` with a per-window
    breakdown (cause, reason, window length, empty out-of-sample record,
    outcome tally), the cause is the one the search's own tally measured
    (`no_position_in_validation_window` vs.
    `no_estimable_training_sharpe`), the flat folds are shown not to be
    short windows, the categorical overfitting verdict keeps its value and
    gains a reason that states how many windows it rests on, the remedy
    names flags the path accepts, and the all-flat case still uses
    `no_selection_diagnosis`.
  - `test_falsifiable_hypothesis_example.py` - the worked example's
    pre-registered falsification test on the shipped sample (structure,
    chronology, the raw-vs-corrected alpha p-value, the reported resolution,
    and the rule that the resolution changes no verdict) **and the synthetic
    positive control**: on a series with a known injected effect the example's
    own criteria machinery returns `SUPPORTED`, on the matched no-effect
    series it returns `NOT SUPPORTED`, the observed effect exceeds the
    framework's own reported minimum detectable effect (so the verdict is a
    power statement, not luck), the control pair differs by exactly the
    injected drift, the verdict survives a change of seed, and the fixture
    is labelled as synthetic and carries no security identifier. The control
    is a check on the test machinery only — it is generated by
    `scripts/generate_positive_control_data.py` and says nothing about any
    real security.
  - `test_resolution_vs_sample_size.py` - the **resolution as a function of
    sample size**: the minimum confirmable annualized Sharpe falls as the
    sample grows and crosses below the framework's 2.0 plausibility bound at
    a few thousand daily bars, so the shipped samples' thresholds are a
    statement about their size rather than about the criteria; the crossing
    holds on every draw measured (three seeds, both the effect and the
    no-effect control); the measurement agrees with the worked example's own
    shipped path; and it moves no threshold, no bound, no criterion and no
    verdict. The data is the synthetic positive-control fixture — the
    numbers are properties of a formula and of the decision machinery, never
    evidence about a security.

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