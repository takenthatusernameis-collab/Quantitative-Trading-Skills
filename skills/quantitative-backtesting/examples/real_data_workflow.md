# Real Data Integration Workflow Guide

This guide demonstrates a complete, reproducible workflow for quantitative research with market data. While this repository uses synthetic data (no network access required), the patterns shown here apply directly to real data sources.

## Prerequisites for Real Data

### Data Sources
Common data providers for quantitative research:
- **Yahoo Finance**: Free, accessible via yfinance or direct API
- **Alpha Vantage**: Free tier available
- **Quandl/Nasdaq Data Link**: Mix of free and paid
- **Polygon.io**: High-quality, paid
- **FRED (Federal Reserve)**: Macroeconomic data
- **CRSP/WRDS**: Academic/professional (survivorship bias corrected)

### Data Format Requirements
The backtesting pipeline expects OHLCV data with columns: `date` (or index), `open`, `high`, `low`, `close`, `volume`. Optional columns: `adj_close`, `dividends`, `splits`.

## Complete Workflow Example

### 1. Load Data with Provenance Tracking

Always track data provenance for reproducibility.

```python
from data_loader import load_data

# Load data - track full provenance
df, prov = load_data("SPY.csv", symbol="SPY", return_provenance=True)
print(prov.to_json())  # Save for research audit trail
```

### 2. Validate Data Quality

```python
from data_loader import validate_data

is_valid = validate_data(df, strict=False)
if not is_valid:
    # Investigate validation messages in provenance
    print(prov.validation_messages)
```

### 3. Point-in-Time (PIT) Validation

Critical for preventing look-ahead bias - ensure no future information leaks into past observations.

```python
from data_loader import validate_point_in_time

# For single-asset with strategy signals
pit_results = validate_point_in_time(df, signals=your_signals)
if not pit_results["passed"]:
    print("WARN: PIT violations detected - potential look-ahead bias")
```

### 4. Survivorship Bias Detection (Multi-Asset)

When working with equity universes, check for delisted stocks and data availability.

```python
from data_loader import load_multi_symbol, detect_survivorship_bias

# Load panel of multiple symbols
panel = load_multi_symbol("universe.csv")  # CSV with symbol column

# Detect survivorship bias
bias_report = detect_survivorship_bias(panel)
print(f"Survivorship score: {bias_report['survivorship_score']}")
# High scores indicate potential survivorship bias
```

### 5. Split Adjustment

For accurate returns, adjust for corporate actions. The implementation follows Yahoo Finance conventions (splits as new_shares/old_shares).

```python
from data_loader import load_data

# Automatically adjust splits if splits column present
df = load_data("SPY.csv", adjust_splits=True)
```

### 6. Backtest with Realistic Costs

Model transaction costs, market impact, borrow/funding costs for realism.

```python
from strategy_builder import build_strategy

strategy = build_strategy("sma_crossover", params={"short_window": 20, "long_window": 50})
signals = strategy.generate_signals(df)
returns = strategy.backtest(
    df,
    signals,
    initial_capital=100000,
    commission=0.0002,      # 2 bps per trade
    slippage=0.0001,        # 1 bp slippage
    impact_coefficient=0.1, # Market impact
    borrow_cost=0.03,       # 3% annual borrow (for shorts)
)
```

### 7. Benchmark Comparison with Statistical Significance

Compare against benchmarks with proper cost modeling and significance testing.

```python
from performance import calculate_metrics

metrics = calculate_metrics({
    "returns": returns,
    "benchmark": spy_benchmark["close"],
    "config": {
        "commission": 0.0002,
        "slippage": 0.0001,
        "benchmark_commission": 0.0002,
        "benchmark_slippage": 0.0001,
        "benchmark_expense_ratio": 0.0005,  # 5 bps ETF expense ratio
        "benchmark_cost_is_periodic": False,  # Round-trip for buy-and-hold
        "total_return_benchmark": True,      # Use total return if dividends available
    }
})
```

### 8. Multiple Testing Correction (Deflated Alpha)

When testing against multiple benchmarks, correct for selection bias.

```python
from walk_forward import deflated_alpha_ratio

# If testing strategy against multiple benchmarks
da = deflated_alpha_ratio(
    alpha=metrics["alpha"],
    returns=returns,
    benchmark_returns=benchmarks[0].pct_change().dropna(),
    n_benchmarks=len(benchmarks),
    trial_alphas=[stats["alpha"] for stats in all_bench_stats],  # Recommended
)
print(f"DAR: {da['deflated_alpha_ratio']:.4f}, p-value: {da['p_value']:.4f}")
```

### 9. Walk-Forward Analysis (Out-of-Sample Validation)

Avoid overfitting with proper time-series cross-validation.

```bash
# CLI usage
python3 scripts/walk_forward.py walk-forward \
  --data data.csv \
  --param-grid '{"short_window":[10,20,30], "long_window":[40,50,60]}' \
  --train-months 12 --test-months 3 --step-months 3 \
  --benchmark bench.csv --total-return-benchmark \
  --output wf_results
```

### 10. Statistical Robustness (Monte Carlo)

Test robustness to sampling variation.

```bash
python3 scripts/run_backtest.py --data data.csv --strategy sma_crossover \
  --params '{"short_window":20,"long_window":50}' \
  --monte-carlo --n-simulations 2000
```

## Best Practices

1. **Data provenance**: Always save and version your data provenance metadata
2. **Split/dividend adjustments**: Use total-return benchmarks and split-adjusted prices
3. **Realistic costs**: Include commissions, slippage, market impact, borrow/funding costs
4. **Out-of-sample validation**: Use walk-forward or CPCV, never rely solely on in-sample optimization
5. **Statistical significance**: Report p-values, t-stats, and multiple-testing corrections
6. **Robustness checks**: Sensitivity analysis, Monte Carlo, parameter stability
7. **No data-mining bias**: Pre-register hypotheses when possible; account for all trials tested
8. **Reproducibility**: Fix seeds, document all parameters, save full configs
