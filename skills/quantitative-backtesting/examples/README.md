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
- **Multiple-testing correction** with Deflated Alpha Ratio
- **Out-of-sample thinking** and rigorous validation practices

### `deflated_alpha_example.py`

Demonstrates the Deflated Alpha Ratio (multiple-testing correction for benchmark alpha):

1. **Single benchmark case** - With N=1, correction is minimal
2. **Multiple benchmarks with trial alphas** - Using cross-sectional dispersion of alphas to estimate expected max alpha
3. **Multiple benchmarks with fallback** - Using i.i.d. normal approximation when trial alphas are unavailable

Run with:
```bash
python3 skills/quantitative-backtesting/examples/deflated_alpha_example.py
```

### `multiple_benchmarks_example.py`

Demonstrates the full multiple-benchmark workflow with deflated alpha correction:

1. **Strategy backtest** - SMA crossover on synthetic OHLCV data with transaction costs
2. **Multiple benchmark loading** - Loads two benchmark return series
3. **Metrics with benchmark_list** - Calls `calculate_metrics` with `benchmark_list` parameter to trigger multiple-testing correction
4. **Deflated alpha output** - Displays DAR, p-value, expected max alpha, z-score, skewness/kurtosis
5. **Direct function usage** - Shows how to collect trial alphas from each benchmark and pass to `deflated_alpha_ratio`

Run with:
```bash
python3 skills/quantitative-backtesting/examples/multiple_benchmarks_example.py
```

Outputs metrics to `example_output/multiple_benchmarks_metrics.json`.

### `real_data_pipeline_example.py`

Complete end-to-end quantitative research pipeline simulating real-market workflows:

1. **Synthetic universe generation** - Creates correlated multi-asset OHLCV data (8 assets, 3 years) using `generate_multi_asset_data()`
2. **Point-in-time validation** - Validates all assets for look-ahead bias with SMA(20, 50) lookback windows
3. **Survivorship bias detection** - Analyzes universe for survivor/entry/exit bias
4. **CPCV validation (Python API)** - Runs `cpcv_analysis` with 2 benchmarks, surfacing `deflated_alpha` and `benchmark_metrics`
5. **CPCV validation (CLI)** - Production-pattern `walk_forward cpcv` with multiple `--benchmark` files
6. **Monte Carlo validation (CLI)** - Production-pattern `walk_forward monte-carlo` with multiple benchmarks, tear sheet rendering deflated alpha
7. **Direct deflated alpha computation** - Demonstrates `_benchmark_list_alpha_correction` and `deflated_alpha_ratio` with trial alphas

Run with:
```bash
python3 skills/quantitative-backtesting/examples/real_data_pipeline_example.py
```

Self-contained: uses temporary directories, no persistent artifacts.

### `trading_costs_robustness_example.py`

Systematic sensitivity analysis of trading costs and cost-modeling assumptions:

1. **Strategy cost sensitivity** — Sweeps commission × slippage × borrow cost × funding cost on the strategy side, measuring how Sharpe, Calmar, and max drawdown degrade.  Borrow and funding costs have no P&L effect on the long-only SMA-crossover strategy (no short positions or leverage).  Two **exposure variants** are demonstrated within this section: a **short-capable variant** (signals inverted from flat to -1) showing that borrow costs reduce returns when the strategy carries short exposure (while funding costs remain zero — no leverage), and a **leveraged variant** (2× long-only) showing that funding costs reduce returns when gross exposure exceeds 1×.
2. **Benchmark cost-model sensitivity** — Sweeps benchmark commission, expense ratio (0–1% annual), and periodic-vs-round-trip costing, showing the impact on estimated alpha and the Deflated Alpha Ratio (DAR).  Includes a positive-alpha scenario using a degraded-strategy benchmark (strategy asset with −30%/−60% compounding drag) that produces DAR ∈ (0, 1) and demonstrates how cost-modeling shifts statistical inference when skill is present.
3. **CPCV robustness under cost stress** — Compares out-of-sample Sharpe, return, and DAR between low-cost and high-cost regimes (including market impact, borrow cost, and funding cost).
   4. **Market-impact sensitivity** — Sweeps the market-impact coefficient (0→5.0) on a market-neutral pairs portfolio, showing how capacity-constrained trading costs degrade returns. This guards against the historical bug where `position_notional` was scaled by the raw asset price instead of portfolio equity, which silently disabled the impact model.

