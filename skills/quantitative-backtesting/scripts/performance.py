#!/usr/bin/env python3
"""
Performance analytics for backtesting.

Calculates risk-adjusted return metrics, drawdown statistics, trade-level
analytics, and benchmark comparisons from backtest results.
"""

import json
import math
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, Union, List


RISK_FREE_RATE = 0.02  # Annual risk-free rate (2%)


def _annualization_factor(index: pd.Index, target_years: float = 1.0) -> float:
    """Estimate the number of periods per year from a DatetimeIndex."""
    if not isinstance(index, pd.DatetimeIndex):
        return 252  # Default trading days
    try:
        freq = pd.infer_freq(index)
        if freq is None:
            return 252
        # Business daily = 252, daily = 365, weekly = 52, monthly = 12
        freq_map = {
            "B": 252, "D": 365, "W": 52, "M": 12,
            "Q": 4, "Y": 1, "H": 252 * 6.5 * 21,
        }
        return freq_map.get(freq[0], 252)
    except Exception:
        return 252


def _betacf(a: float, b: float, x: float) -> float:
    """Continued-fraction expansion for the incomplete beta function (Lentz)."""
    maxit = 300
    eps = 3.0e-16
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        dele = d * c
        h *= dele
        if abs(dele - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_pvalue(t: float, df: int) -> Optional[float]:
    """Two-sided p-value for a Student's t statistic with `df` degrees of freedom.

    Returns None when the test cannot be evaluated (df <= 0, non-finite t).
    p = I_{df/(df+t^2)}(df/2, 1/2).
    """
    if df <= 0 or not np.isfinite(t) or t == 0.0:
        return None if df <= 0 else (1.0 if t == 0.0 else None)
    x = df / (df + t * t)
    return float(_betai(0.5 * df, 0.5, x))


def _benchmark_stats(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    ann_factor: float,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
) -> Dict[str, Any]:
    """Compute buy-and-hold benchmark comparison metrics from aligned returns.

    Returns total/annualized benchmark return, correlation, OLS alpha (annualized),
    beta, the alpha t-statistic, its two-sided p-value, and the regression R^2.
    The alpha/beta/correlation match the existing (pre-significance) definition;
    the regression is the standard per-period OLS y = alpha + beta * x on the
    common-date aligned series. t-stat and p-value are invariant to annualization,
    and are only reported when at least 3 aligned observations exist.

    If benchmark_commission or benchmark_slippage > 0:
      - If benchmark_cost_is_periodic is False (default), the benchmark total return
        is reduced by the round-trip cost (buy + sell) applied once to the total
        benchmark return, simulating a buy-and-hold investor who pays transaction
        costs at entry and exit.
      - If benchmark_cost_is_periodic is True, the benchmark return is reduced each
        period by the per-period cost ( (benchmark_commission + benchmark_slippage) / ann_factor ),
        simulating periodic trading costs (e.g., from frequent rebalancing).

    If benchmark_expense_ratio > 0, the benchmark return is reduced each period
    by the per-period expense ratio (benchmark_expense_ratio / ann_factor),
    simulating a constant annual fee deducted from the benchmark's net asset
    value (e.g., an ETF expense ratio).

    Additionally, computes the tracking error (annualized standard deviation of
    active return) and the information ratio (annualized alpha divided by
    tracking error).
    """
    stats: Dict[str, Any] = {}
    if benchmark_returns is None or len(benchmark_returns) == 0:
        return stats
    # Apply benchmark expense ratio (annual) as a periodic deduction
    if benchmark_expense_ratio > 0:
        expense_per_period = benchmark_expense_ratio / ann_factor
        benchmark_returns = benchmark_returns - expense_per_period
    # Apply benchmark trading costs as periodic deduction if specified
    if benchmark_cost_is_periodic and (benchmark_commission > 0 or benchmark_slippage > 0):
        periodic_cost = (benchmark_commission + benchmark_slippage) / ann_factor
        benchmark_returns = benchmark_returns - periodic_cost

    # Compute total return before applying round-trip costs (if not periodic)
    bench_total = (1 + benchmark_returns).prod() - 1

    # Apply benchmark trading costs (round-trip: buy + sell) if not periodic
    if not benchmark_cost_is_periodic and (benchmark_commission > 0 or benchmark_slippage > 0):
        round_trip_cost = benchmark_commission + benchmark_slippage
        bench_total = (1 + bench_total) * (1 - round_trip_cost) - 1

    stats["benchmark_total_return"] = float(bench_total)
    stats["benchmark_annualized_return"] = float(
        (1 + bench_total) ** (ann_factor / len(benchmark_returns)) - 1
    )
    stats["benchmark_total_return_type"] = "total" if total_return_benchmark else "price"
    stats["benchmark_commission"] = float(benchmark_commission)
    stats["benchmark_slippage"] = float(benchmark_slippage)
    stats["benchmark_expense_ratio"] = float(benchmark_expense_ratio)
    stats["benchmark_cost_is_periodic"] = benchmark_cost_is_periodic

    aligned_ret, aligned_bench = returns.align(benchmark_returns, join="inner")
    n = len(aligned_ret)
    if n <= 1:
        return stats

    stats["correlation_with_benchmark"] = float(aligned_ret.corr(aligned_bench))

    y = aligned_ret.to_numpy(dtype=float)
    x = aligned_bench.to_numpy(dtype=float)
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    sxx = float(np.sum((x - x_mean) ** 2))
    if sxx <= 0:
        return stats
    sxy = float(np.sum((x - x_mean) * (y - y_mean)))
    beta = sxy / sxx
    alpha = y_mean - beta * x_mean  # per-period OLS intercept
    stats["alpha"] = float(alpha * ann_factor)
    stats["beta"] = float(beta)

    # Compute tracking error and information ratio
    active_return = aligned_ret - aligned_bench
    tracking_error = active_return.std() * np.sqrt(ann_factor)
    stats["tracking_error"] = float(tracking_error)
    if tracking_error > 0:
        stats["information_ratio"] = float(stats["alpha"] / tracking_error)
    else:
        # If tracking error is zero, information ratio is infinite if alpha is non-zero,
        # otherwise undefined (set to 0.0)
        stats["information_ratio"] = float("inf") if stats["alpha"] != 0 else 0.0

    # Significance of the alpha intercept (Jensen's alpha t-test).
    if n >= 3:
        residuals = y - (alpha + beta * x)
        rss = float(np.sum(residuals ** 2))
        tss = float(np.sum((y - y_mean) ** 2))
        df = n - 2
        if rss > 0 and tss > 0:
            sigma2 = rss / df
            se_alpha = math.sqrt(sigma2 * (1.0 / n + x_mean ** 2 / sxx))
            t_stat = alpha / se_alpha if se_alpha > 0 else float("inf")
            stats["alpha_tstat"] = float(t_stat)
            stats["alpha_pvalue"] = _t_two_sided_pvalue(t_stat, df)
        elif rss <= 0:
            # Perfect linear fit: alpha estimate is exact, p-value is 0.
            stats["alpha_tstat"] = None
            stats["alpha_pvalue"] = 0.0
        stats["r_squared"] = float(1.0 - rss / tss) if tss > 0 else 0.0
    return stats


def calculate_metrics(
    results: Dict[str, Any],
    risk_free_rate: float = RISK_FREE_RATE,
) -> Dict[str, Any]:
    """
    Calculate comprehensive performance and risk metrics from backtest results.

    Args:
        results: Dictionary containing backtest results. Expected keys:
            - 'equity_curve': pandas Series or DataFrame of portfolio values indexed by date
            - 'returns': pandas Series of period returns (optional)
            - 'trades': list of trade dictionaries with 'pnl', 'entry_date', 'exit_date' (optional)
            - 'benchmark': pandas Series of benchmark returns (optional)
            - 'config': original backtest config dict (optional)
        risk_free_rate: Annual risk-free rate for Sharpe/Sortino calculations
    """
    metrics = {}

    equity = results.get("equity_curve")
    returns = results.get("returns")
    trades = results.get("trades", [])
    benchmark_returns = results.get("benchmark")
    config = results.get("config", {})

    # Derive returns from equity curve if not provided
    if returns is None and equity is not None:
        if isinstance(equity, pd.DataFrame):
            equity_series = equity.iloc[:, 0]
        else:
            equity_series = equity
        returns = equity_series.pct_change().dropna()

    if returns is None or len(returns) == 0:
        return {"error": "No returns data available for metric calculation"}

    returns = returns.dropna()
    ann_factor = _annualization_factor(returns.index)

    # --- Return Metrics ---
    total_return = (1 + returns).prod() - 1
    annualized_return = (1 + total_return) ** (ann_factor / len(returns)) - 1
    metrics["total_return"] = float(total_return)
    metrics["annualized_return"] = float(annualized_return)
    metrics["annualized_volatility"] = float(returns.std() * np.sqrt(ann_factor))

    # --- Risk-Adjusted Returns ---
    excess_returns = returns - risk_free_rate / ann_factor
    std_excess = excess_returns.std()
    if std_excess > 0:
        metrics["sharpe_ratio"] = float(excess_returns.mean() / std_excess * np.sqrt(ann_factor))
        # Sortino: downside deviation
        downside_returns = excess_returns[excess_returns < 0]
        downside_std = downside_returns.std()
        if downside_std > 0:
            metrics["sortino_ratio"] = float(
                excess_returns.mean() / downside_std * np.sqrt(ann_factor)
            )
        else:
            metrics["sortino_ratio"] = float("inf")
    else:
        metrics["sharpe_ratio"] = 0.0
        metrics["sortino_ratio"] = 0.0

    # --- Drawdown ---
    if equity is not None:
        if isinstance(equity, pd.DataFrame):
            equity_values = equity.iloc[:, 0]
        else:
            equity_values = equity
        cummax = equity_values.cummax()
        drawdown = (equity_values - cummax) / cummax
        metrics["max_drawdown"] = float(drawdown.min())
        metrics["avg_drawdown"] = float(drawdown[drawdown < 0].mean() if (drawdown < 0).any() else 0.0)
        # Calmar ratio
        if metrics["max_drawdown"] < 0:
            metrics["calmar_ratio"] = float(
                abs(metrics["annualized_return"] / metrics["max_drawdown"])
            )
        else:
            metrics["calmar_ratio"] = float("inf")
        # Recovery time
        drawdown_idx = drawdown[drawdown == drawdown.min()].index
        if len(drawdown_idx) > 0:
            peak_date = cummax[drawdown == drawdown.min()].index[0]
            trough_date = drawdown_idx[0]
            recovery_mask = (equity_values.index > trough_date) & (
                equity_values > cummax.loc[:trough_date].iloc[-1]
            )
            if recovery_mask.any():
                recovery_date = equity_values.index[recovery_mask][0]
                metrics["max_drawdown_recovery_days"] = int(
                    (recovery_date - peak_date).days
                )
            else:
                metrics["max_drawdown_recovery_days"] = None
    else:
        metrics["max_drawdown"] = 0.0
        metrics["avg_drawdown"] = 0.0
        metrics["calmar_ratio"] = 0.0

    # --- Value at Risk ---
    metrics["var_95"] = float(returns.quantile(0.05))
    metrics["cvar_95"] = float(returns[returns <= returns.quantile(0.05)].mean())

    # --- Return Distribution ---
    metrics["skewness"] = float(returns.skew())
    metrics["kurtosis"] = float(returns.kurtosis())

    # --- Trade-Level Analytics ---
    if trades:
        # Trade PnL is an absolute currency amount; trade return is a fraction
        # of entry price. These are different units and must not be conflated:
        # avg_win/avg_loss are return fractions (displayed as %), while
        # expectancy/profit_factor are PnL aggregates (currency units). Each
        # trade is classified once by its PnL so a missing `return` on one trade
        # cannot desync the win/loss buckets.
        trade_pnls: list[float] = []
        win_returns: list[float] = []
        loss_returns: list[float] = []
        durations: list[float] = []
        for trade in trades:
            pnl = float(trade.get("pnl", 0))
            trade_pnls.append(pnl)
            trade_return = trade.get("return")
            if pnl > 0:
                if trade_return is not None:
                    win_returns.append(float(trade_return))
            elif pnl < 0:
                if trade_return is not None:
                    loss_returns.append(abs(float(trade_return)))
            entry = trade.get("entry_date")
            exit_ = trade.get("exit_date")
            if entry and exit_:
                durations.append(
                    (pd.Timestamp(exit_) - pd.Timestamp(entry)).days
                )

        metrics["total_trades"] = len(trades)
        metrics["winning_trades"] = sum(1 for p in trade_pnls if p > 0)
        metrics["losing_trades"] = sum(1 for p in trade_pnls if p < 0)
        metrics["win_rate"] = float(
            metrics["winning_trades"] / len(trades) if trades else 0
        )
        # Count trades whose exit was forced by the end of the sample
        # rather than by a signal (flagged `closed_at_end` by the
        # backtest extractor). These legs are real PnL in the equity
        # curve but are not signal-driven, so surfacing the count lets
        # consumers judge how much of the trade ledger is end-of-sample
        # artifact vs. genuine entry/exit activity.
        n_closed_at_end = sum(1 for t in trades if t.get("closed_at_end"))
        metrics["trades_closed_at_end"] = int(n_closed_at_end)
        metrics["pct_trades_closed_at_end"] = float(
            n_closed_at_end / len(trades) if trades else 0.0
        )
        metrics["avg_win"] = float(np.mean(win_returns)) if win_returns else 0.0
        metrics["avg_loss"] = float(np.mean(loss_returns)) if loss_returns else 0.0
        gross_profit = sum(p for p in trade_pnls if p > 0)
        gross_loss = abs(sum(p for p in trade_pnls if p < 0))
        if gross_loss > 0:
            metrics["profit_factor"] = float(gross_profit / gross_loss)
        else:
            metrics["profit_factor"] = 0.0
        metrics["expectancy"] = float(np.mean(trade_pnls))
        if durations:
            metrics["avg_trade_duration"] = float(np.mean(durations))

    # --- Benchmark Comparison ---
    # Handle multiple benchmarks if present (for multiple-testing correction)
    benchmark_list = results.get("benchmark_list")
    if benchmark_list is not None and len(benchmark_list) > 0:
        # Process each benchmark in the list
        benchmark_metrics = []
        benchmark_alphas = []  # For multiple-testing correction

        for i, bench_returns in enumerate(benchmark_list):
            if bench_returns is not None and len(bench_returns) > 0:
                bench_stats = _benchmark_stats(
                    returns,
                    bench_returns,
                    ann_factor,
                    total_return_benchmark=config.get("total_return_benchmark", False),
                    benchmark_commission=config.get("benchmark_commission", 0.0),
                    benchmark_slippage=config.get("benchmark_slippage", 0.0),
                    benchmark_expense_ratio=config.get("benchmark_expense_ratio", 0.0),
                    benchmark_cost_is_periodic=config.get("benchmark_cost_is_periodic", False),
                )
                # Add index to distinguish between benchmarks
                indexed_stats = {f"benchmark_{i}_{k}": v for k, v in bench_stats.items()}
                benchmark_metrics.append(indexed_stats)

                # Collect alpha for multiple-testing correction
                if "alpha" in bench_stats:
                    benchmark_alphas.append(bench_stats["alpha"])
            else:
                benchmark_metrics.append({})

        # Add all benchmark metrics to results
        for bench_metric in benchmark_metrics:
            metrics.update(bench_metric)

        # Apply Deflated Alpha Ratio correction for multiple benchmarks
        if len(benchmark_alphas) >= 2 and len(returns) >= 2:
            # Use the first benchmark's alpha as the primary one for correction
            # (typically the first benchmark is the main one being compared against)
            primary_alpha = metrics.get("benchmark_0_alpha", 0.0)
            # For multiple-testing correction, we need to know how many benchmarks were tested
            n_benchmarks = len([a for a in benchmark_alphas if not np.isnan(a)])

            if n_benchmarks >= 2:
                try:
                    # Import deflated_alpha_ratio with circular import protection
                    try:
                        from walk_forward import deflated_alpha_ratio  # noqa: E402
                    except ImportError:
                        from scripts.walk_forward import deflated_alpha_ratio  # noqa: E402

                    # Apply Deflated Alpha Ratio correction
                    da_result = deflated_alpha_ratio(
                        alpha=primary_alpha,
                        returns=returns,
                        benchmark_returns=benchmark_list[0] if benchmark_list[0] is not None else pd.Series(),
                        n_benchmarks=n_benchmarks,
                        trial_alphas=benchmark_alphas if len(benchmark_alphas) == n_benchmarks else None,
                    )
                    # Add the deflated alpha metrics with a prefix to distinguish
                    metrics["deflated_alpha"] = da_result
                except Exception:
                    # If deflated alpha calculation fails, continue without it
                    pass
    elif benchmark_returns is not None and len(benchmark_returns) > 0:
        # Backward compatibility: single benchmark
        metrics.update(_benchmark_stats(
            returns,
            benchmark_returns,
            ann_factor,
            total_return_benchmark=config.get("total_return_benchmark", False),
            benchmark_commission=config.get("benchmark_commission", 0.0),
            benchmark_slippage=config.get("benchmark_slippage", 0.0),
            benchmark_expense_ratio=config.get("benchmark_expense_ratio", 0.0),
            benchmark_cost_is_periodic=config.get("benchmark_cost_is_periodic", False),
        ))
        # Apply Deflated Alpha Ratio correction for single benchmark (n_benchmarks=1)
        # With n_benchmarks=1, the deflated alpha should equal the regular alpha
        # (no multiple-testing correction needed), but we'll compute it anyway for consistency
        if "alpha" in metrics and len(returns) >= 2:
            try:
                # Import deflated_alpha_ratio with circular import protection
                try:
                    from walk_forward import deflated_alpha_ratio  # noqa: E402
                except ImportError:
                    from scripts.walk_forward import deflated_alpha_ratio  # noqa: E402

                da_result = deflated_alpha_ratio(
                    alpha=metrics["alpha"],
                    returns=returns,
                    benchmark_returns=benchmark_returns,
                    n_benchmarks=1,
                    trial_alphas=[metrics["alpha"]],
                )
                metrics["deflated_alpha"] = da_result
            except Exception:
                # If deflated alpha calculation fails, continue without it
                pass

    # --- Additional Ratios ---
    if returns.std() > 0:
        metrics["omega_ratio"] = float(
            (1 + returns[returns > 0].sum()) / abs(returns[returns < 0].sum())
            if (returns < 0).any()
            else float("inf")
        )
        metrics["tail_ratio"] = float(
            returns.quantile(0.9) / abs(returns.quantile(0.1))
            if returns.quantile(0.1) != 0
            else float("inf")
        )
    else:
        metrics["omega_ratio"] = 0.0
        metrics["tail_ratio"] = 0.0

    # --- Multiple-Testing Correction (Deflated Sharpe Ratio) ---
    # When the caller reports how many development trials (parameter
    # configurations) produced this backtest (e.g. the size of the
    # grid searched), deflate the final Sharpe for selection bias and
    # for the non-normality of returns. `deflated_sharpe_ratio` lives
    # in walk_forward, which imports this module, so it is imported
    # lazily to avoid a circular import at module load time.
    n_trials = config.get("n_trials") if config else None
    # Optional cross-sectional record: when the caller also reports the
    # Sharpe ratios of every trial (e.g. the ranked rows of a parameter
    # optimization), SR* is estimated from their dispersion instead of
    # the i.i.d.-normal null approximation.
    trial_sharpes = config.get("trial_sharpes") if config else None
    if n_trials is not None and int(n_trials) >= 1 and len(returns) >= 2:
        # Try both the top-level and the package-qualified name so the
        # function resolves regardless of whether `performance` was
        # imported as a top-level module or as part of the `scripts`
        # package.
        try:
            from walk_forward import deflated_sharpe_ratio  # noqa: E402
        except ImportError:
            from scripts.walk_forward import deflated_sharpe_ratio  # noqa: E402

        metrics["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=metrics["sharpe_ratio"],
            returns=returns,
            n_trials=int(n_trials),
            trial_sharpes=trial_sharpes,
        )

    # Store config metadata
    if config:
        metrics["initial_capital"] = config.get("initial_capital", None)

    return metrics


def generate_report(
    metrics: Dict[str, Any],
    output_dir: Union[str, Path],
    symbol: str = "N/A",
    strategy_name: str = "N/A",
) -> None:
    """
    Generate a performance report from calculated metrics.

    Args:
        metrics: Dictionary of performance metrics
        output_dir: Directory to save the report
        symbol: Symbol that was backtested
        strategy_name: Name of the strategy used
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save metrics as JSON
    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    # Generate text report
    report_path = output_dir / "report.txt"
    lines = [
        "=" * 60,
        "BACKTEST PERFORMANCE REPORT",
        "=" * 60,
        f"Symbol: {symbol}",
        f"Strategy: {strategy_name}",
        "",
        "--- Return Metrics ---",
        f"Total Return:          {metrics.get('total_return', 'N/A'):.2%}"
        if isinstance(metrics.get("total_return"), (int, float))
        else "Total Return: N/A",
        f"Annualized Return:     {metrics.get('annualized_return', 0):.2%}",
        f"Annualized Volatility: {metrics.get('annualized_volatility', 0):.2%}",
        "",
        "--- Risk-Adjusted Returns ---",
        f"Sharpe Ratio:          {metrics.get('sharpe_ratio', 0):.2f}",
        f"Sortino Ratio:         {metrics.get('sortino_ratio', 0):.2f}",
        f"Calmar Ratio:          {metrics.get('calmar_ratio', 0):.2f}",
        "",
        "--- Risk Metrics ---",
        f"Max Drawdown:          {metrics.get('max_drawdown', 0):.2%}",
        f"Avg Drawdown:          {metrics.get('avg_drawdown', 0):.2%}",
        f"VaR (95%):             {metrics.get('var_95', 0):.2%}",
        f"CVaR (95%):            {metrics.get('cvar_95', 0):.2%}",
        f"Skewness:              {metrics.get('skewness', 0):.2f}",
        f"Kurtosis:              {metrics.get('kurtosis', 0):.2f}",
        "",
    ]

    if "total_trades" in metrics:
        lines.extend([
            "--- Trade-Level Analytics ---",
            f"Total Trades:          {metrics.get('total_trades', 0)}",
            f"Winning Trades:        {metrics.get('winning_trades', 0)}",
            f"Losing Trades:         {metrics.get('losing_trades', 0)}",
            f"Win Rate:              {metrics.get('win_rate', 0):.2%}",
            f"Avg Win:               {metrics.get('avg_win', 0):.2%}",
            f"Avg Loss:              {metrics.get('avg_loss', 0):.2%}",
            f"Profit Factor:         {metrics.get('profit_factor', 0):.2f}",
            f"Expectancy:            {metrics.get('expectancy', 0):.4f}",
            "",
        ])
        # End-of-sample forced closes: trades whose exit was not signal-
        # driven but forced because the data ended. These are real PnL in
        # the equity curve but are an artifact of the sample boundary, so
        # surfacing the count lets consumers judge how much of the ledger
        # is genuine entry/exit activity.
        if "trades_closed_at_end" in metrics:
            lines.extend([
                "--- End-of-Sample Closes ---",
                f"Trades Closed at End:      {metrics.get('trades_closed_at_end', 0)}",
                f"% of Trades Closed at End: {metrics.get('pct_trades_closed_at_end', 0):.2%}",
                "",
            ])

    # Multiple-testing correction: surfaced only when the backtest
    # reported the number of development trials behind it.
    dsr = metrics.get("deflated_sharpe")
    if dsr is not None:
        z_score = dsr.get("z_score")
        lines.extend([
            "--- Multiple-Testing Correction ---",
            f"Deflated Sharpe Ratio: {dsr.get('deflated_sharpe_ratio', 0):.4f}",
            f"P-Value:               {dsr.get('p_value', 0):.4f}",
            f"Expected Max Sharpe:   {dsr.get('expected_max_sharpe', 0):.4f}",
            f"Z-Score:               {z_score:.4f}" if z_score is not None else "Z-Score:               N/A",
            f"Number of Trials:      {dsr.get('n_trials', 0)}",
            f"Observations:          {dsr.get('n_observations', 0)}",
            "",
        ])

    if "benchmark_total_return" in metrics:
        lines.extend([
            "--- Benchmark Comparison ---",
            f"Benchmark Total Return:      {metrics.get('benchmark_total_return', 0):.2%}",
            f"Benchmark Annualized Return: {metrics.get('benchmark_annualized_return', 0):.2%}",
            f"Benchmark Return Type:       {metrics.get('benchmark_total_return_type', 'price')}",
            f"Benchmark Commission:        {metrics.get('benchmark_commission', 0):.4f}",
            f"Benchmark Slippage:          {metrics.get('benchmark_slippage', 0):.4f}",
            f"Correlation:                 {metrics.get('correlation_with_benchmark', 0):.2f}",
            f"Alpha:                       {metrics.get('alpha', 0):.2%}",
            f"Beta:                        {metrics.get('beta', 0):.2f}",
            f"Alpha t-stat:                {metrics.get('alpha_tstat', 'N/A')}",
            f"Alpha p-value:               {metrics.get('alpha_pvalue', 'N/A')}",
            f"R-squared:                   {metrics.get('r_squared', 'N/A')}",
            "",
        ])

    # Deflated Alpha Ratio section (multiple-testing correction for benchmark alpha)
    if "deflated_alpha" in metrics:
        da = metrics["deflated_alpha"]
        lines.extend([
            "--- Deflated Alpha Ratio (Multiple-Testing Correction) ---",
            f"Deflated Alpha Ratio:        {da.get('deflated_alpha_ratio', 0):.4f}",
            f"P-Value:                     {da.get('p_value', 0):.4f}",
            f"Expected Max Alpha:          {da.get('expected_max_alpha', 0):.4f}",
            f"Z-Score:                     {da.get('z_score', 'N/A')}"
            if da.get('z_score') is not None else "Z-Score:                     N/A",
            f"Number of Benchmarks:        {da.get('n_benchmarks', 0)}",
            f"Observations:                {da.get('n_observations', 0)}",
            "",
        ])

    lines.append("=" * 60)

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    print(f"Metrics saved to: {metrics_path}")
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test performance analytics")
    args = parser.parse_args()

    # Generate sample returns
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=252, freq="B")
    sample_returns = pd.Series(np.random.normal(0.0005, 0.015, 252), index=dates)
    sample_equity = (1 + sample_returns).cumprod() * 100000

    sample_results = {
        "equity_curve": sample_equity,
        "returns": sample_returns,
        "config": {"initial_capital": 100000},
        "trades": [
            {"pnl": 1500, "return": 0.015, "entry_date": "2020-02-01", "exit_date": "2020-03-01"},
            {"pnl": -800, "return": -0.008, "entry_date": "2020-03-15", "exit_date": "2020-04-01"},
            {"pnl": 2300, "return": 0.023, "entry_date": "2020-05-01", "exit_date": "2020-06-01"},
        ],
    }

    m = calculate_metrics(sample_results)
    for k, v in m.items():
        if isinstance(v, (int, float)):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
