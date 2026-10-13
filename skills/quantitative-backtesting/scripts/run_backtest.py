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

import numpy as np
import pandas as pd

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
    parser.add_argument("--impact-coefficient", type=float, default=0.0, help="Market impact coefficient (position_notional/ADV * coefficient). 0 to disable.")
    parser.add_argument("--adv-window", type=int, default=20, help="Rolling window for Average Daily Volume calculation")
    parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3% per year)")
    parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2% per year)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")
    parser.add_argument("--n-trials", type=int, default=None, help="Number of development trials (parameter configurations) tested; when set, report the Deflated Sharpe Ratio (multiple-testing correction) for the final Sharpe")
    return parser.parse_args()


def run_backtest(data, strategy, args):
    """Run a vectorized backtest and return results with equity curve and trades."""
    signals = strategy.generate_signals(data)
    if isinstance(data, dict):
        common_index = None
        for df in data.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)
        common_index = common_index.sort_values()
        close_list = []
        vol_list = []
        for df in data.values():
            aligned = df.reindex(common_index)
            close_list.append(aligned["close"])
            vol_list.append(aligned["volume"])
        close = pd.concat(close_list, axis=1).mean(axis=1)
        volume = pd.concat(vol_list, axis=1).mean(axis=1)
    elif isinstance(data.columns, pd.MultiIndex):
        close = data["close"].mean(axis=1)
        volume = data["volume"].mean(axis=1)
    else:
        close = data["close"]
        volume = data["volume"]

    # Guard against strategies that never take a position (e.g. a lookback
    # longer than the data window leaves every rolling indicator NaN, so the
    # signal stays flat at 0). Such strategies produce no trades and their
    # performance metrics are meaningless (division-by-zero Sharpe, etc.).
    if not signals_active(signals):
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

    # Market impact model: impact = (position_notional / ADV) * impact_coefficient
    # Position notional = |position| * price (equity value of the position)
    # ADV = rolling average of daily volume (in shares) * price
    if args.impact_coefficient > 0 and volume is not None:
        # Average Daily Volume in shares (rolling)
        adv_shares = volume.rolling(window=args.adv_window, min_periods=1).mean()
        # Average Daily Volume in notional (shares * price)
        adv_notional = adv_shares * close
        # Position notional = |position| * equity (we approximate with close price * initial_capital)
        # Since we don't have equity at this level, we use position * close as a proxy
        # The cost is applied as a fraction of notional on position changes
        position_notional = position_changes * close
        # Market impact as fraction of notional traded
        market_impact = (position_notional / adv_notional.replace(0, np.nan)) * args.impact_coefficient
        market_impact = market_impact.fillna(0)
        costs = costs + market_impact

    # Borrow cost for short positions
    # Applied daily on the absolute value of short positions
    if args.borrow_cost > 0:
        # Convert annual rate to per-period rate
        ann_factor = 252  # trading days per year
        daily_borrow_rate = args.borrow_cost / ann_factor
        # Short positions are negative; borrow cost applies to absolute short exposure
        short_positions = positions.clip(upper=0).abs()
        borrow_costs = short_positions * daily_borrow_rate
        costs = costs + borrow_costs

    # Funding cost for leveraged positions (gross exposure > 1)
    # Applied daily on the amount of leverage used beyond 100% equity
    if args.funding_cost > 0:
        # Convert annual rate to per-period rate
        ann_factor = 252  # trading days per year
        daily_funding_rate = args.funding_cost / ann_factor
        # Gross leverage = absolute position size
        gross_exposure = positions.abs()
        # Funding cost applies to leverage beyond 1x (i.e., gross_exposure - 1 when > 1)
        leverage_excess = (gross_exposure - 1).clip(lower=0)
        funding_costs = leverage_excess * daily_funding_rate
        costs = costs + funding_costs

    strategy_returns = positions * raw_returns - costs
    strategy_returns = strategy_returns.dropna()

    # Build equity curve
    equity = (1 + strategy_returns).cumprod() * args.initial_capital
    equity.name = "equity"

    # Extract trade-level statistics.
    #
    # A trade boundary is any bar where the position changes. We must close the
    # previously open position and open a new one at that same bar. This matters
    # for long/short strategies that flip directly between +1 and -1 (e.g.
    # Bollinger Bands, Donchian Breakout, RSI mean reversion): a flip is a
    # position change but never reaches 0, so an exit-only heuristic would
    # silently leak the long leg and never record the short leg. Costs for the
    # round turn are already accounted for by `position_changes` above.
    position_changes_bool = positions.diff().fillna(0) != 0

    # Trade extraction must iterate over the position series, not
    # `data`: for dict panel data `len(data)` is the number of
    # symbols (not bars) and `data.index` does not exist, which
    # crashed the extractor or silently dropped every trade.
    # `positions`, `close` and the trade ledger all share the
    # common date index for single-asset, MultiIndex and dict
    # panel formats alike.
    n_bars = len(position_changes_bool)

    trades = []
    entry_idx = None
    entry_price = None
    entry_date = None
    entry_direction = None  # +1 for long, -1 for short
    for i in range(n_bars):
        if not position_changes_bool.iloc[i]:
            continue

        # Close any currently open position at this bar's price.
        if entry_idx is not None:
            exit_price = close.iloc[i]
            exit_date = positions.index[i]
            pnl = (exit_price - entry_price) * entry_direction
            trades.append({
                "pnl": float(pnl),
                "return": float(pnl / entry_price),
                "entry_date": str(entry_date.date()),
                "exit_date": str(exit_date.date()),
            })
            entry_idx = None
            entry_price = None
            entry_date = None
            entry_direction = None

        # Open the new position at this bar's price (if it is non-zero).
        new_pos = positions.iloc[i]
        if new_pos != 0:
            entry_idx = i
            entry_price = close.iloc[i]
            entry_date = positions.index[i]
            entry_direction = 1 if new_pos > 0 else -1

    # Mark the final open position to market at the last bar's close.
    # A strategy still holding a position when the data ends (common
    # for long-lookback momentum strategies) would otherwise record no
    # trade at all for that leg: its PnL is in the equity curve but
    # missing from the trade ledger, so trade-level stats (win rate,
    # expectancy, profit factor) understate activity and do not
    # reconcile with the equity curve. The exit is forced by the end
    # of the sample, not by a signal, so it is flagged via
    # `closed_at_end`. A position opened on the very last bar has no
    # later bar to close at and is left unrecorded.
    if entry_idx is not None and entry_idx < n_bars - 1:
        exit_price = close.iloc[-1]
        exit_date = positions.index[-1]
        pnl = (exit_price - entry_price) * entry_direction
        trades.append({
            "pnl": float(pnl),
            "return": float(pnl / entry_price),
            "entry_date": str(entry_date.date()),
            "exit_date": str(exit_date.date()),
            "closed_at_end": True,
        })

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
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "strategy": args.strategy,
            "symbol": args.symbol,
            "n_trials": getattr(args, "n_trials", None),
        },
    }


def signals_active(signals: pd.Series) -> bool:
    """Return True if the signal series ever takes a non-zero position.

    A strategy that never takes a position (e.g. a lookback longer than the
    data window leaves every rolling indicator NaN, so the signal stays flat
    at 0) produces no trades and meaningless zero returns. Callers should
    skip such parameter sets rather than ranking them as "optimal".

    NaN values are explicitly excluded: a signal that is entirely NaN
    (e.g., from an indicator with a lookback longer than the data) is
    treated as flat, not active.
    """
    return bool((signals.notna() & (signals != 0)).any())


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

    # Multiple-testing correction: when the number of development
    # trials was reported (--n-trials), echo the Deflated Sharpe
    # Ratio that calculate_metrics attached to the metrics.
    dsr = metrics.get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

    print("Generating report...")
    generate_report(metrics, args.output, symbol=args.symbol, strategy_name=args.strategy)
    generate_tear_sheet(results, metrics, args.output, symbol=args.symbol, strategy_name=args.strategy)

    print(f"Backtest complete! Results saved to {args.output}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())