Run with:
```bash
python3 skills/quantitative-backtesting/examples/trading_costs_robustness_example.py
```

Self-contained: uses synthetic data, no network access required. Produces a structured JSON summary and a key-findings banner.

### `falsifiable_hypothesis_example.py`

A worked example of a **pre-registered falsification test**: one specific,
bounded hypothesis, five explicit falsification criteria, and a verdict that
is the conjunction of those criteria — never a claim of profitability.

1. **Pre-registered criteria** — OOS Sharpe > 0; deflated Sharpe p-value < 0.10; raw benchmark-alpha p-value < 0.05; OOS total return above the benchmark's; Deflated Alpha Ratio > 0.90.
2. **Chronological 0.6/0.2/0.2 train/validation/test split**, with the split-separation audit printed (the held-out test set is never used in any selection step).
3. **Point-in-time validation, walk-forward selection on the training slice only**, and a multiple-testing correction on both sides (parameter grid → Deflated Sharpe; benchmark set → Deflated Alpha).
4. **The raw and the corrected alpha p-values are kept distinct.** The benchmark correction rewrites `alpha_pvalue` with the deflated value and keeps the raw one in `alpha_pvalue_original`; criterion 3 reads the raw value and criterion 5 the corrected one, so the benchmark-side data-mining control binds independently instead of being implied by criterion 3.
5. **Test resolution** — the smallest annualized Sharpe / alpha each significance criterion requires at the sample size actually available (the minimum detectable effect), with the criteria the sample cannot resolve named in the output. The verdict is *not* changed by this analysis: a decision rule is not revisited after the result is seen.

On the shipped sample data the verdict is `NOT SUPPORTED`, and the resolution
section shows that the three statistical criteria need effects the 100 test
observations cannot resolve — so that verdict is largely a statement about the
size of the held-out sample rather than about the strategy.

**The positive control.** A verdict that can only ever be `NOT SUPPORTED`
would be no evidence of a test at all, so the example's machinery is also run
against a **synthetic** series with a known injected effect (and against a
matched no-effect control) in
`tests/test_falsifiable_hypothesis_example.py`. On the effect series the same
criteria return `SUPPORTED`, on the no-effect series they return `NOT
SUPPORTED`, and on the effect series the observed effect also exceeds the
framework's own reported minimum detectable effect. The control is a check on
the decision machinery: its data is produced by a formula
(`scripts/generate_positive_control_data.py`), describes no real security, and
says nothing about any market.

**How much data the criteria need.** The thresholds on the shipped sample are a
statement about its 504 bars, not about the criteria: measured at the same
configuration, the smallest annualized Sharpe criterion 2 can confirm falls
from 4.20 (the shipped 504-bar sample) to 2.40 at 2,500 bars and 1.71 at
10,000 bars, crossing below the framework's 2.0 plausibility bound on the way.
`scripts/measure_resolution_vs_sample_size.py` produces that curve, and
`references/validation_methods.md`, "How much data does criterion 2 need?",
records it and the mechanism.

Run with:
```bash
python3 skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py
```

### `real_data_workflow.md`

Comprehensive guide for working with real market data including:
- Data provenance best practices
- Point-in-time validation to prevent look-ahead bias
- Survivorship bias detection for universe construction
- Split/dividend adjustments and total-return benchmarks
- Realistic cost modeling (commissions, slippage, market impact, borrow/funding)
- Multiple-testing correction with deflated alpha
- Walk-forward analysis and Monte Carlo robustness checks
