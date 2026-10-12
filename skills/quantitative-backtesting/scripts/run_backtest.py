#!/usr/bin/env python3
"""
Main entry point for running backtests with configurable parameters.

This script provides a command-line interface for running backtests
with various strategies, data sources, and configuration options.
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_loader import load_data, validate_data
from scripts.strategy_builder import build_strategy
from scripts.performance import calculate_metrics, generate_report
from scripts.reporting import generate_tear_sheet


def parse_args():
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (bps)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (bps)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"Loading data from {args.data}...")
    data = load_data(args.data, symbol=args.symbol, start=args.start, end=args.end)

    if not validate_data(data):
        print("Data validation failed!")
        return 1

    print(f"Building strategy: {args.strategy}...")
    strategy = build_strategy(args.strategy, args.params)

    print("Running backtest...")
    # This would use vectorbt or similar for actual backtesting
    # For now, we simulate the workflow
    results = run_backtest(data, strategy, args)

    print("Calculating performance metrics...")
    metrics = calculate_metrics(results)

    print("Generating report...")
    generate_report(metrics, args.output)
    generate_tear_sheet(results, metrics, args.output)

    print(f"Backtest complete! Results saved to {args.output}/")
    return 0


def run_backtest(data, strategy, args):
    """Placeholder for actual backtest execution."""
    # In a real implementation, this would use vectorbt:
    # import vectorbt as vbt
    # pf = vbt.Portfolio.from_signals(...)
    # return pf

    return {
        "data": data,
        "strategy": strategy,
        "config": vars(args)
    }


if __name__ == "__main__":
    sys.exit(main())