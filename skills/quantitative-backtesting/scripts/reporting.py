#!/usr/bin/env python3
"""
Automated tear sheet and report generation for backtesting.

Creates visual and textual summaries of strategy performance including
equity curves, return distributions, drawdown analysis, and trade breakdowns.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Union, Optional


def generate_tear_sheet(
    results: Dict[str, Any],
    metrics: Dict[str, Any],
    output_dir: Union[str, Path],
    symbol: str = "N/A",
    strategy_name: str = "N/A",
    save_plots: bool = True,
) -> str:
    """
    Generate a comprehensive tear sheet for a backtest.

    Args:
        results: Dictionary containing backtest results including:
            - 'equity_curve': Series or DataFrame of portfolio values
            - 'returns': Series of period returns
            - 'data': original market data DataFrame
            - 'config': backtest configuration
        metrics: Dictionary of calculated performance metrics
        output_dir: Directory to save the tear sheet and plots
        symbol: Symbol that was backtested
        strategy_name: Name of the strategy
        save_plots: If True, attempt to save matplotlib plots

    Returns:
        Path to the generated tear sheet HTML file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    equity = results.get("equity_curve")
    returns = results.get("returns")
    data = results.get("data")

    if equity is not None:
        if isinstance(equity, pd.DataFrame):
            equity_values = equity.iloc[:, 0]
        else:
            equity_values = equity
    else:
        equity_values = None

    if returns is None and equity_values is not None:
        returns = equity_values.pct_change().dropna()

    # Build HTML tear sheet
    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Tear Sheet</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #2980b9; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
        th {{ background: #3498db; color: white; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .metric {{ font-family: monospace; }}
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        .chart {{ margin: 20px 0; text-align: center; }}
        .chart img {{ max-width: 100%; border-radius: 4px; }}
    </style>
</head>
<body>
<div class="container">
<h1>Backtest Tear Sheet</h1>
<p><strong>Symbol:</strong> {symbol}</p>
<p><strong>Strategy:</strong> {strategy_name}</p>
<p><strong>Periods:</strong> {len(returns) if returns is not None else 'N/A'}</p>
""")

    # Summary metrics table
    html_parts.append("<h2>Summary Metrics</h2>")
    html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")

    def fmt_pct(val):
        if isinstance(val, (int, float)):
            return f"{val:.2%}"
        return str(val)

    def fmt_num(val, decimals=2):
        if isinstance(val, (int, float)):
            if val == float("inf"):
                return "inf"
            if val == float("-inf"):
                return "-inf"
            return f"{val:.{decimals}f}"
        return str(val)

    summary_metrics = [
        ("Total Return", "total_return", fmt_pct),
        ("Annualized Return", "annualized_return", fmt_pct),
        ("Annualized Volatility", "annualized_volatility", fmt_pct),
        ("Sharpe Ratio", "sharpe_ratio", fmt_num),
        ("Sortino Ratio", "sortino_ratio", fmt_num),
        ("Calmar Ratio", "calmar_ratio", fmt_num),
        ("Max Drawdown", "max_drawdown", fmt_pct),
        ("Omega Ratio", "omega_ratio", fmt_num),
        ("Skewness", "skewness", fmt_num),
        ("Kurtosis", "kurtosis", fmt_num),
        ("VaR (95%)", "var_95", fmt_pct),
        ("CVaR (95%)", "cvar_95", fmt_pct),
    ]

    for label, key, fmt in summary_metrics:
        if key in metrics:
            val = fmt(metrics[key])
            cls = ""
            if key in ("total_return", "annualized_return") and isinstance(metrics.get(key), (int, float)):
                cls = "positive" if metrics[key] > 0 else "negative"
            if key == "max_drawdown":
                cls = "negative" if metrics[key] < 0 else "positive"
            html_parts.append(f"<tr><td>{label}</td><td class='metric {cls}'>{val}</td></tr>")
    html_parts.append("</table>")

    # Trade analytics
    if "total_trades" in metrics:
        html_parts.append("<h2>Trade Analytics</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        trade_metrics = [
            ("Total Trades", "total_trades", fmt_num),
            ("Winning Trades", "winning_trades", fmt_num),
            ("Losing Trades", "losing_trades", fmt_num),
            ("Win Rate", "win_rate", fmt_pct),
            ("Avg Win", "avg_win", fmt_pct),
            ("Avg Loss", "avg_loss", fmt_pct),
            ("Profit Factor", "profit_factor", fmt_num),
            ("Expectancy", "expectancy", lambda v: f"{v:.4f}" if isinstance(v, (int, float)) else str(v)),
        ]
        for label, key, fmt in trade_metrics:
            if key in metrics:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(metrics[key])}</td></tr>")
        html_parts.append("</table>")

    # Benchmark comparison
    if "benchmark_total_return" in metrics:
        html_parts.append("<h2>Benchmark Comparison</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        bench_metrics = [
            ("Benchmark Total Return", "benchmark_total_return", fmt_pct),
            ("Correlation", "correlation_with_benchmark", fmt_num),
            ("Alpha", "alpha", fmt_pct),
            ("Beta", "beta", fmt_num),
        ]
        for label, key, fmt in bench_metrics:
            if key in metrics:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(metrics[key])}</td></tr>")
        html_parts.append("</table>")

    # Generate plots if matplotlib is available
    plot_files = []
    if save_plots and returns is not None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            # Equity curve plot
            if equity_values is not None:
                fig, ax = plt.subplots(figsize=(12, 4))
                ax.plot(equity_values.index, equity_values.values)
                ax.set_title("Equity Curve")
                ax.set_ylabel("Portfolio Value")
                ax.set_xlabel("Date")
                ax.grid(True, alpha=0.3)
                plt.tight_layout()
                equity_path = output_dir / "equity_curve.png"
                plt.savefig(equity_path, dpi=150)
                plt.close()
                plot_files.append(equity_path)

            # Returns distribution
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.hist(returns.values, bins=50, alpha=0.7, edgecolor="black")
            ax.axvline(returns.mean(), color="red", linestyle="--", label=f"Mean: {returns.mean():.4f}")
            ax.set_title("Return Distribution")
            ax.set_xlabel("Returns")
            ax.set_ylabel("Frequency")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            dist_path = output_dir / "returns_distribution.png"
            plt.savefig(dist_path, dpi=150)
            plt.close()
            plot_files.append(dist_path)

        except ImportError:
            pass  # matplotlib not available, skip plots

    # Add plot images to HTML
    for plot_path in plot_files:
        rel_path = plot_path.name
        html_parts.append(
            f"<div class='chart'><img src='{rel_path}' alt='{plot_path.stem}'></div>"
        )

    # Close HTML
    html_parts.append("""
</div>
</body>
</html>
""")

    # Write HTML file
    html_path = output_dir / "tear_sheet.html"
    with open(html_path, "w") as f:
        f.write("\n".join(html_parts))

    # Also write a JSON summary
    summary_path = output_dir / "tear_sheet_summary.json"
    summary = {
        "symbol": symbol,
        "strategy": strategy_name,
        "metrics": {k: v for k, v in metrics.items() if isinstance(v, (str, int, float, bool, type(None)))},
        "plot_files": [str(p) for p in plot_files],
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Tear sheet saved to: {html_path}")
    print(f"Summary saved to: {summary_path}")
    return str(html_path)


if __name__ == "__main__":
    # Test with sample data
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=252, freq="B")
    sample_returns = pd.Series(np.random.normal(0.0005, 0.015, 252), index=dates)
    sample_equity = (1 + sample_returns).cumprod() * 100000

    sample_results = {
        "equity_curve": sample_equity,
        "returns": sample_returns,
        "config": {"initial_capital": 100000},
    }

    from performance import calculate_metrics

    sample_metrics = calculate_metrics(sample_results)
    generate_tear_sheet(sample_results, sample_metrics, "test_output", symbol="SPY", strategy_name="SMA Crossover")
    print("Tear sheet generation complete.")
