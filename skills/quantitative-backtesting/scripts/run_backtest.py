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
from typing import Dict, Any

import numpy as np
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import (
    load_data,
    validate_data,
    load_multi_symbol,
    validate_point_in_time,
    detect_survivorship_bias,
    _compute_benchmark_total_return,
)
from strategy_builder import build_strategy
from performance import calculate_metrics, generate_report
from reporting import generate_tear_sheet
from utils import _annualization_factor
from walk_forward import estimate_capacity


def parse_args():
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    parser.add_argument("--commissions", type=float, nargs="+", default=None, help="List of commissions to sweep (overrides --commission)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    parser.add_argument("--slippages", type=float, nargs="+", default=None, help="List of slippages to sweep (overrides --slippage)")
    parser.add_argument("--impact-coefficient", type=float, default=0.0, help="Market impact coefficient (position_notional/ADV * coefficient). 0 to disable.")
    parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="List of market impact coefficients to sweep (overrides --impact-coefficient).")
    parser.add_argument("--adv-window", type=int, default=20, help="Rolling window for Average Daily Volume calculation")
    parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3%% per year)")
    parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="List of annual borrow costs to sweep (overrides --borrow-cost).")
    parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2%% per year)")
    parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="List of annual funding costs to sweep (overrides --funding-cost).")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")
    parser.add_argument("--n-trials", type=int, default=None, help="Number of development trials (parameter configurations) tested; when set, report the Deflated Sharpe Ratio (multiple-testing correction) for the final Sharpe")
    parser.add_argument("--risk-free-rate", type=float, default=None, help="Annual risk-free rate (as decimal, e.g., 0.02 for 2%%)")
    parser.add_argument("--validate-point-in-time", action="store_true", help="Run point-in-time validation on the loaded data and strategy signals (temporal ordering, duplicate timestamps, signal/next-return correlation for look-ahead bias screening)")
    parser.add_argument("--point-in-time-strict", action="store_true", help="Abort with a non-zero exit code when point-in-time validation finds violations (default: warn only)")
    parser.add_argument("--multi-symbol", action="store_true", help="Load every symbol in a multi-symbol file (with a 'symbol' or 'ticker' column) as a panel, run survivorship-bias detection, and backtest a panel. Requires a panel strategy such as cross_sectional_momentum or dual_momentum.")
    parser.add_argument("--benchmark", type=str, nargs="+", default=None, help="Path to benchmark OHLCV file(s) (e.g. SPY QQQ) for buy-and-hold baseline comparison (alpha/beta, correlation)")
    parser.add_argument("--benchmark-name", type=str, nargs="+", default=None, help="Optional name(s) for each benchmark (corresponding to --benchmark order). If omitted, derived from filename.")
    parser.add_argument("--benchmark-names", type=str, nargs="+", default=None, help="Alias for --benchmark-name (optional).")
    parser.add_argument("--total-return-benchmark", action="store_true", help="Compute benchmark returns using total return (dividends + price) when dividend/adj_close data is available, instead of price-only returns (applies to all benchmarks)")
    parser.add_argument("--benchmark-commission", type=float, default=None, help="Commission per trade for benchmark (as decimal). Defaults to strategy commission if not specified (applies to all benchmarks).")
    parser.add_argument("--benchmark-slippage", type=float, default=None, help="Slippage per trade for benchmark (as decimal). Defaults to strategy slippage if not specified (applies to all benchmarks).")
    parser.add_argument("--benchmark-expense-ratio", type=float, default=None, help="Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%). Defaults to 0 (applies to all benchmarks).")
    parser.add_argument("--benchmark-cost-is-periodic", action="store_true", help="If set, apply benchmark trading costs (commission+slippage) as periodic deductions each period instead of as a round-trip cost on total return (applies to all benchmarks).")
    parser.add_argument("--latency", type=int, default=0, help="Execution latency in periods (0 = no delay, 1 = one period delay). Delays position execution by latency periods after signal generation.")
    parser.add_argument("--fill-rate", type=float, default=1.0, help="Execution fill rate (0 < r <= 1); only this fraction of each targeted position change is filled, scaling the achieved position and all transaction costs proportionally. Default 1.0 (full fill, backward compatible).")
    parser.add_argument("--fill-rates", type=float, nargs="+", default=None, help="List of fill rates to sweep (overrides --fill-rate).")
    parser.add_argument("--latencies", type=int, nargs="+", default=None, help="List of execution latencies (in periods) to sweep (overrides --latency). Delays position execution by each latency after signal generation.")
    parser.add_argument("--adjust-splits", action="store_true", help="Adjust prices for stock splits using the splits column if present.")
    return parser.parse_args()


