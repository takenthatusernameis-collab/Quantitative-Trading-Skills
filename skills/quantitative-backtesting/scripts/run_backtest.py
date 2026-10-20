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
from utils import (
    _annualization_factor,
    book_capacity_estimate,
    book_cost_components,
    book_is_active,
    book_market_impact_cost,
    book_return_from_held,
    book_trade_ledger,
    build_market_model,
    compute_book_diagnostic,
    execution_warmup_metadata,
    format_impact_dilution_lines,
    held_book_weights,
    market_impact_cost,
    resolve_impact_aggregation,
    resolve_panel_pricing,
    strategy_target_weights,
    WARMUP_CONVENTION_RUN_BACKTEST,
)
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
    parser.add_argument("--impact-aggregation", type=str, default="panel", choices=["panel", "notional-weighted"], help="Market-impact aggregation convention. 'panel' (default) charges the equal-weighted mean of the per-asset impact rates -- the convention every published number was produced under. 'notional-weighted' charges the dollar-consistent aggregation (the impact rate of each name applied to the notional traded in that name); default unchanged so no published number moves.")
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
    parser.add_argument(
        "--panel-pricing",
        type=str,
        default="net-exposure",
        choices=["net-exposure", "book"],
        help=(
            "How a multi-asset panel is priced and costed. 'net-exposure' "
            "(default) prices the portfolio as net_exposure x mean(asset "
            "returns) and charges the costs on the net exposure -- the "
            "convention every published number was produced under. 'book' "
            "prices the true per-asset book return sum_i w_i r_i of the "
            "strategy's target weights, which makes a market-neutral book "
            "backtestable, and charges the costs on the book itself: "
            "commission and slippage on its gross turnover, borrow on its "
            "short legs, funding on its gross exposure, and market impact "
            "per asset against that asset's own ADV."
        ),
    )
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
    # Shared market model: the single definition of how a single asset, a
    # MultiIndex panel and a dict panel are priced. It is shared with
    # walk_forward.py so the two entry points return comparable results for
    # the same panel (see references/cost_models.md, "Cross-path parity").
    market = build_market_model(data)
    raw_returns = market["raw_returns"]
    close = market["close"]
    volume = market["volume"]
    price = market["price"]
    is_panel = market["is_panel"]

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

    # Panel pricing mode. "net-exposure" (the default) prices the panel as
    # `net_exposure x mean(asset returns)` -- one scalar per period, the
    # convention every published number in this skill was produced under.
    # "book" prices the true per-asset book return `sum_i w_i r_i` of the
    # strategy's target weights, so a market-neutral book can be backtested
    # at all, and charges the costs on the book itself (its gross turnover,
    # its short legs, its gross exposure) instead of on the net exposure.
    panel_pricing = resolve_panel_pricing(getattr(args, "panel_pricing", None))

    # Market-impact aggregation convention. "panel" (the default) charges
    # the equal-weighted mean of the per-asset impact rates; "notional-
    # weighted" charges the dollar-consistent aggregation. Default unchanged
    # so no published number moves.
    impact_aggregation = resolve_impact_aggregation(getattr(args, "impact_aggregation", None))

    # Panel book diagnostic (measurement only). The panel path prices the
    # portfolio as `net_exposure x mean(asset returns)` -- one scalar per
    # period -- so a strategy that holds a long/short book cannot be
    # represented by that scalar. The diagnostic measures the book the
    # strategy actually holds against the framework's pricing; it changes
    # no return, cost, impact or capacity number.
    #
    # The weights are looked up here (the guard below needs them to explain
    # *why* the framework sees no position when the book is not flat); the
    # diagnostic itself is computed after the return series exists, so the
    # return gap is measured on exactly the bars the framework reports.
    book_weights = strategy_target_weights(strategy, data)

    # The book actually held on each bar, when the run prices the panel as
    # a book. It is the single source of truth for the book-mode return AND
    # the book-mode cost basis, so the two can never disagree. None when
    # the strategy exposes no book (the mode then falls back to
    # net-exposure pricing with an explicit message) or when the data is
    # not a panel.
    held_book = None
    if panel_pricing == "book" and book_weights is not None:
        held_book = held_book_weights(
            book_weights,
            market,
            lag=1 + latency,
            fill_rate=fill_rate,
        )

    # The book return, when the mode prices the book.
    book_returns = None
    if held_book is not None:
        book_returns = book_return_from_held(held_book, close)

    # Guard against strategies that never takes a position (e.g. a lookback
    # longer than the data window leaves every rolling indicator NaN, so the
    # signal stays flat at 0). Such strategies produce no trades and their
    # performance metrics are meaningless (division-by-zero Sharpe, etc.).
    #
    # The test is book-aware in "book" mode: a market-neutral book has a
    # flat net exposure but a non-zero gross book, so it *does* take a
    # position and must not be rejected. In "net-exposure" mode the test is
    # the scalar signal test, exactly as before.
    if panel_pricing == "book" and book_weights is not None:
        takes_position = book_is_active(
            book_weights,
            market,
            lag=1 + latency,
            fill_rate=fill_rate,
        )
    else:
        takes_position = signals_active(signals)

    if not takes_position:
        _book_note = ""
        if book_weights is not None:
            _book_only = compute_book_diagnostic(
                book_weights,
                market,
                positions=signals.shift(1 + latency),
                framework_returns=None,
                lag=1 + latency,
                fill_rate=fill_rate,
                impact_coefficient=args.impact_coefficient,
                adv_window=args.adv_window,
                initial_capital=args.initial_capital,
            )
            if _book_only and _book_only.get("n_periods_with_book"):
                _book_note = (
                    " The strategy does hold a book (gross book "
                    f"{_book_only['gross_book']:.4f} on average, "
                    f"{_book_only['n_periods_with_book']} of "
                    f"{_book_only['n_periods']} periods), but its net "
                    "exposure is flat, so the panel pricing convention "
                    "reports no position. See the panel book diagnostic."
                )
        raise ValueError(
            "Strategy never takes a position for the given data and "
            "parameters. Reduce the lookback/period so the indicator is "
            "defined over at least part of the window." + _book_note
        )

    positions = signals.shift(1 + latency).fillna(0)
    if fill_rate < 1.0:
        positions = positions * fill_rate

    # Borrow and funding costs are annualized rates applied per period.
    # The per-period rate divides by the number of periods per year
    # inferred from the data's index (e.g. 252 for business-daily,
    # 365 for calendar-daily, 52 for weekly, 12 for monthly), matching
    # the annualization used for the performance metrics. Falls back to
    # 252 when the frequency cannot be inferred.
    ann_factor = _annualization_factor(raw_returns.index)

    if held_book is not None:
        # Book cost basis. The costs are charged on the book the strategy
        # actually holds, not on the scalar net exposure:
        #
        #   commission + slippage  on the gross turnover sum_i |dw_i|
        #   borrow                 on the short legs sum_i max(-w_i, 0)
        #   funding                on the gross exposure sum_i |w_i| > 1x
        #   market impact          per asset, against that asset's own ADV
        #
        # A market-neutral book has a flat net exposure, so the net-exposure
        # cost model would charge it nothing at all; the book basis charges
        # it for the rotation it actually pays for.
        _book_costs = book_cost_components(
            held_book,
            commission=args.commission,
            slippage=args.slippage,
            borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost,
            ann_factor=ann_factor,
        )
        costs = _book_costs["total"]
        market_impact = book_market_impact_cost(
            held_book=held_book,
            raw_returns=raw_returns,
            close=close,
            volume=volume,
            impact_coefficient=args.impact_coefficient,
            adv_window=args.adv_window,
            initial_capital=args.initial_capital,
            impact_aggregation=impact_aggregation,
        )
        if market_impact is not None:
            costs = costs + market_impact
    else:
        # Transaction costs: apply on position changes. run_backtest uses a
        # different warmup convention to walk_forward.py (it opens the
        # position on the first executable bar rather than dropping the
        # warmup bars) -- this difference is intentional and pinned by
        # cross-path parity tests.
        position_changes = positions.diff().abs()
        costs = position_changes * (args.commission + args.slippage)

        # Market impact model: impact = (position_notional / ADV) * impact_coefficient
        # ADV = rolling average of daily volume (in shares) * price
        #
        # The model lives in utils.market_impact_cost so that this path and
        # walk_forward.py charge the same impact for the same panel. For a
        # panel the portfolio notional is split equally over the constituents
        # and every constituent is measured against its own ADV.
        market_impact = market_impact_cost(
            position_changes=position_changes,
            raw_returns=raw_returns,
            close=close,
            volume=volume,
            is_panel=is_panel,
            impact_coefficient=args.impact_coefficient,
            adv_window=args.adv_window,
            initial_capital=args.initial_capital,
            impact_aggregation=impact_aggregation,
        )
        if market_impact is not None:
            costs = costs + market_impact

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

    # Portfolio return. Two pricing conventions:
    #
    #   net-exposure (default): `positions x mean(asset returns)` -- the
    #     scalar net exposure times the equal-weighted basket return. This
    #     is the convention every published number in this skill was
    #     produced under.
    #   book: `sum_i w_i r_i` -- the true P&L of the per-asset book the
    #     strategy holds. A market-neutral book (flat net exposure, non-zero
    #     gross book) is only representable under this convention.
    #
    # The two modes also differ in their *cost* basis: the net-exposure
    # mode charges the scalar net exposure, the book mode charges the book
    # (gross turnover, short legs, gross exposure). The "Panel book
    # diagnostic" block reports both turnovers so the difference is visible.
    if book_returns is not None:
        effective_pricing = "book"
        strategy_returns = book_returns - costs
    else:
        effective_pricing = "net-exposure"
        strategy_returns = positions * raw_returns - costs
    strategy_returns = strategy_returns.dropna()

    # Panel book diagnostic: the per-asset book the strategy actually holds
    # against the framework's net-exposure pricing, measured on exactly the
    # bars the framework reports. None for a single asset or for a strategy
    # that does not expose a book. This is a measurement only: the returns,
    # costs, impact and capacity above are unchanged by it.
    book_diagnostic = None
    if book_weights is not None:
        book_diagnostic = compute_book_diagnostic(
            book_weights,
            market,
            positions=positions,
            framework_returns=strategy_returns,
            lag=1 + latency,
            fill_rate=fill_rate,
            pricing_mode=effective_pricing,
            impact_coefficient=args.impact_coefficient,
            adv_window=args.adv_window,
            initial_capital=args.initial_capital,
            impact_aggregation=impact_aggregation,
        )

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
    # `positions`, `price` and the trade ledger all share the
    # common date index for single-asset, MultiIndex and dict
    # panel formats alike. `price` is the market model's representative
    # price series (the close for a single asset, the equal-weighted mean
    # of the per-asset closes for a panel), so the ledger is priced on the
    # same basket the return series is marked against.
    n_bars = len(position_changes_bool)

    if held_book is not None:
        # Book ledger: one round trip per asset and direction, priced at
        # that asset's own close. The net-exposure ledger cannot describe
        # a book -- a market-neutral book has a flat net exposure and would
        # produce no trade record at all, leaving the trade-level
        # statistics (win rate, profit factor, expectancy) empty.
        trades = book_trade_ledger(held_book, close)
    else:
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
                exit_price = price.iloc[i]
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
                entry_price = price.iloc[i]
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
            exit_price = price.iloc[-1]
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
        # Panel book diagnostic (None for a single asset or a strategy that
        # does not expose a book). Measurement only -- it does not change
        # the reported P&L.
        "book_diagnostic": book_diagnostic,
        # The pricing convention that produced the reported P&L:
        # "net-exposure" (the default) or "book". Recorded so a result can
        # never be read without knowing how the panel was priced.
        "panel_pricing": effective_pricing,
        "config": {
            "initial_capital": args.initial_capital,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "impact_aggregation": impact_aggregation,
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
            # The execution warmup this run applied, so a consumer of the
            # results knows how many leading bars of the window are not
            # tradable without having to re-derive the convention from the
            # return series. run_backtest zeroes the lagged position
            # instead of dropping it, so the strategy opens on the first
            # executable bar and only the bar with an undefined turnover is
            # dropped -- one bar, against walk_forward.py's two (the
            # difference is intentional and pinned by the cross-path parity
            # tests).
            **execution_warmup_metadata(WARMUP_CONVENTION_RUN_BACKTEST),
            # The requested panel pricing mode and the one that was actually
            # applied. They differ when "book" was requested for a strategy
            # that exposes no book (or for a single asset): the run then
            # falls back to the net-exposure convention.
            "panel_pricing": panel_pricing,
            "panel_pricing_effective": effective_pricing,
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
    #
    # For a panel the frame keeps one column per constituent, so
    # estimate_capacity applies the same equal-weighted basket rule used by
    # the walk-forward paths: each constituent carries 1/n_assets of the
    # portfolio notional and the *least liquid* constituent binds the
    # portfolio capacity. (The previous code collapsed the panel into a
    # pseudo-asset built from the mean close and the mean volume, which
    # overstated the panel's liquidity and made the two paths disagree.)
    try:
        if is_panel:
            _cap_frame = (
                pd.concat({"close": close, "volume": volume}, axis=1)
                if volume is not None
                else None
            )
        else:
            _cap_frame = pd.DataFrame({"close": close, "volume": volume})
        if _cap_frame is None:
            results["capacity"] = None
            results["capacity_trend"] = None
        else:
            _cap = estimate_capacity(
                _cap_frame, args.impact_coefficient, adv_window=args.adv_window
            )
            results["capacity"] = _cap.get("estimated_capacity")
            # Capacity trend: the per-period capacity distribution over the
            # backtest window, so a liquidity squeeze inside the window is
            # visible instead of being hidden behind the last bar's
            # point-in-time reading. None when impact is disabled or ADV is
            # not estimable.
            results["capacity_trend"] = _cap.get("capacity_trend")
    except Exception:
        results["capacity"] = None
        results["capacity_trend"] = None

    # Book-based capacity: the capacity implied by the trade sizes the
    # strategy actually executes, next to the basket-based estimate above
    # (which assumes an equal-weight basket rebalancing 1/n per
    # constituent). A book that trades more per period than that supports
    # less capital, a book that trades less supports more; the two agree
    # exactly for a book that trades 1/n per constituent every period.
    #
    # Reported in the "book" pricing mode only, so the default net-exposure
    # path keeps a single capacity number. None when the mode is not "book",
    # when impact is disabled, when the panel carries no volume, or when
    # the strategy exposes no book. Two book-based capacities are reported
    # side by side: the panel ("|dw|") rule and the dollar-consistent
    # "notional-weighted" ("dw^2") rule, which is the capacity consistent
    # with the notional-weighted impact charge.
    results["capacity_book"] = None
    results["capacity_book_trend"] = None
    results["capacity_notional_weighted"] = None
    results["capacity_notional_weighted_trend"] = None
    if held_book is not None:
        try:
            _book_cap = book_capacity_estimate(
                held_book,
                close,
                volume,
                impact_coefficient=args.impact_coefficient,
                adv_window=args.adv_window,
                impact_aggregation=impact_aggregation,
            )
            results["capacity_book"] = _book_cap.get("estimated_capacity")
            results["capacity_book_trend"] = _book_cap.get("capacity_trend")
            results["capacity_notional_weighted"] = _book_cap.get(
                "estimated_capacity_notional_weighted"
            )
            results["capacity_notional_weighted_trend"] = _book_cap.get(
                "capacity_notional_weighted_trend"
            )
        except Exception:
            results["capacity_book"] = None
            results["capacity_book_trend"] = None
            results["capacity_notional_weighted"] = None
            results["capacity_notional_weighted_trend"] = None

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
    metrics["capacity_trend"] = results.get("capacity_trend")
    # Book-based capacity: the capacity implied by the strategy's own trade
    # sizes (book pricing mode only). None in the net-exposure mode.
    metrics["capacity_book"] = results.get("capacity_book")
    metrics["capacity_book_trend"] = results.get("capacity_book_trend")
    # Panel book diagnostic: the per-asset book the strategy holds against
    # the framework's net-exposure pricing. None for a single asset or a
    # strategy without a book.
    metrics["book_diagnostic"] = results.get("book_diagnostic")
    book_diagnostic = results.get("book_diagnostic")

    # Panel pricing mode: which convention produced the reported P&L. It is
    # printed before every number so a result can never be read without
    # knowing how the panel was priced.
    _requested_pricing = (results.get("config") or {}).get("panel_pricing", "net-exposure")
    _effective_pricing = results.get("panel_pricing", _requested_pricing)
    if _effective_pricing == "book":
        print(
            "Panel pricing mode: book (the portfolio return is the true "
            "per-asset book return sum_i w_i r_i, and the costs are charged "
            "on the book: gross turnover, short legs and gross exposure)."
        )
    elif _requested_pricing == "book":
        print(
            "Panel pricing mode: net-exposure (FALLBACK: --panel-pricing "
            "book was requested, but this strategy/data exposes no per-asset "
            "book, so the run used the net-exposure convention)."
        )
    else:
        print(
            "Panel pricing mode: net-exposure (the portfolio return is "
            "net_exposure x mean(asset returns))."
        )

    # Execution warmup: how many leading bars of the window are not
    # tradable under the convention this run applied. Printed next to the
    # pricing mode so a result can never be read without knowing it.
    _warmup = (results.get("config") or {}).get("warmup_convention")
    _warmup_bars = (results.get("config") or {}).get("execution_warmup_bars")
    if _warmup is not None and _warmup_bars is not None:
        print(
            f"Execution warmup: {_warmup} ({_warmup_bars} bar(s) dropped "
            "from the front of the window; the position is opened on the "
            "first executable bar)."
        )

    if book_diagnostic:
        if _effective_pricing == "book":
            print(
                "Panel Book Diagnostic (the reported P&L uses the book "
                "convention; the net-exposure pricing is shown for "
                "comparison):"
            )
        else:
            print(
                "Panel Book Diagnostic (measurement only -- the reported P&L "
                "is unchanged):"
            )
        print(f"  Gross book (mean sum|w|):     {book_diagnostic['gross_book']:.4f}")
        print(f"  Net exposure (book):          {book_diagnostic['net_exposure']:.4f}")
        print(f"  Net exposure (framework):      {book_diagnostic['framework_net_exposure']:.4f}")
        print(f"  Gross turnover (book):         {book_diagnostic['gross_turnover']:.4f}")
        print(
            "  Turnover charged by the model: "
            f"{book_diagnostic.get('charged_turnover', book_diagnostic['framework_turnover']):.4f}"
            f"  (cost basis: {book_diagnostic.get('cost_basis', 'net-exposure')})"
        )
        print(
            f"  Periods with a book:           "
            f"{book_diagnostic['n_periods_with_book']}/{book_diagnostic['n_periods']}"
        )
        _gap_bps = book_diagnostic.get("return_gap_bps")
        _gap_total = book_diagnostic.get("return_gap_total")
        if _gap_bps is not None:
            print(
                f"  Return gap (framework - book): {_gap_bps:.2f} bps/period "
                f"({_gap_total:.2%} cumulative, pre-cost)"
            )
            print(
                f"  Book return (pre-cost):        "
                f"{book_diagnostic['book_total_return']:.2%}; reported "
                f"(net of costs): "
                f"{book_diagnostic.get('reported_total_return', book_diagnostic['framework_total_return_after_costs']):.2%}"
            )
        if _effective_pricing == "book":
            print(
                "  Cost basis: book. Commission and slippage are charged on "
                "the book's gross turnover (the charged turnover above now "
                "equals the gross turnover), borrow on its short legs and "
                "funding on its gross exposure. The trade ledger is built "
                "from the book, one round trip per asset."
            )
            print(
                "  Residual approximation: the market-impact model charges "
                "the equal-weighted mean of the per-asset impacts over the "
                "whole panel, so a period in which only some names trade is "
                "charged less than the participation actually consumed (see "
                "the impact participation block below)."
            )
        else:
            print(
                "  NOTE: the costs are charged on the net exposure "
                "(|d net exposure|), so the book's own rotation is "
                "under-charged (compare gross turnover with the charged "
                "turnover above). Use --panel-pricing book to price and "
                "cost the book itself."
            )
        for _line in format_impact_dilution_lines(book_diagnostic):
            print(_line)

    # Capacity: the basket-based estimate (the framework's convention) and,
    # in the book pricing mode, the book-based estimate next to it. Printed
    # in the book mode only, so the default path's output is unchanged.
    _capacity_basket = results.get("capacity")
    _capacity_book = results.get("capacity_book")
    if _effective_pricing == "book" and _capacity_book is not None:
        print("Capacity (market impact):")
        if _capacity_basket is not None:
            print(
                "  Basket-based (equal 1/n per constituent): "
                f"{_capacity_basket:,.2f}"
            )
        print(
            "  Book-based (the strategy's own trade sizes): "
            f"{_capacity_book:,.2f}"
        )
        _cap_book_trend = results.get("capacity_book_trend") or {}
        _cap_book_min = _cap_book_trend.get("min_capacity")
        if _cap_book_min is not None:
            print(
                "  Book-based, worst reading in the window:    "
                f"{_cap_book_min:,.2f}"
            )
        print(
            "  The book-based estimate is the equity level at which one of "
            "the strategy's own rebalances reaches the impact threshold; "
            "the basket-based estimate assumes an equal-weight basket that "
            "rebalances 1/n per constituent. The two agree exactly for a "
            "book that rebalances 1/n per constituent every period."
        )
        if _capacity_book > 0:
            print(
                f"  The strategy trades {args.initial_capital:,.2f} of "
                f"equity: {args.initial_capital / _capacity_book:.2f}x the "
                "book-based capacity."
            )

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