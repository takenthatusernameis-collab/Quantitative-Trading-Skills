#!/usr/bin/env python3
"""
Performance analytics for backtesting.

Calculates risk-adjusted return metrics, drawdown statistics, trade-level
analytics, and benchmark comparisons from backtest results.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, Union


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

    Returns:
        Dictionary of performance metrics
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
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        bench_total = (1 + benchmark_returns).prod() - 1
        metrics["benchmark_total_return"] = float(bench_total)
        metrics["benchmark_annualized_return"] = float(
            (1 + bench_total) ** (ann_factor / len(benchmark_returns)) - 1
        )
        # Correlation
        aligned_ret, aligned_bench = returns.align(benchmark_returns, join="inner")
        if len(aligned_ret) > 1:
            metrics["correlation_with_benchmark"] = float(aligned_ret.corr(aligned_bench))
        # Alpha/Beta (simplified)
        if len(aligned_ret) > 1 and aligned_bench.std() > 0:
            beta = aligned_ret.cov(aligned_bench) / aligned_bench.var()
            alpha = aligned_ret.mean() - beta * aligned_bench.mean()
            metrics["alpha"] = float(alpha * ann_factor)
            metrics["beta"] = float(beta)

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

    if "benchmark_total_return" in metrics:
        lines.extend([
            "--- Benchmark Comparison ---",
            f"Benchmark Total Return:      {metrics.get('benchmark_total_return', 0):.2%}",
            f"Benchmark Annualized Return: {metrics.get('benchmark_annualized_return', 0):.2%}",
            f"Correlation:                 {metrics.get('correlation_with_benchmark', 0):.2f}",
            f"Alpha:                       {metrics.get('alpha', 0):.2%}",
            f"Beta:                        {metrics.get('beta', 0):.2f}",
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