def _validate_point_in_time(data, signals) -> Dict[str, Any]:
    """Run point-in-time validation on the loaded data and signals.

    Single-asset data is validated together with the signal series so
    the signal/next-return correlation check can screen for look-ahead
    bias. Panel data (dict or MultiIndex columns) has no single signal
    column, so each symbol frame is validated for structural violations
    (temporal ordering, duplicate timestamps) instead.
    """
    if isinstance(data, pd.DataFrame) and not isinstance(data.columns, pd.MultiIndex):
        check_df = data.copy()
        check_df["_pit_signal"] = signals
        result = validate_point_in_time(check_df, signal_column="_pit_signal")
        # The internal signal column is not user data: warnings about
        # long runs of identical values are an artifact of the check
        # (signals are sticky by design), not stale data.
        result["warnings"] = [
            w for w in result["warnings"] if "_pit_signal" not in w
        ]
        return result

    frames = list(data.values()) if isinstance(data, dict) else [data]
    combined: Dict[str, Any] = {"passed": True, "violations": [], "warnings": []}
    for df in frames:
        result = validate_point_in_time(df)
        combined["passed"] = combined["passed"] and result["passed"]
        combined["violations"].extend(result["violations"])
        combined["warnings"].extend(result["warnings"])
    return combined


def _handle_point_in_time_results(pit_result: Dict[str, Any], strict: bool) -> bool:
    """Print point-in-time validation results to the log.

    Returns True when the run must abort (strict mode with violations).
    """
    if pit_result["violations"]:
        print("Point-in-time validation violations:")
        for violation in pit_result["violations"]:
            print(f"  - {violation}")
    if pit_result["warnings"]:
        print("Point-in-time validation warnings:")
        for warning in pit_result["warnings"]:
            print(f"  - {warning}")
    if not pit_result["violations"] and not pit_result["warnings"]:
        print("Point-in-time validation passed (no violations or warnings).")
    elif not pit_result["violations"]:
        print("Point-in-time validation passed (no violations).")
    if strict and not pit_result["passed"]:
        print("Point-in-time validation failed in strict mode; aborting.")
        return True
    return False


def _print_survivorship_report(survivorship: Dict[str, Any]) -> None:
    """Print a survivorship-bias detection report to the log."""
    print("Survivorship bias detection:")
    print(f"  bias_score: {survivorship['bias_score']:.3f}")
    print(f"  surviving symbols: {len(survivorship['surviving_symbols'])}")
    for entry in survivorship["entered_symbols"]:
        print(
            f"  entered after sample start: {entry['symbol']} "
            f"({entry['days_after_global_start']} days late)"
        )
    for entry in survivorship["exited_symbols"]:
        print(
            f"  exited before sample end: {entry['symbol']} "
            f"({entry['days_before_global_end']} days early)"
        )
    for symbol in survivorship["insufficient_data"]:
        print(f"  insufficient observations: {symbol}")
    for entry in survivorship["large_gaps"]:
        print(
            f"  large data gap: {entry['symbol']} "
            f"(max {entry['max_gap_days']} days)"
        )


