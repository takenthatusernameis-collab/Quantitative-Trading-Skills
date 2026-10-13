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
from typing import Dict, Any, Union, Optional, List, Tuple


def generate_parameter_heatmap(
    optimization_results: List[Dict[str, Any]],
    param_x: str,
    param_y: str,
    metric: str = "sharpe_ratio",
    save_path: Optional[Union[str, Path]] = None,
    cmap: str = "RdYlGn",
    title: Optional[str] = None,
) -> Optional[Any]:
    """
    Generate a 2D parameter sensitivity heatmap from optimization results.

    Args:
        optimization_results: List of result dicts from parameter_optimization,
            each containing 'params', 'sharpe_ratio', 'total_return', and
            optionally 'deflated_sharpe' with 'deflated_sharpe_ratio'.
        param_x: Name of the parameter for the x-axis.
        param_y: Name of the parameter for the y-axis.
        metric: Metric to visualize. Options: 'sharpe_ratio', 'deflated_sharpe_ratio',
            'total_return'. Default: 'sharpe_ratio'.
        save_path: Optional path to save the figure. If None, figure is returned
            without saving.
        cmap: Matplotlib colormap name. Default: 'RdYlGn'.
        title: Optional custom title. If None, generated from metric name.

    Returns:
        Matplotlib figure object, or None if matplotlib is unavailable or
        the grid is invalid.

    Notes:
        - Handles non-rectangular grids (missing combos appear as NaN/white).
        - Degenerate DSR dicts (z_score=None) are treated as NaN for coloring.
        - Requires exactly two varying parameters in the grid; returns None otherwise.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not optimization_results:
        return None

    # Extract the two varying parameter names from results
    all_params = [r.get("params", {}) for r in optimization_results]
    param_names = set()
    for p in all_params:
        param_names.update(p.keys())

    # Verify exactly two varying parameters
    varying_params = []
    for name in param_names:
        values = set(p.get(name) for p in all_params if name in p)
        if len(values) > 1:
            varying_params.append(name)

    if len(varying_params) != 2:
        return None

    # Verify requested params are in the varying set
    if param_x not in varying_params or param_y not in varying_params:
        return None

    # Build coordinate arrays
    x_vals = sorted(set(p.get(param_x) for p in all_params if param_x in p))
    y_vals = sorted(set(p.get(param_y) for p in all_params if param_y in p))

    # Create value grid
    grid = np.full((len(y_vals), len(x_vals)), np.nan)
    x_to_idx = {v: i for i, v in enumerate(x_vals)}
    y_to_idx = {v: i for i, v in enumerate(y_vals)}

    for r in optimization_results:
        params = r.get("params", {})
        x = params.get(param_x)
        y = params.get(param_y)
        if x is None or y is None:
            continue

        if metric == "deflated_sharpe_ratio":
            dsr = r.get("deflated_sharpe")
            if dsr is None:
                val = np.nan
            else:
                val = dsr.get("deflated_sharpe_ratio")
                # Degenerate DSR (z_score=None) treated as NaN for coloring
                if dsr.get("z_score") is None:
                    val = np.nan
        elif metric == "sharpe_ratio":
            val = r.get("sharpe_ratio")
        elif metric == "total_return":
            val = r.get("total_return")
        else:
            val = r.get(metric)

        if val is not None and np.isfinite(val):
            ix = x_to_idx.get(x)
            iy = y_to_idx.get(y)
            if ix is not None and iy is not None:
                grid[iy, ix] = val

    # Create figure
    fig, ax = plt.subplots(figsize=(8, 6))

    # Mask NaN values for transparent coloring
    masked_grid = np.ma.masked_invalid(grid)

    im = ax.imshow(
        masked_grid,
        aspect="auto",
        origin="lower",
        cmap=cmap,
        interpolation="nearest",
    )

    # Colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label(metric.replace("_", " ").title(), rotation=270, labelpad=15)

    # Ticks and labels
    ax.set_xticks(range(len(x_vals)))
    ax.set_xticklabels([str(v) for v in x_vals])
    ax.set_yticks(range(len(y_vals)))
    ax.set_yticklabels([str(v) for v in y_vals])
    ax.set_xlabel(param_x)
    ax.set_ylabel(param_y)

    if title is None:
        title = f"Parameter Sensitivity: {metric.replace('_', ' ').title()}"
    ax.set_title(title)

    # Annotate cells with values
    for iy in range(len(y_vals)):
        for ix in range(len(x_vals)):
            val = grid[iy, ix]
            if not np.isnan(val):
                ax.text(
                    ix,
                    iy,
                    f"{val:.3f}",
                    ha="center",
                    va="center",
                    color="black" if val > np.nanmean(grid) else "white",
                    fontsize=9,
                )

    plt.tight_layout()

    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig


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
            ("Trades Closed at End", "trades_closed_at_end", fmt_num),
            ("Pct Trades Closed at End", "pct_trades_closed_at_end", fmt_pct),
        ]
        for label, key, fmt in trade_metrics:
            if key in metrics:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(metrics[key])}</td></tr>")
        html_parts.append("</table>")

    # Multiple-testing correction: surfaced only when the backtest
    # reported the number of development trials behind it.
    dsr = metrics.get("deflated_sharpe")
    if dsr is not None:
        html_parts.append("<h2>Multiple-Testing Correction</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        z_score = dsr.get("z_score")
        dsr_rows = [
            ("Deflated Sharpe Ratio", dsr.get("deflated_sharpe_ratio"), lambda v: f"{v:.4f}"),
            ("P-Value", dsr.get("p_value"), lambda v: f"{v:.4f}"),
            ("Expected Max Sharpe", dsr.get("expected_max_sharpe"), lambda v: f"{v:.4f}"),
            ("Z-Score", z_score, lambda v: f"{v:.4f}"),
            ("Number of Trials", dsr.get("n_trials"), lambda v: f"{int(v)}"),
            ("Observations", dsr.get("n_observations"), lambda v: f"{int(v)}"),
        ]
        for label, val, fmt in dsr_rows:
            display = fmt(val) if val is not None else "N/A"
            html_parts.append(f"<tr><td>{label}</td><td class='metric'>{display}</td></tr>")
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
    if save_plots:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            # Parameter sensitivity heatmap (from parameter_optimization results)
            param_opt_results = results.get("parameter_optimization")
            if param_opt_results:
                # Detect the two varying parameters
                all_params = [r.get("params", {}) for r in param_opt_results]
                param_names = set()
                for p in all_params:
                    param_names.update(p.keys())
                varying_params = []
                for name in param_names:
                    values = set(p.get(name) for p in all_params if name in p)
                    if len(values) > 1:
                        varying_params.append(name)

                if len(varying_params) == 2:
                    param_x, param_y = varying_params[0], varying_params[1]
                    heatmap_path = output_dir / "parameter_heatmap.png"
                    fig = generate_parameter_heatmap(
                        param_opt_results,
                        param_x=param_x,
                        param_y=param_y,
                        metric="sharpe_ratio",
                        save_path=heatmap_path,
                    )
                    if fig is not None:
                        plt.close(fig)
                        plot_files.append(heatmap_path)

            if returns is not None:
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
    # The Deflated Sharpe Ratio is a dict, so it is filtered out of
    # the scalar-only `metrics` field above; surface it explicitly.
    if "deflated_sharpe" in metrics:
        summary["deflated_sharpe"] = metrics["deflated_sharpe"]
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
