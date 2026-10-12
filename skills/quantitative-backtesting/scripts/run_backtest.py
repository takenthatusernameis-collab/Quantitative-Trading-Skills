#!/usr/bin/env python3
"""
Main entry point for running backtests with configurable parameters.

This script provides a command-line interface for running backtests
with various strategies, data sources, and configuration options.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_data, validate_data
from strategy_builder import build_strategy
from performance import calculate_metrics, generate_report
from reporting import generate_tear_sheet


def parse_args():
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")
    return parser.parse_args()


def run_backtest(data, strategy, args):
    """Run a vectorized backtest and return results with equity curve and trades."""
    signals = strategy.generate_signals(data)
    close = data["close"]

    # Guard against strategies that never take a position (e.g. a lookback
    # longer than the data window leaves every rolling indicator NaN, so the
    # signal stays flat at 0). Such strategies produce no trades and their
    # performance metrics are meaningless (division-by-zero Sharpe, etc.).
    if (signals != 0).sum() == 0:
        raise ValueError(
            "Strategy never takes a position for the given data and "
            "parameters. Reduce the lookback/period so the indicator is "
            "defined over at least part of the window."
        )

    # Trade at next period's open (avoid look-ahead bias)
    positions = signals.shift(1).fillna(0)
    raw_returns = close.pct_change()

    # Transaction costs: apply on position changes
    position_changes = positions.diff().abs()
    costs = position_changes * (args.commission + args.slippage)

    strategy_returns = positions * raw_returns - costs
    strategy_returns = strategy_returns.dropna()

    # Build equity curve
    equity = (1 + strategy_returns).cumprod() * args.initial_capital
    equity.name = "equity"

    # Extract trade-level statistics
    position_changes_bool = positions.diff().fillna(0) != 0
    entry_mask = position_changes_bool & (positions != 0)
    exit_mask = position_changes_bool & (positions == 0)

    trades = []
    entry_idx = None
    entry_price = None
    entry_date = None
    for i in range(len(data)):
        if entry_mask.iloc[i] and entry_idx is None:
            entry_idx = i
            entry_price = close.iloc[i]
            entry_date = data.index[i]
        elif exit_mask.iloc[i] and entry_idx is not None:
            exit_price = close.iloc[i]
            exit_date = data.index[i]
            pnl = (exit_price - entry_price) * (positions.iloc[entry_idx] / abs(positions.iloc[entry_idx]))
            trades.append({
                "pnl": float(pnl),
                "return": float(pnl / entry_price),
                "entry_date": str(entry_date.date()),
                "exit_date": str(exit_date.date()),
            })
            entry_idx = None
            entry_price = None
            entry_date = None

    return {
        "equity_curve": equity,
        "returns": strategy_returns,
        "data": data,
        "strategy": strategy,
        "trades": trades,
        "config": {
            "initial_capital": args.initial_capital,
            "commission": args.commission,
            "slippage": args.slippage,
            "strategy": args.strategy,
            "symbol": args.symbol,
        },
    }


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
    results = run_backtest(data, strategy, args)

    print("Calculating performance metrics...")
    metrics = calculate_metrics(results)

    print("Generating report...")
    generate_report(metrics, args.output, symbol=args.symbol, strategy_name=args.strategy)
    generate_tear_sheet(results, metrics, args.output, symbol=args.symbol, strategy_name=args.strategy)

    print(f"Backtest complete! Results saved to {args.output}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())