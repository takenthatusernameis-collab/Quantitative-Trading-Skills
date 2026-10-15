#!/usr/bin/env python3
"""
Example demonstrating deflated alpha with multiple benchmarks.

This example shows how multiple-testing correction for benchmark alpha
works when comparing against multiple benchmarks (e.g., comparing a
strategy against SPY, QQQ, IWM, etc.). Testing against multiple
benchmarks increases the chance of finding spurious alpha purely by luck;
the Deflated Alpha Ratio corrects for this selection bias.

All data comes from the included sample data - no external network access required.
"""

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Add scripts to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import load_data
from strategy_builder import build_strategy
from performance import calculate_metrics, generate_report, _benchmark_stats
from walk_forward import deflated_alpha_ratio, _annualization_factor


def run_multiple_benchmarks_example():
    """Demonstrate deflated alpha with multiple benchmarks."""
    print("=" * 80)
    print("QUANTITATIVE BACKTESTING: MULTIPLE BENCHMARKS & DEFLATED ALPHA EXAMPLE")
    print("=" * 80)
    print()

    # Configuration
    data_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    bench_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_benchmark.csv"
    out_dir = Path(__file__).resolve().parent / "example_output"
    out_dir.mkdir(exist_ok=True)

    # Load strategy data
    print("1. LOADING STRATEGY DATA")
    print("-" * 50)
    df = load_data(str(data_path), symbol="SPY")
    print(f"✓ Loaded strategy data: {len(df)} rows")

    # Build and run strategy
    strategy = build_strategy("sma_crossover", json.dumps({"fast_period": 20, "slow_period": 50}))
    signals = strategy.generate_signals(df)
    positions = signals.shift(1).fillna(0)  # Enter next day (no look-ahead)
    price_returns = df["close"].pct_change().fillna(0)
    strategy_returns = positions * price_returns
    # Apply costs: 2 bps commission + 1 bps slippage per trade
    position_changes = positions.diff().abs().fillna(0)
    costs = position_changes * (0.0002 + 0.0001)  # 3 bps
    returns = strategy_returns - costs
    n_trades = int((position_changes > 0).sum())
    print(f"✓ Strategy backtested: {len(returns)} periods, {n_trades} trades")
    print()

    # Load multiple benchmarks
    print("2. LOADING MULTIPLE BENCHMARKS")
    print("-" * 50)
    bench1 = load_data(str(data_path), symbol="SPY")  # Same as strategy universe
    bench2 = load_data(str(bench_path), symbol="SPY")  # Synthetic alternative
    bench1_rets = bench1["close"].pct_change().dropna()
    bench2_rets = bench2["close"].pct_change().dropna()
    print(f"✓ Loaded 2 benchmarks: bench1 ({len(bench1_rets)} returns), bench2 ({len(bench2_rets)} returns)")

    # Compute metrics with multiple benchmarks
    print("\n3. COMPUTING METRICS WITH MULTIPLE BENCHMARKS")
    print("-" * 50)
    metrics = calculate_metrics({
        "returns": returns,
        "benchmark_list": [bench1_rets, bench2_rets],  # Multiple benchmark return Series
        "config": {
            "commission": 0.0002,
            "slippage": 0.0001,
            "benchmark_commission": 0.0002,
            "benchmark_slippage": 0.0001,
        }
    })
    print("✓ Metrics computed with multiple-benchmark correction")
    print()

    # Display deflated alpha results
    print("4. DEFLATED ALPHA (MULTIPLE-TESTING CORRECTION)")
    print("-" * 50)
    if "deflated_alpha" in metrics:
        da = metrics["deflated_alpha"]
        print(f"Alpha (estimated):           {da['alpha']:.2%}")
        print(f"Expected Max Alpha (luck):   {da['expected_max_alpha']:.4%}")
        print(f"Deflated Alpha Ratio (DAR):  {da['deflated_alpha_ratio']:.4f}")
        print(f"P-value (DAR):               {da['p_value']:.4f}")
        print(f"Z-score:                      {da['z_score']}")
        print(f"Number of Benchmarks (N):    {da['n_benchmarks']}")
        print(f"Observations (T):            {da['n_observations']}")
        print(f"Skewness/Kurtosis:           {da['skewness']:.3f}/{da['kurtosis']:.3f}")
        print()
        print("Interpretation:")
        print("  - DAR represents probability that true alpha > max alpha from luck")
        print("  - Higher N (more benchmarks tested) increases expected max alpha")
        print("  - Non-normality (skew/kurt) is accounted for in the correction")
    else:
        print("⚠ Deflated alpha not computed (insufficient data or error)")
    print()

    # Demonstrate direct function usage
    print("5. DIRECT DEFLATED ALPHA FUNCTION USAGE")
    print("-" * 50)
    # Collect trial alphas from each benchmark for the cross-sectional estimator
    bench_alphas = []
    ann_factor = _annualization_factor(returns.index)
    for i, bench_rets_i in enumerate([bench1_rets, bench2_rets]):
        bench_stats = _benchmark_stats(returns, bench_rets_i, ann_factor)
        if "alpha" in bench_stats:
            bench_alphas.append(bench_stats["alpha"])
            print(f"  Benchmark {i+1} alpha: {bench_stats['alpha']:.2%}")
    print(f"  Trial alphas collected: {[f'{a:.2%}' for a in bench_alphas]}")
    print(f"  These trial alphas feed the cross-sectional alpha* estimator")
    print()

    # Save results
    metrics_path = out_dir / "multiple_benchmarks_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"✓ Metrics saved to: {metrics_path}")
    print()

    print("=" * 80)
    print("MULTIPLE BENCHMARKS EXAMPLE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_multiple_benchmarks_example()
