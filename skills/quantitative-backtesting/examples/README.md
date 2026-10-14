# Quantitative Backtesting Examples

This directory contains example workflows demonstrating the quantitative backtesting pipeline.

## Examples

### `full_pipeline_example.py`

Demonstrates a complete end-to-end quantitative research workflow:

1. **Data Loading with Provenance** - Load OHLCV data with full provenance tracking (source, checksum, transformations, validation status)
2. **Data Validation** - Validate data quality (OHLC relationships, volume constraints, gaps)
3. **Point-in-Time (PIT) Validation** - Detect potential look-ahead bias and validate temporal ordering
4. **Survivorship Bias Detection** - Analyze panel data for survivorship, entry/exit, and data gaps
5. **Backtesting with Costs** - Run a strategy backtest with realistic transaction costs (commissions + slippage)
6. **Benchmark Comparison** - Compare strategy performance against buy-and-hold benchmark with cost modeling
7. **Performance Metrics** - Calculate comprehensive metrics including Sharpe, Sortino, Calmar, VaR/CVaR, alpha/beta, tracking error, and statistical significance
8. **Report Generation** - Generate text reports and tear sheets

## Running the Examples

From the repository root:

```bash
python3 skills/quantitative-backtesting/examples/full_pipeline_example.py
```

From within the examples directory:

```bash
cd skills/quantitative-backtesting/examples
python3 full_pipeline_example.py
```

## Expected Outputs

The example creates an `example_output/` directory with:

- `data_provenance.json` - Complete data provenance metadata
- `survivorship_bias_report.json` - Survivorship bias analysis results
- `metrics.json` - All computed performance metrics
- `report.txt` - Human-readable performance report

Note: Tear sheet generation requires matplotlib. In environments without matplotlib, the tear sheet step is skipped gracefully.

## Data Sources

All examples use the included synthetic sample data: `../assets/example_data/sample_ohlcv.csv` (504 trading days of OHLCV data). No external network access is required.

## Key Concepts Demonstrated

- **Provenance tracking** for research reproducibility
- **Point-in-time validation** to prevent look-ahead bias
- **Survivorship bias detection** for robust universe construction
- **Realistic cost modeling** (commissions, slippage, benchmark costs)
- **Benchmark comparison with statistical tests** (alpha, beta, correlation, t-stats)
- **Out-of-sample thinking** and rigorous validation practices