def run_backtest(data, strategy, args, data_provenance=None, benchmark=None, survivorship=None):
    """Run a vectorized backtest and return results with equity curve and trades.

    data_provenance: optional DataProvenance (or dict of them for
        multi-symbol panels) captured at load time; serialized into
        the results so the backtest is reproducible.
    benchmark: optional DataFrame of benchmark OHLCV indexed by date
        (e.g. a market index or buy-and-hold baseline). When provided,
        buy-and-hold returns are computed from the benchmark close,
        aligned to the strategy returns index on common trading dates,
        and attached as ``results["benchmark"]`` so
        ``calculate_metrics`` can report alpha/beta/correlation vs the
        market. The benchmark return for period t is the close-to-close
        return from t-1 to t (no shift), matching the strategy's
        next-period-open trading convention.
    """
    signals = strategy.generate_signals(data)

    # Optional point-in-time validation (look-ahead bias screening).
    # Recorded in the results so the check is reproducible downstream.
    pit_result = None
    if getattr(args, "validate_point_in_time", False):
        pit_result = _validate_point_in_time(data, signals)
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
            if "volume" in aligned.columns:
                vol_list.append(aligned["volume"])
        close = pd.concat(close_list, axis=1).mean(axis=1)
        volume = pd.concat(vol_list, axis=1).mean(axis=1) if vol_list else None
    elif isinstance(data.columns, pd.MultiIndex):
        close = data["close"].mean(axis=1)
        volume = data["volume"].mean(axis=1) if "volume" in data.columns.get_level_values(0) else None
    else:
        close = data["close"]
        volume = data["volume"] if "volume" in data.columns else None

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
    # Account for execution latency if specified (delay position execution by latency periods)
    latency = getattr(args, 'latency', 0) or 0
    if latency < 0:
        latency = 0
    # Account for partial execution fill rate (only a fraction of each
    # targeted position change is filled; scales position and costs)
    fill_rate = getattr(args, 'fill_rate', 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(
            f"--fill-rate must be in (0, 1], got {fill_rate}"
        )
    positions = signals.shift(1 + latency).fillna(0)
    if fill_rate < 1.0:
        positions = positions * fill_rate
    raw_returns = close.pct_change()

    # Transaction costs: apply on position changes
    position_changes = positions.diff().abs()
    costs = position_changes * (args.commission + args.slippage)

    # Market impact model: impact = (position_notional / ADV) * impact_coefficient
    # ADV = rolling average of daily volume (in shares) * price
    if args.impact_coefficient > 0 and volume is not None:
        # Average Daily Volume in shares (rolling)
        adv_shares = volume.rolling(window=args.adv_window, min_periods=1).mean()
        # Average Daily Volume in notional (shares * price)
        adv_notional = adv_shares * close
        # Position notional = |position_change| * equity, where equity is the
        # current portfolio value.  Since this function only sees returns (not
        # equity), equity is approximated by initial_capital * cumprod(1 +
        # raw_returns), i.e. the value of a fully-invested buy-and-hold position
        # in the asset at the current price.  This is the correct scaling: the
        # original implementation multiplied by the raw asset price (~$100),
        # understating the notional by ~1000x and making impact_coefficient a
        # silent no-op.  Mirrors _calculate_strategy_returns in walk_forward.py.
        equity = args.initial_capital * (1 + raw_returns).cumprod()
        position_notional = position_changes * equity
        # Market impact as fraction of notional traded
        market_impact = (position_notional / adv_notional.replace(0, np.nan)) * args.impact_coefficient
        market_impact = market_impact.fillna(0)
        costs = costs + market_impact

    # Borrow and funding costs are annualized rates applied per period.
    # The per-period rate divides by the number of periods per year
    # inferred from the data's index (e.g. 252 for business-daily,
    # 365 for calendar-daily, 52 for weekly, 12 for monthly), matching
    # the annualization used for the performance metrics. Falls back to
    # 252 when the frequency cannot be inferred.
    ann_factor = _annualization_factor(close.index)

    # Borrow cost for short positions
    # Applied per period on the absolute value of short positions
    if args.borrow_cost > 0:
        # Convert annual rate to per-period rate
        period_borrow_rate = args.borrow_cost / ann_factor
        # Short positions are negative; borrow cost applies to absolute short exposure
        short_positions = positions.clip(upper=0).abs()
        borrow_costs = short_positions * period_borrow_rate
        costs = costs + borrow_costs

    # Funding cost for leveraged positions (gross exposure > 1)
    # Applied per period on the amount of leverage used beyond 100% equity
    if args.funding_cost > 0:
        # Convert annual rate to per-period rate
        period_funding_rate = args.funding_cost / ann_factor
        # Gross leverage = absolute position size
        gross_exposure = positions.abs()
        # Funding cost applies to leverage beyond 1x (i.e., gross_exposure - 1 when > 1)
        leverage_excess = (gross_exposure - 1).clip(lower=0)
        funding_costs = leverage_excess * period_funding_rate
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

    results = {
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
            "risk_free_rate": getattr(args, "risk_free_rate", None),
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": getattr(args, "total_return_benchmark", False),
            "benchmark_commission": getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission,
            "benchmark_slippage": getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage,
            "benchmark_expense_ratio": getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            "latency": getattr(args, "latency", 0),
            "fill_rate": fill_rate,
        },
    }

    # Optional data provenance (the CLI captures DataProvenance at
    # load time) so results are reproducible from the artifacts.
    if data_provenance is not None:
        if isinstance(data_provenance, dict):
            results["data_provenance"] = {
                sym: prov.to_dict() for sym, prov in data_provenance.items()
            }
        else:
            results["data_provenance"] = data_provenance.to_dict()

    # Optional point-in-time validation outcome.
    if pit_result is not None:
        results["point_in_time_validation"] = pit_result

    # Optional survivorship-bias report artifact (multi-symbol panels).
    if survivorship is not None:
        results["survivorship_bias"] = survivorship

    # Bias-controls engagement flag (point-in-time validation and/or
    # survivorship screening on this path). Multiple-testing deflation
    # (Deflated Sharpe) is recorded separately in metrics; this flag is
    # about bias controls engaged during backtest setup/validation.
    if pit_result is not None or survivorship is not None:
        results["bias_controls_engaged"] = True

    # Surface market-impact capacity estimate in the results summary so the
    # single-backtest path reports capacity consistently with walk-forward/
    # CPCV/out-of-sample paths. Build a close/volume frame from the aligned
    # series (handles single-asset, MultiIndex and dict-panel inputs).
    try:
        _cap_frame = pd.DataFrame({"close": close, "volume": volume})
        _cap = estimate_capacity(_cap_frame, args.impact_coefficient, adv_window=args.adv_window)
        results["capacity"] = _cap.get("estimated_capacity")
    except Exception:
        results["capacity"] = None

    # Optional buy-and-hold benchmark baseline(s).
    # The benchmark return for period t is the close-to-close return
    # from t-1 to t (no shift): the strategy already trades at the next
    # period's open, so this is an apples-to-apples comparison window.
    # Align to the strategy returns index on common trading dates (inner
    # join handles a benchmark that is a strict superset of the strategy
    # date range without misaligning).
    # When multiple benchmarks are provided, each is processed separately.
    if benchmark is not None:
        # Handle multiple benchmarks
        if isinstance(benchmark, list):
            # Process each benchmark separately
            benchmark_results = []
            for i, bench in enumerate(benchmark):
                if getattr(args, "total_return_benchmark", False):
                    benchmark_returns = _compute_benchmark_total_return(bench)
                else:
                    benchmark_returns = bench["close"].pct_change()
                _, aligned_benchmark = strategy_returns.align(benchmark_returns, join="inner")
                if len(aligned_benchmark) > 0:
                    benchmark_results.append(aligned_benchmark)
                else:
                    benchmark_results.append(None)
            # When exactly one benchmark is provided, keep the single-benchmark
            # path so calculate_metrics() emits the non-prefixed keys
            # (alpha, beta, benchmark_total_return, ...) expected by
            # existing callers and tests. The multi-benchmark path
            # (benchmark_list + Deflated Alpha correction) is only used
            # when 2+ benchmarks are supplied.
            if len(benchmark_results) == 1 and benchmark_results[0] is not None:
                results["benchmark"] = benchmark_results[0]
            elif len(benchmark_results) > 1:
                results["benchmark_list"] = benchmark_results
        else:
            # Single benchmark (backward compatibility)
            if getattr(args, "total_return_benchmark", False):
                benchmark_returns = _compute_benchmark_total_return(benchmark)
            else:
                benchmark_returns = benchmark["close"].pct_change()
            _, aligned_benchmark = strategy_returns.align(benchmark_returns, join="inner")
            if len(aligned_benchmark) > 0:
                results["benchmark"] = aligned_benchmark

    return results


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


