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
- `walk_forward.py` - Walk-forward analysis and parameter optimization
- `reporting.py` - Automated tear sheet and report generation
- `generate_sample_data.py` - Generates a sample OHLCV dataset for testing

### tests/
- `test_walk_forward.py` - Unit tests for walk-forward and parameter optimization
- `test_run_backtest.py` - Unit tests for the run_backtest CLI entry point
- `test_strategy_builder.py` - Unit tests for the strategy factory and registry
- `test_data_loader.py` - Unit tests for data loading and validation

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