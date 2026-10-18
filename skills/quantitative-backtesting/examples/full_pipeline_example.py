#!/usr/bin/env python3
"""
Example workflow demonstrating the full quantitative backtesting pipeline.

This script walks through a complete end-to-end workflow:
1. Load and validate market data with provenance tracking
2. Perform point-in-time (PIT) validation and look-ahead bias detection
3. Detect survivorship bias in multi-asset context
4. Run a backtest with realistic transaction costs
5. Compare against a benchmark (buy-and-hold) with costs
6. Compute performance metrics including statistical significance
7. Generate reports and tear sheets

All data comes from the included sample data - no external network access required.
"""

import sys
import json
from datetime import datetime, UTC
from pathlib import Path

import numpy as np
import pandas as pd

# Add scripts to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import (
    load_data,
    validate_data,
    load_multi_symbol,
    validate_point_in_time,
    detect_survivorship_bias,
    _compute_benchmark_total_return,
    _detect_benchmark_total_return_type,
)
from strategy_builder import build_strategy
from performance import calculate_metrics, generate_report
from reporting import generate_tear_sheet


def run_full_pipeline():
    """Execute the complete quantitative backtesting pipeline."""
    print("=" * 80)
    print("QUANTITATIVE BACKTESTING: FULL PIPELINE EXAMPLE")
    print("=" * 80)
    print()

    # Configuration
    data_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    out_dir = Path(__file__).resolve().parent / "example_output"
    out_dir.mkdir(exist_ok=True)

    # 1. DATA LOADING WITH PROVENANCE TRACKING
    print("1. LOADING DATA WITH PROVENANCE TRACKING")
    print("-" * 50)
    df, prov = load_data(str(data_path), symbol="SPY", return_provenance=True)
    print(f"✓ Loaded {len(df)} rows from {data_path.name}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  File checksum: {prov.checksum}")
    print(f"  Total return type detected: {prov.total_return_type}")
    print()
    prov_path = out_dir / "data_provenance.json"
    prov_dict = prov.to_dict()
    # Make timestamp stable for reproducibility: use source file's mtime
    try:
        from datetime import datetime, UTC
        prov_dict["load_timestamp"] = datetime.fromtimestamp(
            data_path.stat().st_mtime, UTC
        ).isoformat().replace("+00:00", "Z")
    except Exception:
        pass
    with open(prov_path, "w") as f:
        json.dump(prov_dict, f, indent=2)
    print(f"  Provenance saved to: {prov_path}")
    print()

    # 2. DATA VALIDATION
    print("2. DATA QUALITY VALIDATION")
    print("-" * 50)
    is_valid = validate_data(df)
    print(f"✓ Data validation: {'PASSED' if is_valid else 'FAILED'}")
    print()

    # 3. POINT-IN-TIME (PIT) VALIDATION
    print("3. POINT-IN-TIME VALIDATION & LOOK-AHEAD BIAS DETECTION")
    print("-" * 50)
    # Build strategy signals for PIT validation
    strategy = build_strategy("sma_crossover", '{"fast_period": 20, "slow_period": 50}')
    signals = strategy.generate_signals(df)
    pit_result = validate_point_in_time(df.copy(), signal_column="_pit_check")
    # Simpler check using validate_point_in_time directly on data
    pit_result = validate_point_in_time(df, lookback_windows=[20, 50])
    print("PIT validation results:")
    print(f"  Passed: {pit_result['passed']}")
    print(f"  Violations: {len(pit_result['violations'])}")
    print(f"  Warnings: {len(pit_result['warnings'])}")
    for v in pit_result["violations"]:
        print(f"    - {v}")
    for w in pit_result["warnings"]:
        print(f"    - {w}")
    print()

    # 4. SURVIVORSHIP BIAS DETECTION (Multi-asset example)
    print("4. SURVIVORSHIP BIAS DETECTION")
    print("-" * 50)
    # Create synthetic multi-asset panel to demonstrate detection
    dates = pd.date_range("2018-01-01", periods=252, freq="B")
    data_dict = {}
    # Symbol 1: Survives entire period
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.015, 252)
    prices = 100 * np.exp(np.cumsum(rets))
    df_survive = pd.DataFrame({
        "open": prices * 0.999, "high": prices * 1.005,
        "low": prices * 0.995, "close": prices, "volume": 1_000_000
    }, index=dates)
    data_dict["SURVIVE"] = df_survive

    # Symbol 2: Enters mid-period (IPO-like)
    rets2 = rng.normal(0.0005, 0.015, 150)
    prices2 = 90 * np.exp(np.cumsum(rets2))
    df_enter = pd.DataFrame({
        "open": prices2 * 0.999, "high": prices2 * 1.005,
        "low": prices2 * 0.995, "close": prices2, "volume": 800_000
    }, index=dates[102:])  # starts ~mid-2018
    data_dict["ENTER"] = df_enter

    surv_res = detect_survivorship_bias(data_dict)
    print(f"✓ Survivorship analysis complete (bias score: {surv_res['bias_score']:.3f})")
    print(f"  Surviving symbols: {surv_res['surviving_symbols']}")
    print(f"  Entered symbols: {len(surv_res['entered_symbols'])}")
    print(f"  Exited symbols: {len(surv_res['exited_symbols'])}")
    print(f"  Insufficient data: {len(surv_res['insufficient_data'])}")
    print(f"  Large gaps: {len(surv_res['large_gaps'])}")
    surv_path = out_dir / "survivorship_bias_report.json"
    with open(surv_path, "w") as f:
        json.dump(surv_res, f, indent=2, default=str)
    print(f"  Report saved to: {surv_path}")
    print()

    # 5. RUN BACKTEST WITH REALISTIC COSTS
    print("5. RUNNING BACKTEST WITH TRANSACTION COSTS")
    print("-" * 50)
    strategy = build_strategy("sma_crossover", '{"fast_period": 20, "slow_period": 50}')
    signals = strategy.generate_signals(df)
    positions = signals.shift(1).fillna(0)  # Enter next day
    # Compute returns
    returns = df["close"].pct_change().fillna(0)
    strategy_returns = positions * returns
    # Apply costs: 2 bps commission + 1 bps slippage per trade
    position_changes = positions.diff().abs().fillna(0)
    costs = position_changes * (0.0002 + 0.0001)  # 3 bps
    strategy_returns_net = strategy_returns - costs
    print(f"✓ Backtest complete on {len(df)} periods")
    print(f"  Strategy: SMA Crossover (20/50)")
    print(f"  Transaction costs: 3 bps per trade")
    print(f"  Total trades: {int(position_changes.sum())}")
    print()

    # 6. BENCHMARK COMPARISON (BUY-AND-HOLD) WITH COSTS
    print("6. BENCHMARK COMPARISON (BUY-AND-HOLD)")
    print("-" * 50)
    bench_type = _detect_benchmark_total_return_type(df)
    bench_rets = _compute_benchmark_total_return(df).dropna()
    print(f"✓ Benchmark computed (return type: {bench_type})")
    print(f"  Uses dividends/adj_close if available; falls back to price returns")
    print(f"  Benchmark costs modeled (entry+exit round-trip by default)")
    print()

    # 7. PERFORMANCE METRICS WITH STATISTICAL SIGNIFICANCE
    print("7. COMPUTING PERFORMANCE METRICS")
    print("-" * 50)
    results = {
        'returns': strategy_returns_net,
        'benchmark': bench_rets,
        'config': {'total_return_benchmark': False}
    }
    metrics = calculate_metrics(results, risk_free_rate=0.02)
    print("✓ Metrics calculated")
    print(f"  Total Return: {metrics['total_return']:.2%}")
    print(f"  Annualized Return: {metrics['annualized_return']:.2%}")
    print(f"  Annualized Volatility: {metrics['annualized_volatility']:.2%}")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio: {metrics['sortino_ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['max_drawdown']:.2%}")
    print(f"  Calmar Ratio: {metrics['calmar_ratio']:.2f}")
    if 'correlation_with_benchmark' in metrics:
        print(f"  Correlation w/ Benchmark: {metrics['correlation_with_benchmark']:.3f}")
        print(f"  Alpha (annualized): {metrics['alpha']:.2%}")
        print(f"  Beta: {metrics['beta']:.3f}")
        if metrics.get('alpha_t_stat') is not None:
            print(f"  Alpha t-stat: {metrics['alpha_t_stat']:.3f}")
            print(f"  Alpha p-value: {metrics['alpha_p_value']:.4f}")
    print()

    # 8. GENERATE REPORTS AND TEAR SHEETS
    print("8. GENERATING REPORTS AND TEAR SHEETS")
    print("-" * 50)
    generate_report(metrics, out_dir, symbol="SPY", strategy_name="SMA Crossover (20/50)")
    print(f"✓ Text report saved to: {out_dir / "report.txt"}")

    # Generate tear sheet
    equity_curve = (1 + strategy_returns_net).cumprod() * 100000  # hypothetical capital
    try:
        tear_sheet_path = out_dir / "tear_sheet.html"
        ts_results = {
            "equity_curve": equity_curve,
            "returns": strategy_returns_net,
            "data": df,
            "config": {"initial_capital": 100000},
        }
        ts_html = generate_tear_sheet(
            ts_results,
            metrics,
            tear_sheet_path.parent,
            symbol="SPY",
            strategy_name="SMA Crossover (20/50)",
        )
        print(f"✓ Tear sheet saved to: {ts_html}")
    except Exception as e:
        print(f"⚠ Tear sheet generation skipped: {e}")
    print()

    # Save metrics
    metrics_path = out_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump({k: (float(v) if isinstance(v, (np.integer, np.floating)) and not isinstance(v, bool) else v) for k, v in metrics.items()}, f, indent=2)
    print(f"✓ Metrics saved to: {metrics_path}")
    print()

    print("=" * 80)
    print("FULL PIPELINE EXAMPLE COMPLETE")
    print("=" * 80)
    print(f"All outputs saved to: {out_dir}")
    print()


if __name__ == "__main__":
    run_full_pipeline()