def _run_backtest_sweep_coefficient(args, data, strategy, provenance, benchmark,
                                   impact_coefficient=None, borrow_cost=None,
                                   funding_cost=None, commission=None,
                                   slippage=None, fill_rate=None,
                                   latency=None,
                                   survivorship=None):
    """Run backtest for a single cost coefficient.

    No file I/O or stdout; returns per-coefficient metrics dict.
    """
    if impact_coefficient is None:
        impact_coefficient = args.impact_coefficient
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if fill_rate is None:
        fill_rate = args.fill_rate
    if latency is None:
        latency = args.latency

    class SweepArgs:
        def __init__(self, base):
            for k, v in base.__dict__.items():
                setattr(self, k, v)
            self.impact_coefficient = impact_coefficient
            self.borrow_cost = borrow_cost
            self.funding_cost = funding_cost
            self.commission = commission
            self.slippage = slippage
            self.fill_rate = fill_rate
            self.latency = latency

    sweep_args = SweepArgs(args)
    results = run_backtest(data, strategy, sweep_args,
                           data_provenance=provenance, benchmark=benchmark, survivorship=survivorship)

    rfr = getattr(args, "risk_free_rate", None)
    metrics = calculate_metrics(results) if rfr is None else calculate_metrics(results, risk_free_rate=rfr)

    return {
        "impact_coefficient": impact_coefficient,
        "borrow_cost": borrow_cost,
        "funding_cost": funding_cost,
        "commission": commission,
        "slippage": slippage,
        "fill_rate": fill_rate,
        "latency": latency,
        "total_return": metrics.get("total_return", 0.0),
        "annualized_return": metrics.get("annualized_return", 0.0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
        "max_drawdown": metrics.get("max_drawdown", 0.0),
    }


def main():
    args = parse_args()

    print(f"Loading data from {args.data}...")
    survivorship = None
    if getattr(args, "multi_symbol", False):
        print("Multi-symbol mode: loading the full symbol universe...")
        data, provenance = load_multi_symbol(args.data, return_provenance=True)
        if not data:
            print("No symbols could be loaded from the multi-symbol file!")
            return 1
        survivorship = detect_survivorship_bias(data)
        _print_survivorship_report(survivorship)
        for sym, prov in provenance.items():
            print(
                f"  {sym}: {prov.final_shape[0]} rows, "
                f"checksum {prov.checksum}"
            )
    else:
        data, provenance = load_data(
            args.data,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            return_provenance=True,
            adjust_splits=getattr(args, "adjust_splits", False),
        )
        print(
            f"Loaded {provenance.final_shape[0]} rows x "
            f"{provenance.final_shape[1]} columns "
            f"(checksum {provenance.checksum})"
        )

    # Multi-symbol frames are validated per symbol inside
    # load_multi_symbol (failing symbols are dropped there).
    if not isinstance(data, dict) and not validate_data(data):
        print("Data validation failed!")
        return 1

    # Optional benchmark baseline (buy-and-hold comparison).
    # --benchmark accepts one or more paths (nargs="+"), so args.benchmark
    # is a list. Each path is loaded separately and the resulting
    # DataFrames are passed as a list to run_backtest(), which aligns
    # each one independently and supports multiple-testing correction
    # across benchmarks.
    benchmark = None
    benchmark_provenance = None
    benchmark_provenances = []
    benchmark_paths = getattr(args, "benchmark", None)
    if benchmark_paths:
        # Normalize to a list of paths for uniform handling.
        if isinstance(benchmark_paths, str):
            benchmark_paths = [benchmark_paths]
        benchmark_frames = []
        benchmark_provenances = []
        # Resolve benchmark names
        bench_names = getattr(args, "benchmark_names", None) or getattr(args, "benchmark_name", None)
        if bench_names:
            if len(bench_names) != len(benchmark_paths):
                # If lengths mismatch, try to be tolerant - pad/truncate
                if len(bench_names) < len(benchmark_paths):
                    bench_names = bench_names + [None] * (len(benchmark_paths) - len(bench_names))
                else:
                    bench_names = bench_names[:len(benchmark_paths)]
        else:
            bench_names = [None] * len(benchmark_paths)
        for i, path in enumerate(benchmark_paths):
            print(f"Loading benchmark data from {path}...")
            bench_df, bench_prov = load_data(path, return_provenance=True, adjust_splits=getattr(args, "adjust_splits", False))
            print(
                f"Loaded benchmark: {bench_prov.final_shape[0]} rows "
                f"(checksum {bench_prov.checksum}, "
                f"total_return_type: {bench_prov.total_return_type})"
            )
            if getattr(args, "total_return_benchmark", False):
                if bench_prov.total_return_type == "total":
                    print("Using total-return benchmark (dividends/adj_close included)")
                else:
                    print("Warning: --total-return-benchmark requested but benchmark data has no dividends/adj_close column; falling back to price-only returns")
            if not validate_data(bench_df):
                print("Benchmark data validation failed!")
                return 1
            # Attach name to provenance
            if hasattr(bench_prov, '__dict__'):
                name = bench_names[i]
                if name is None:
                    try:
                        name = Path(path).stem
                    except Exception:
                        name = str(path)
                try:
                    # Set attribute if possible
                    setattr(bench_prov, 'name', name)
                except Exception:
                    pass
            benchmark_frames.append(bench_df)
            benchmark_provenances.append(bench_prov)
        # Pass the list of benchmark DataFrames to run_backtest();
        # a single-element list is also accepted (backward compatible).
        benchmark = benchmark_frames if len(benchmark_frames) > 1 else benchmark_frames[0]
        # Keep all provenances (preserves traceability for multi-benchmark runs).
        benchmark_provenance = benchmark_provenances
        # Stash all provenances on args so downstream code can serialize them.
        args._benchmark_provenances = benchmark_provenances

    print(f"Building strategy: {args.strategy}...")
    strategy = build_strategy(args.strategy, args.params)


    # Cost sweeps: when a list of coefficients/costs is provided, run once per
    # value, write a sweep artifact, and return. Single-float behavior unchanged.
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if getattr(args, "impact_coefficients", None) is not None and len(args.impact_coefficients) > 1:
        sweep_results = []
        for coeff in args.impact_coefficients:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, coeff,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"impact_coefficients": args.impact_coefficients, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        # Print degradation table
        if sweep_results:
            print("\nImpact coefficient sweep:")
            print("coeff\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['impact_coefficient']:.4f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "borrow_costs", None) is not None and len(args.borrow_costs) > 1:
        sweep_results = []
        for cost in args.borrow_costs:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, args.impact_coefficient, borrow_cost=cost,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_borrow_cost_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"borrow_costs": args.borrow_costs, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nBorrow cost sweep:")
            print("cost\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['borrow_cost']:.4f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "funding_costs", None) is not None and len(args.funding_costs) > 1:
        sweep_results = []
        for cost in args.funding_costs:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_funding_cost_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"funding_costs": args.funding_costs, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nFunding cost sweep:")
            print("cost\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['funding_cost']:.4f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "commissions", None) is not None and len(args.commissions) > 1:
        sweep_results = []
        for cost in args.commissions:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, commission=cost,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"commissions": args.commissions, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nCommission sweep:")
            print("comm\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['commission']:.6f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "slippages", None) is not None and len(args.slippages) > 1:
        sweep_results = []
        for cost in args.slippages:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, slippage=cost,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"slippages": args.slippages, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nSlippage sweep:")
            print("slip\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['slippage']:.6f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "fill_rates", None) is not None and len(args.fill_rates) > 1:
        sweep_results = []
        for rate in args.fill_rates:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, fill_rate=rate,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_fill_rate_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"fill_rates": args.fill_rates, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nFill rate sweep:")
            print("rate\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['fill_rate']:.4f}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    if getattr(args, "latencies", None) is not None and len(args.latencies) > 1:
        sweep_results = []
        for lat in args.latencies:
            sweep_results.append(
                _run_backtest_sweep_coefficient(
                    args, data, strategy, provenance, benchmark, latency=lat,
                    survivorship=survivorship,
                )
            )
        sweep_path = output_dir / "run_backtest_latency_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump({"latencies": args.latencies, "results": sweep_results}, f, indent=2)
        print(f"Sweep results saved to: {sweep_path}")
        if sweep_results:
            print("\nLatency sweep:")
            print("lat\treturn\tann_ret\tSharpe\tmaxDD")
            for r in sweep_results:
                print(f"{r['latency']}\t{r['total_return']:.4f}\t{r['annualized_return']:.4f}\t{r['sharpe_ratio']:.4f}\t{r['max_drawdown']:.4f}")
        return 0

    print("Running backtest...")
    results = run_backtest(data, strategy, args, data_provenance=provenance, benchmark=benchmark, survivorship=survivorship)
    # Thread benchmark provenance through results for downstream serialization
    try:
        if benchmark_provenance is not None:
            results["benchmark_provenance"] = benchmark_provenance
    except Exception:
        pass

    # Surface point-in-time validation results in the logs and
    # abort in strict mode before investing more in the run.
    pit = results.get("point_in_time_validation")
    if pit is not None and _handle_point_in_time_results(
        pit, getattr(args, "point_in_time_strict", False)
    ):
        return 1

    print("Calculating performance metrics...")
    rfr = getattr(args, "risk_free_rate", None)
    metrics = calculate_metrics(results, risk_free_rate=rfr) if rfr is not None else calculate_metrics(results)
    metrics["capacity"] = results.get("capacity")

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

    # Persist provenance and survivorship artifacts alongside the
    # other outputs so the backtest can be reproduced and audited.
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    prov_path = output_dir / "data_provenance.json"
    prov_data = results.get("data_provenance")
    # Sanitize load_timestamp for reproducibility (use source file mtime if available)
    try:
        from datetime import datetime, UTC
        if isinstance(prov_data, dict):
            # Single symbol case or multi-symbol dict
            if all(isinstance(v, dict) for v in prov_data.values()) and len(prov_data) > 0:
                for k, v in prov_data.items():
                    sp = v.get("source_path") or v.get("source")
                    if sp and "load_timestamp" in v:
                        try:
                            v["load_timestamp"] = datetime.fromtimestamp(
                                Path(sp).stat().st_mtime, UTC
                            ).isoformat().replace("+00:00", "Z")
                        except Exception:
                            pass
            elif "source_path" in prov_data:
                sp = prov_data.get("source_path")
                if sp and "load_timestamp" in prov_data:
                    try:
                        prov_data["load_timestamp"] = datetime.fromtimestamp(
                            Path(sp).stat().st_mtime, UTC
                        ).isoformat().replace("+00:00", "Z")
                    except Exception:
                        pass
    except Exception:
        pass
    with open(prov_path, "w") as f:
        json.dump(prov_data, f, indent=2, default=str)
    print(f"Data provenance saved to: {prov_path}")

    if benchmark_provenance is not None or len(benchmark_provenances) > 0:
        bench_prov_path = output_dir / "benchmark_provenance.json"
        # Build the data
        bench_data = None
        if len(benchmark_provenances) == 1:
            bench_data = benchmark_provenances[0].to_dict()
        elif len(benchmark_provenances) > 1:
            bench_data = [p.to_dict() for p in benchmark_provenances]
        elif isinstance(benchmark_provenance, list):
            if len(benchmark_provenance) == 1:
                p = benchmark_provenance[0]
                bench_data = p.to_dict() if hasattr(p, 'to_dict') else p
            else:
                bench_data = [p.to_dict() if hasattr(p, 'to_dict') else p for p in benchmark_provenance]
        else:
            bp = benchmark_provenance
            bench_data = bp.to_dict() if hasattr(bp, 'to_dict') else bp
        # Sanitize
        try:
            from datetime import datetime, UTC
            def sanitize_b(d):
                if isinstance(d, dict):
                    sp = d.get("source_path")
                    if sp and "load_timestamp" in d:
                        try:
                            d["load_timestamp"] = datetime.fromtimestamp(
                                Path(sp).stat().st_mtime, UTC
                            ).isoformat().replace("+00:00", "Z")
                        except Exception:
                            pass
                return d
            if isinstance(bench_data, list):
                for b in bench_data:
                    sanitize_b(b)
            else:
                sanitize_b(bench_data)
        except Exception:
            pass
        with open(bench_prov_path, "w") as f:
            json.dump(bench_data, f, indent=2, default=str)
        print(f"Benchmark provenance saved to: {bench_prov_path}")

    if survivorship is not None:
        surv_path = output_dir / "survivorship_bias.json"
        with open(surv_path, "w") as f:
            json.dump(survivorship, f, indent=2, default=str)
        print(f"Survivorship bias report saved to: {surv_path}")

    print(f"Backtest complete! Results saved to {args.output}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())