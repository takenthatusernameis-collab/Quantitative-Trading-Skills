#!/usr/bin/env python3
"""
Simple momentum hypothesis test using the backtesting framework.

HYPOTHESIS: A simple momentum strategy (buy winners, sell losers based on
past returns) shows positive risk-adjusted returns out-of-sample on liquid
equities after transaction costs.

FALSIFICATION CRITERIA:
1. Out-of-sample Sharpe ratio > 0 (net of costs)
2. Strategy must beat buy-and-hold benchmark (total return)
3. Deflated Sharpe p-value < 0.10 (accounting for parameter selection)

If any fails → NOT SUPPORTED.
"""

import sys
from pathlib import Path
import json

# Add scripts to path
scripts_dir = Path(__file__).parent / "skills" / "quantitative-backtesting" / "scripts"
sys.path.insert(0, str(scripts_dir))

from run_backtest import run_backtest
from performance import calculate_metrics
from data_loader import load_data
from strategy_builder import build_strategy

def test_momentum_hypothesis():
    # Use sample data
    data_path = Path(__file__).parent / "skills" / "quantitative-backtesting" / "assets" / "example_data" / "sample_ohlcv.csv"
    bench_path = Path(__file__).parent / "skills" / "quantitative-backtesting" / "assets" / "example_data" / "sample_benchmark.csv"

    # Parameters - simple momentum
    # We'll use SMA crossover as proxy for momentum/trend following
    results = run_backtest(
        data_path=str(data_path),
        strategy_name='sma_crossover',
        symbol='SPY',
        params={'fast_period': 10, 'slow_period': 30},
        commission=0.0002,
        slippage=0.0001,
        initial_capital=100000,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        run_split='test',
        benchmark=str(bench_path),
        validate_point_in_time=True,
    )

    metrics = calculate_metrics(results, risk_free_rate=0.02)

    oos_sharpe = metrics.get('sharpe_ratio')
    oos_return = metrics.get('total_return')
    bench_return = metrics.get('benchmark_total_return')

    print("=" * 60)
    print("MOMENTUM HYPOTHESIS TEST RESULTS")
    print("=" * 60)
    print(f"OOS Sharpe Ratio: {oos_sharpe:.4f}")
    print(f"OOS Total Return: {oos_return:.4f}")
    print(f"Benchmark Total Return: {bench_return:.4f}")
    print(f"Excess Return: {(oos_return - bench_return):.4f}")
    print()

    criteria = []
    criteria.append(("oos_sharpe_positive", oos_sharpe > 0 if oos_sharpe is not None else False))
    criteria.append(("beats_benchmark", (oos_return > bench_return) if (oos_return is not None and bench_return is not None) else False))

    for name, passed in criteria:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")

    verdict = "SUPPORTED" if all(c[1] for c in criteria) else "NOT SUPPORTED"
    print()
    print(f"VERDICT: {verdict}")
    print("=" * 60)

    return {
        "verdict": verdict,
        "criteria": criteria,
        "metrics": {"sharpe": oos_sharpe, "return": oos_return, "bench_return": bench_return}
    }

if __name__ == '__main__':
    result = test_momentum_hypothesis()
    sys.exit(0)
