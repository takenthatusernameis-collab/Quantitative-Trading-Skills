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
- `run_backtest.py` - Main entry point for running backtests with configurable parameters
- `data_loader.py` - Utilities for loading and validating market data from various sources
- `strategy_builder.py` - Factory for creating common strategy templates (trend, mean reversion, momentum)
- `performance.py` - Comprehensive performance analytics and metric calculation
- `walk_forward.py` - Walk-forward analysis, parameter optimization, Monte Carlo, CPCV, and Deflated Sharpe Ratio multiple-testing correction
- `reporting.py` - Automated tear sheet and report generation
- `generate_sample_data.py` - Generates a sample OHLCV dataset for testing

### tests/
- `test_walk_forward.py` - Unit tests for walk-forward and parameter optimization
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
- Correct for multiple testing: a grid search over many parameter combinations inflates in-sample Sharpe; compute the Deflated Sharpe Ratio (`--deflate`) before trusting a Sharpe estimate
- Consider regime-dependent performance (bull/bear/sideways markets)
- Document all assumptions and data sources for reproducibility

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
python3 skills/quantitative-backtesting/tests/test_generate_sample_data.py
```

- `test_data_loader.py` - CSV/Parquet loading, column/date handling, symbol
  filtering, and `validate_data` quality checks (missing columns, non-positive
  prices, high < low, duplicate dates, short series).
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
  Uses the stdlib `unittest` framework rather than the custom runner.
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
  bars) for a dict and `data.index` does not exist on dicts.
- `test_strategy_builder.py` - strategy registry, `build_strategy`, defaults,
  binary long/flat signal generation with real crossovers, and multi-asset
  panel signal generation for `CrossSectionalMomentum` and
  `DualMomentumStrategy` (dict and MultiIndex formats, single-asset
  fallback warnings, quantile/ranking semantics).
  - `test_walk_forward.py` - walk-forward windowing, parameter grid parsing,
    train/test separation, Monte Carlo simulation, **Deflated Sharpe Ratio
    multiple-testing correction** (`deflated_sharpe_ratio`, `apply_deflation`
    on `parameter_optimization` and `walk_forward_analysis`, CLI `--deflate`),
    and multi-asset panel (dict and MultiIndex) walk-forward and Monte Carlo
    integration with `CrossSectionalMomentum` and `DualMomentumStrategy`.
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