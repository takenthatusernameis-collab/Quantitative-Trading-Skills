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
from performance import calculate_metrics, generate_report, _annualization_factor
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
    parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3%% per year)")
    parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2%% per year)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")
    parser.add_argument("--n-trials", type=int, default=None, help="Number of development trials (parameter configurations) tested; when set, report the Deflated Sharpe Ratio (multiple-testing correction) for the final Sharpe")
    parser.add_argument("--risk-free-rate", type=float, default=None, help="Annual risk-free rate (as decimal, e.g., 0.02 for 2%%)")
    parser.add_argument("--validate-point-in-time", action="store_true", help="Run point-in-time validation on the loaded data and strategy signals (temporal ordering, duplicate timestamps, signal/next-return correlation for look-ahead bias screening)")
    parser.add_argument("--point-in-time-strict", action="store_true", help="Abort with a non-zero exit code when point-in-time validation finds violations (default: warn only)")
    parser.add_argument("--multi-symbol", action="store_true", help="Load every symbol in a multi-symbol file (with a 'symbol' or 'ticker' column) as a panel, run survivorship-bias detection, and backtest a panel. Requires a panel strategy such as cross_sectional_momentum or dual_momentum.")
    parser.add_argument("--benchmark", type=str, nargs="+", default=None, help="Path to benchmark OHLCV file(s) (e.g. SPY QQQ) for buy-and-hold baseline comparison (alpha/beta, correlation)")
    parser.add_argument("--total-return-benchmark", action="store_true", help="Compute benchmark returns using total return (dividends + price) when dividend/adj_close data is available, instead of price-only returns (applies to all benchmarks)")
    parser.add_argument("--benchmark-commission", type=float, default=None, help="Commission per trade for benchmark (as decimal). Defaults to strategy commission if not specified (applies to all benchmarks).")
    parser.add_argument("--benchmark-slippage", type=float, default=None, help="Slippage per trade for benchmark (as decimal). Defaults to strategy slippage if not specified (applies to all benchmarks).")
    parser.add_argument("--benchmark-expense-ratio", type=float, default=None, help="Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%). Defaults to 0 (applies to all benchmarks).")
    parser.add_argument("--benchmark-cost-is-periodic", action="store_true", help="If set, apply benchmark trading costs (commission+slippage) as periodic deductions each period instead of as a round-trip cost on total return (applies to all benchmarks).")
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


def run_backtest(data, strategy, args, data_provenance=None, benchmark=None):
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
    benchmark_paths = getattr(args, "benchmark", None)
    if benchmark_paths:
        # Normalize to a list of paths for uniform handling.
        if isinstance(benchmark_paths, str):
            benchmark_paths = [benchmark_paths]
        benchmark_frames = []
        benchmark_provenances = []
        for path in benchmark_paths:
            print(f"Loading benchmark data from {path}...")
            bench_df, bench_prov = load_data(path, return_provenance=True)
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
            benchmark_frames.append(bench_df)
            benchmark_provenances.append(bench_prov)
        # Pass the list of benchmark DataFrames to run_backtest();
        # a single-element list is also accepted (backward compatible).
        benchmark = benchmark_frames if len(benchmark_frames) > 1 else benchmark_frames[0]
        # Keep the first provenance for the artifact/report (the primary benchmark).
        benchmark_provenance = benchmark_provenances[0]
        # Stash all provenances on args so downstream code can serialize them.
        args._benchmark_provenances = benchmark_provenances

    print(f"Building strategy: {args.strategy}...")
    strategy = build_strategy(args.strategy, args.params)

    print("Running backtest...")
    results = run_backtest(data, strategy, args, data_provenance=provenance, benchmark=benchmark)

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
    with open(prov_path, "w") as f:
        json.dump(results.get("data_provenance"), f, indent=2, default=str)
    print(f"Data provenance saved to: {prov_path}")

    if benchmark_provenance is not None:
        bench_prov_path = output_dir / "benchmark_provenance.json"
        with open(bench_prov_path, "w") as f:
            json.dump(benchmark_provenance.to_dict(), f, indent=2, default=str)
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