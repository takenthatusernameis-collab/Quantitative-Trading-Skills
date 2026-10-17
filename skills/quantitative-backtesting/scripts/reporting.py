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


def _json_safe(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalar types to JSON-safe Python types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int, float, str, bool, type(None))):
        if isinstance(obj, float) and not np.isfinite(obj):
            return None
        return obj
    return str(obj)


def _format_params(params: Optional[Dict[str, Any]]) -> str:
    """Format a params dict as a readable 'k1=v1, k2=v2' string."""
    if not params:
        return "N/A"
    return ", ".join(f"{k}={v}" for k, v in params.items())


def _fmt_sharpe(val: Any) -> str:
    """Format a Sharpe ratio value, handling None/NaN/np types."""
    if val is None:
        return "N/A"
    if isinstance(val, (int, float, np.floating)) and np.isfinite(float(val)):
        return f"{float(val):.4f}"
    return "N/A"


def _extract_benchmark_metrics(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reconstruct the per-benchmark stats list from ``metrics``.

    Two sources are possible, in priority order:

    (a) ``benchmark_metrics`` — a list of per-benchmark stat dicts surfaced
        directly by the validation pipelines (walk-forward / CPCV / OOS /
        Monte Carlo) on their summaries.
    (b) ``benchmark_N_*`` keys — produced by ``calculate_metrics`` when
        ``results["benchmark_list"]`` has 2+ entries (the run_backtest CLI
        path). Reconstruct rows from those prefixed keys so both shapes are
        handled uniformly by the HTML tear sheet and the JSON summary.

    Returns an empty list when no benchmark metrics are present.
    """
    bench_metrics_list = metrics.get("benchmark_metrics")
    if isinstance(bench_metrics_list, list) and bench_metrics_list:
        return bench_metrics_list
    reconstructed: List[Dict[str, Any]] = []
    i = 0
    while True:
        prefix = f"benchmark_{i}_"
        # Look for any prefixed key to detect the index exists
        has_any = any(k.startswith(prefix) for k in metrics.keys())
        if not has_any:
            break
        row = {
            k[len(prefix):]: v
            for k, v in metrics.items()
            if k.startswith(prefix)
        }
        reconstructed.append(row)
        i += 1
        if i > 20:  # safety bound
            break
    return reconstructed


def generate_tear_sheet(
    results: Dict[str, Any],
    metrics: Dict[str, Any],
    output_dir: Union[str, Path],
    symbol: str = "N/A",
    strategy_name: str = "N/A",
    save_plots: bool = True,
    analysis_results: Optional[Dict[str, Any]] = None,
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
        analysis_results: Optional dict with keys 'walk_forward', 'cpcv',
            and/or 'monte_carlo' containing respective analysis outputs to
            render as additional tear-sheet sections.

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
            ("Benchmark Annualized Return", "benchmark_annualized_return", fmt_pct),
            ("Benchmark Return Type", "benchmark_total_return_type", lambda v: str(v)),
            ("Benchmark Commission", "benchmark_commission", lambda v: f"{v:.4f}"),
            ("Benchmark Slippage", "benchmark_slippage", lambda v: f"{v:.4f}"),
            ("Correlation", "correlation_with_benchmark", fmt_num),
            ("Alpha", "alpha", fmt_pct),
            ("Beta", "beta", fmt_num),
        ]
        for label, key, fmt in bench_metrics:
            if key in metrics:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(metrics[key])}</td></tr>")
        sig_metrics = [
            ("Alpha t-statistic", "alpha_tstat", fmt_num),
            ("Alpha p-value", "alpha_pvalue", fmt_num),
            ("R-squared", "r_squared", fmt_num),
        ]
        for label, key, fmt in sig_metrics:
            if key in metrics:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(metrics[key])}</td></tr>")
        html_parts.append("</table>")

    # Multiple-testing correction across benchmarks: surfaced by
    # ``calculate_metrics`` when ``results["benchmark_list"]`` has 2+ entries
    # (the canonical Deflated Alpha Ratio). Distinct from the single-benchmark
    # ``deflated_sharpe`` section above, which is trial-count based.
    da = metrics.get("deflated_alpha")
    if isinstance(da, dict):
        html_parts.append("<h2>Multiple-Testing Correction (Deflated Alpha)</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        da_rows = [
            ("Deflated Alpha Ratio", da.get("deflated_alpha_ratio"), lambda v: f"{v:.4f}"),
            ("P-Value", da.get("p_value"), lambda v: f"{v:.4f}"),
            ("Expected Max Alpha", da.get("expected_max_alpha"), lambda v: f"{v:.4f}"),
            ("Z-Score", da.get("z_score"), lambda v: f"{v:.4f}"),
            ("Number of Benchmarks", da.get("n_benchmarks"), lambda v: str(int(v))),
            ("Observations", da.get("n_observations"), lambda v: str(int(v))),
            ("Skewness", da.get("skewness"), lambda v: f"{v:.4f}"),
            ("Kurtosis", da.get("kurtosis"), lambda v: f"{v:.4f}"),
        ]
        for label, val, fmt in da_rows:
            display = fmt(val) if val is not None else "N/A"
            html_parts.append(f"<tr><td>{label}</td><td class='metric'>{display}</td></tr>")
        html_parts.append("</table>")

        # Per-benchmark detail. Two sources are possible:
        #   (a) ``benchmark_metrics`` — a list of per-benchmark stat dicts, surfaced
        #       directly by the validation pipelines (CPCV/walk-forward/OOS/Monte Carlo)
        #       on their summaries and passed through to the tear sheet.
        #   (b) ``benchmark_N_*`` keys — produced by ``calculate_metrics`` when
        #       ``results["benchmark_list"]`` has 2+ entries (e.g. the Monte Carlo
        #       tear sheet built from ``mc_base_results``). Reconstruct rows from
        #       those prefixed keys so the detail section renders either way.
        bench_metrics_list = _extract_benchmark_metrics(metrics)
        if bench_metrics_list:
            html_parts.append("<h3>Per-Benchmark Comparison</h3>")
            html_parts.append(
                "<table><tr><th>Benchmark</th><th>Alpha</th><th>Beta</th>"
                "<th>Correlation</th><th>Alpha P-Value</th><th>Deflated Alpha</th>"
                "<th>Expected Max Alpha</th></tr>"
            )
            for i, bm in enumerate(bench_metrics_list):
                if not isinstance(bm, dict):
                    continue
                alpha = bm.get("alpha")
                beta = bm.get("beta")
                corr = bm.get("correlation_with_benchmark", bm.get("correlation"))
                pval = bm.get("alpha_pvalue", bm.get("alpha_pvalue_original"))
                da_val = bm.get("deflated_alpha")
                ema = bm.get("expected_max_alpha")
                html_parts.append(
                    f"<tr><td>Benchmark {i}</td>"
                    f"<td class='metric'>{fmt_pct(alpha) if isinstance(alpha, (int, float)) else 'N/A'}</td>"
                    f"<td class='metric'>{fmt_num(beta) if isinstance(beta, (int, float)) else 'N/A'}</td>"
                    f"<td class='metric'>{fmt_num(corr) if isinstance(corr, (int, float)) else 'N/A'}</td>"
                    f"<td class='metric'>{fmt_num(pval) if isinstance(pval, (int, float)) else 'N/A'}</td>"
                    f"<td class='metric'>{fmt_num(da_val) if isinstance(da_val, (int, float)) else 'N/A'}</td>"
                    f"<td class='metric'>{fmt_num(ema) if isinstance(ema, (int, float)) else 'N/A'}</td>"
                    "</tr>"
                )
            html_parts.append("</table>")

    # Analysis results: walk-forward, CPCV, Monte Carlo
    analysis = analysis_results or {}

    wf_results = analysis.get("walk_forward")
    if wf_results:
        wf_summary = wf_results.get("summary", {})
        html_parts.append("<h2>Walk-Forward Analysis</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        wf_metrics = [
            ("Number of Periods", "n_periods", fmt_num),
            ("Total OOS Return", "total_oos_return", fmt_pct),
            ("OOS Sharpe Ratio", "oos_sharpe", fmt_num),
            ("OOS Volatility", "oos_volatility", fmt_pct),
            ("OOS Win Rate", "win_rate_periods", fmt_pct),
            ("Avg Period Return", "avg_period_return", fmt_pct),
        ]
        for label, key, fmt in wf_metrics:
            if key in wf_summary:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(wf_summary[key])}</td></tr>")
        html_parts.append("</table>")

        periods = wf_results.get("periods", [])
        if periods:
            html_parts.append("<h3>Best Parameters Per Period</h3>")
            html_parts.append("<table><tr><th>Period</th><th>Best Params</th><th>In-Sample Sharpe</th></tr>")
            for i, p in enumerate(periods):
                params_str = _format_params(p.get("best_params"))
                sharpe_str = _fmt_sharpe(p.get("best_sharpe"))
                html_parts.append(f"<tr><td>{i + 1}</td><td>{params_str}</td><td class='metric'>{sharpe_str}</td></tr>")
            html_parts.append("</table>")

        wf_dsr = wf_summary.get("deflated_sharpe")
        if wf_dsr:
            html_parts.append("<h3>Walk-Forward Multiple-Testing Correction</h3>")
            html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
            wf_dsr_rows = [
                ("Deflated Sharpe Ratio", wf_dsr.get("deflated_sharpe_ratio"), lambda v: f"{v:.4f}"),
                ("P-Value", wf_dsr.get("p_value"), lambda v: f"{v:.4f}"),
                ("Expected Max Sharpe", wf_dsr.get("expected_max_sharpe"), lambda v: f"{v:.4f}"),
                ("Z-Score", wf_dsr.get("z_score"), lambda v: f"{v:.4f}"),
                ("Number of Trials", wf_dsr.get("n_trials"), lambda v: str(int(v))),
                ("Observations", wf_dsr.get("n_observations"), lambda v: str(int(v))),
            ]
            for label, val, fmt in wf_dsr_rows:
                display = fmt(val) if val is not None else "N/A"
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{display}</td></tr>")
            html_parts.append("</table>")

    # Data provenance: surface source path, checksum, date range, filters,
    # transformations, and validation outcome so each tear sheet is
    # traceable to its input. Handles the single-asset (flat dict) and
    # per-symbol panel (dict of {symbol: prov_dict}) provenance forms, and
    # also surfaces the point-in-time validation outcome captured at the
    # results level (not inside the DataProvenance dict itself).
    data_prov = results.get("data_provenance")
    pit_val = results.get("point_in_time_validation")
    # Bias-controls engagement flag (point-in-time validation, survivorship
    # screening, and multiple-testing deflation). Mirrors the JSON summary
    # key so the HTML tear sheet is traceable to the same signal.
    bias_flag = results.get("bias_controls_engaged")
    if bias_flag is None:
        # Fall back to the analysis-result summaries (walk-forward / CPCV /
        # Monte Carlo) when the flag was recorded there rather than at the
        # top-level results dict.
        for _analysis in (analysis or {}).values():
            if isinstance(_analysis, dict) and isinstance(_analysis.get("summary"), dict):
                bias_flag = _analysis["summary"].get("bias_controls_engaged")
                if bias_flag is not None:
                    break
    if data_prov or pit_val or bias_flag is not None:
        html_parts.append("<h2>Data Provenance</h2>")
        html_parts.append("<table><tr><th>Field</th><th>Value</th></tr>")

        def fmt_prov(v):
            if v is None:
                return "N/A"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (dict, list)):
                return json.dumps(v)
            if isinstance(v, (int, float)):
                return str(v)
            return str(v)

        prov_fields = [
            "source_path", "load_timestamp", "file_format", "file_size_bytes",
            "symbol_filter", "start_date_filter", "end_date_filter",
            "date_range_original", "date_range_final", "original_shape",
            "final_shape", "columns_original", "columns_final",
            "validation_passed", "validation_messages",
            "transformations_applied", "checksum",
        ]

        # Per-symbol panel provenance: dict of {symbol: prov_dict}
        first_val = next(iter(data_prov.values()), None) if data_prov else None
        is_panel = (
            isinstance(data_prov, dict)
            and isinstance(first_val, dict)
            and "source_path" in first_val
        )
        if is_panel:
            for sym, prov in data_prov.items():
                for field in prov_fields:
                    if field in prov:
                        html_parts.append(
                            f"<tr><td>{sym} / {field}</td><td class='metric'>{fmt_prov(prov[field])}</td></tr>"
                        )
        elif isinstance(data_prov, dict):
            for field in prov_fields:
                if field in data_prov:
                    html_parts.append(
                        f"<tr><td>{field}</td><td class='metric'>{fmt_prov(data_prov[field])}</td></tr>"
                    )

        if pit_val is not None:
            for field in ["passed", "violations", "warnings"]:
                if field in pit_val:
                    html_parts.append(
                        f"<tr><td>point_in_time / {field}</td><td class='metric'>{fmt_prov(pit_val[field])}</td></tr>"
                    )

        # Bias-controls engagement flag (point-in-time validation, survivorship
        # screening, and multiple-testing deflation). Mirrors the JSON summary
        # key so the HTML tear sheet is traceable to the same signal.
        bias_flag = results.get("bias_controls_engaged")
        if bias_flag is None:
            # Fall back to the analysis-result summaries (walk-forward / CPCV /
            # Monte Carlo) when the flag was recorded there rather than at the
            # top-level results dict.
            for _analysis in (analysis or {}).values():
                if isinstance(_analysis, dict) and isinstance(_analysis.get("summary"), dict):
                    bias_flag = _analysis["summary"].get("bias_controls_engaged")
                    if bias_flag is not None:
                        break
        if bias_flag is not None:
            html_parts.append(
                f"<tr><td>bias_controls_engaged</td>"
                f"<td class='metric'>{fmt_prov(bool(bias_flag))}</td></tr>"
            )

        html_parts.append("</table>")

    cpcv_results = analysis.get("cpcv")
    if cpcv_results:
        cpcv_summary = cpcv_results.get("summary", {})
        html_parts.append("<h2>CPCV Analysis</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        cpcv_metrics = [
            ("Number of Folds", "n_folds", fmt_num),
            ("Total OOS Return", "total_oos_return", fmt_pct),
            ("OOS Sharpe Ratio", "oos_sharpe", fmt_num),
            ("OOS Volatility", "oos_volatility", fmt_pct),
            ("OOS Win Rate", "win_rate_folds", fmt_pct),
            ("Avg Fold Return", "avg_fold_return", fmt_pct),
            ("Avg Parameter Stability", "avg_param_stability", fmt_pct),
            ("Overfitting Risk", "overfitting_risk", lambda v: str(v)),
        ]
        for label, key, fmt in cpcv_metrics:
            if key in cpcv_summary:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(cpcv_summary[key])}</td></tr>")
        html_parts.append("</table>")

        param_stability = cpcv_results.get("param_stability", {})
        if param_stability:
            html_parts.append("<h3>Parameter Stability</h3>")
            html_parts.append("<table><tr><th>Parameter</th><th>Unique Values</th><th>Most Common</th><th>Stability Ratio</th></tr>")
            for name, stats in param_stability.items():
                if isinstance(stats, dict):
                    html_parts.append(
                        f"<tr><td>{name}</td><td>{stats.get('unique_values', 'N/A')}</td>"
                        f"<td>{stats.get('most_common', 'N/A')}</td>"
                        f"<td class='metric'>{fmt_pct(stats.get('stability_ratio', 0))}</td></tr>"
                    )
            html_parts.append("</table>")

        folds = cpcv_results.get("folds", [])
        if folds:
            html_parts.append("<h3>Best Parameters Per Fold</h3>")
            html_parts.append("<table><tr><th>Fold</th><th>Best Params</th><th>Best Sharpe</th></tr>")
            for f in folds:
                params_str = _format_params(f.get("best_params"))
                sharpe_str = _fmt_sharpe(f.get("best_sharpe"))
                html_parts.append(f"<tr><td>{f.get('fold', '?')}</td><td>{params_str}</td><td class='metric'>{sharpe_str}</td></tr>")
            html_parts.append("</table>")

        cpcv_dsr = cpcv_summary.get("deflated_sharpe")
        if cpcv_dsr:
            html_parts.append("<h3>CPCV Multiple-Testing Correction</h3>")
            html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
            cpcv_dsr_rows = [
                ("Deflated Sharpe Ratio", cpcv_dsr.get("deflated_sharpe_ratio"), lambda v: f"{v:.4f}"),
                ("P-Value", cpcv_dsr.get("p_value"), lambda v: f"{v:.4f}"),
                ("Expected Max Sharpe", cpcv_dsr.get("expected_max_sharpe"), lambda v: f"{v:.4f}"),
                ("Number of Trials", cpcv_dsr.get("n_trials"), lambda v: str(int(v))),
            ]
            for label, val, fmt in cpcv_dsr_rows:
                display = fmt(val) if val is not None else "N/A"
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{display}</td></tr>")
            html_parts.append("</table>")

    mc_results = analysis.get("monte_carlo")
    if mc_results:
        html_parts.append("<h2>Monte Carlo Simulation</h2>")
        html_parts.append("<table><tr><th>Metric</th><th>Value</th></tr>")
        for label, key, fmt in [
            ("Number of Simulations", "n_simulations", fmt_num),
            ("Base Observations", "base_observations", fmt_num),
            ("Probability of Ruin", "probability_of_ruin", fmt_pct),
            ("Ruin Threshold", "ruin_threshold", fmt_pct),
        ]:
            if key in mc_results and mc_results[key] is not None:
                html_parts.append(f"<tr><td>{label}</td><td class='metric'>{fmt(mc_results[key])}</td></tr>")
        html_parts.append("</table>")

        cis = mc_results.get("confidence_intervals", {})
        if cis:
            html_parts.append("<h3>Confidence Intervals</h3>")
            html_parts.append("<table><tr><th>Metric</th><th>90%</th><th>95%</th><th>99%</th></tr>")
            for metric, level_cis in cis.items():
                cells = []
                for level in [0.90, 0.95, 0.99]:
                    ci = level_cis.get(level)
                    if ci and len(ci) == 2:
                        cells.append(f"[{ci[0]:.4f}, {ci[1]:.4f}]")
                    else:
                        cells.append("N/A")
                html_parts.append(f"<tr><td>{metric}</td><td>{cells[0]}</td><td>{cells[1]}</td><td>{cells[2]}</td></tr>")
            html_parts.append("</table>")

        mc_summary = mc_results.get("summary", {})
        if mc_summary:
            html_parts.append("<h3>Metric Distributions</h3>")
            html_parts.append("<table><tr><th>Metric</th><th>Mean</th><th>Std</th><th>Median</th><th>Min</th><th>Max</th></tr>")
            for metric, stats in mc_summary.items():
                if isinstance(stats, dict):
                    cells = []
                    for field in ["mean", "std", "median", "min", "max"]:
                        v = stats.get(field)
                        if isinstance(v, (int, float, np.floating)) and np.isfinite(float(v)):
                            cells.append(f"{float(v):.4f}")
                        else:
                            cells.append("N/A")
                    html_parts.append(f"<tr><td>{metric}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
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

                # Monte Carlo equity curve fan chart
                mc_results = analysis.get("monte_carlo")
                if mc_results and mc_results.get("simulated_equity_curves"):
                    mc_curves = mc_results["simulated_equity_curves"]
                    valid_curves = [
                        c for c in mc_curves
                        if isinstance(c, (pd.Series, pd.DataFrame))
                        and len(c.dropna()) > 0
                    ]
                    if valid_curves:
                        try:
                            curve_series = []
                            for c in valid_curves:
                                if isinstance(c, pd.DataFrame):
                                    c = c.iloc[:, 0]
                                curve_series.append(c)
                            curve_df = pd.concat(curve_series, axis=1)
                            if not curve_df.empty:
                                fig, ax = plt.subplots(figsize=(12, 4))
                                percentiles = [5, 25, 50, 75, 95]
                                bands = {
                                    p: curve_df.quantile(p / 100, axis=1)
                                    for p in percentiles
                                }
                                ax.fill_between(
                                    curve_df.index, bands[5], bands[95],
                                    alpha=0.2, color="steelblue", label="90% CI",
                                )
                                ax.fill_between(
                                    curve_df.index, bands[25], bands[75],
                                    alpha=0.3, color="steelblue", label="50% CI",
                                )
                                ax.plot(curve_df.index, bands[50], color="steelblue",
                                        label="Median", linewidth=1.5)
                                ax.set_title("Monte Carlo Equity Curve Distribution")
                                ax.set_ylabel("Normalized Equity")
                                ax.set_xlabel("Date")
                                ax.legend()
                                ax.grid(True, alpha=0.3)
                                plt.tight_layout()
                                mc_path = output_dir / "monte_carlo_equity_curve.png"
                                plt.savefig(mc_path, dpi=150, bbox_inches="tight")
                                plt.close()
                                plot_files.append(mc_path)
                        except Exception:
                            pass

                # Walk-forward equity curve plot
                wf_results = analysis.get("walk_forward")
                if wf_results and wf_results.get("oos_returns") is not None:
                    wf_oos_returns = wf_results["oos_returns"]
                    if isinstance(wf_oos_returns, pd.Series) and len(wf_oos_returns) > 0:
                        try:
                            wf_equity = (1 + wf_oos_returns).cumprod() * 100000
                            fig, ax = plt.subplots(figsize=(12, 4))
                            ax.plot(wf_equity.index, wf_equity.values, color="darkgreen")
                            ax.set_title("Walk-Forward Out-of-Sample Equity Curve")
                            ax.set_ylabel("Portfolio Value")
                            ax.set_xlabel("Date")
                            ax.grid(True, alpha=0.3)
                            plt.tight_layout()
                            wf_path = output_dir / "walk_forward_equity_curve.png"
                            plt.savefig(wf_path, dpi=150)
                            plt.close()
                            plot_files.append(wf_path)
                        except Exception:
                            pass

                # CPCV equity curve plot
                cpcv_results = analysis.get("cpcv")
                if cpcv_results and cpcv_results.get("oos_returns") is not None:
                    cpcv_oos_returns = cpcv_results["oos_returns"]
                    if isinstance(cpcv_oos_returns, pd.Series) and len(cpcv_oos_returns) > 0:
                        try:
                            cpcv_equity = (1 + cpcv_oos_returns).cumprod() * 100000
                            fig, ax = plt.subplots(figsize=(12, 4))
                            ax.plot(cpcv_equity.index, cpcv_equity.values, color="darkorange")
                            ax.set_title("CPCV Out-of-Sample Equity Curve")
                            ax.set_ylabel("Portfolio Value")
                            ax.set_xlabel("Date")
                            ax.grid(True, alpha=0.3)
                            plt.tight_layout()
                            cpcv_path = output_dir / "cpcv_equity_curve.png"
                            plt.savefig(cpcv_path, dpi=150)
                            plt.close()
                            plot_files.append(cpcv_path)
                        except Exception:
                            pass

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
    # The aggregate Deflated Alpha Ratio (multiple-benchmark correction) is a
    # dict, so it is likewise filtered out of the scalar-only `metrics` field;
    # surface it explicitly so the run_backtest CLI tear sheet carries the same
    # aggregate correction the walk-forward / CPCV / OOS summaries emit.
    if "deflated_alpha" in metrics:
        summary["deflated_alpha"] = _json_safe(metrics["deflated_alpha"])

    # Surface analysis results in the JSON summary (JSON-safe extraction only).
    if analysis:
        wf = analysis.get("walk_forward")
        if wf:
            summary["walk_forward"] = {
                "summary": _json_safe(wf.get("summary", {})),
                "best_params_per_period": _json_safe(wf.get("best_params_per_period", [])),
            }
        cpcv = analysis.get("cpcv")
        if cpcv:
            summary["cpcv"] = {
                "summary": _json_safe(cpcv.get("summary", {})),
                "param_stability": _json_safe(cpcv.get("param_stability", {})),
                "best_params_per_fold": _json_safe(cpcv.get("best_params_per_fold", [])),
            }
        mc = analysis.get("monte_carlo")
        if mc:
            summary["monte_carlo"] = {
                "summary": _json_safe(mc.get("summary", {})),
                "confidence_intervals": _json_safe(mc.get("confidence_intervals", {})),
                "probability_of_ruin": mc.get("probability_of_ruin"),
                "ruin_threshold": mc.get("ruin_threshold"),
                "n_simulations": mc.get("n_simulations"),
                "base_observations": mc.get("base_observations"),
            }

    # Surface the per-benchmark Deflated Alpha metrics in the JSON summary
    # when 2+ benchmarks were tested (the canonical multiple-testing
    # correction). ``calculate_metrics`` only emits the ``benchmark_N_*``
    # prefixed scalar keys for the run_backtest CLI path, so reconstruct the
    # per-benchmark dicts here (mirroring the HTML reconstruction below) and
    # expose them as ``benchmark_metrics`` — the same key the walk-forward /
    # CPCV / OOS summaries use, so downstream consumers see one shape.
    # Omitted when fewer than 2 benchmarks are present, exactly as the
    # walk-forward path does (single-benchmark runs keep the non-prefixed
    # ``alpha`` / ``beta`` / ``correlation_with_benchmark`` keys).
    bench_metrics_list = _extract_benchmark_metrics(metrics)
    # Associate each benchmark_metrics row with its provenance so downstream
    # consumers can trace corrected alpha/deflated alpha back to the exact
    # benchmark file/checksum without relying on list order alone.
    bp = results.get("benchmark_provenance")
    if bp is not None and isinstance(bench_metrics_list, list) and bench_metrics_list:
        if not isinstance(bp, list):
            bp_list = [bp]
        else:
            bp_list = bp
        prov_dicts = []
        for p in bp_list:
            prov_dicts.append(p.to_dict() if hasattr(p, "to_dict") else (p if isinstance(p, dict) else p))
        if len(prov_dicts) == len(bench_metrics_list):
            for row, prov in zip(bench_metrics_list, prov_dicts):
                if isinstance(row, dict):
                    row["benchmark_provenance"] = prov
    if len(bench_metrics_list) >= 2:
        summary["benchmark_metrics"] = _json_safe(bench_metrics_list)

    # Surface data provenance and point-in-time validation outcome in JSON
    # summary, if present (backward compatible: omitted when absent).
    if results.get("data_provenance"):
        summary["data_provenance"] = _json_safe(results["data_provenance"])
    # Surface benchmark provenance (full list when multiple, single dict when one).
    bp = results.get("benchmark_provenance")
    if bp is not None:
        if isinstance(bp, list):
            if len(bp) == 1:
                p = bp[0]
                summary["benchmark_provenance"] = _json_safe(p.to_dict() if hasattr(p, "to_dict") else p)
            else:
                summary["benchmark_provenance"] = _json_safe([p.to_dict() if hasattr(p, "to_dict") else p for p in bp])
        elif hasattr(bp, "to_dict"):
            summary["benchmark_provenance"] = _json_safe(bp.to_dict())
        else:
            # If it's already a dict/list, preserve appropriate shape? but dict means single
            summary["benchmark_provenance"] = _json_safe(bp)
    if results.get("point_in_time_validation"):
        summary["point_in_time_validation"] = _json_safe(
            results["point_in_time_validation"]
        )
    # Bias-controls engagement flag (PIT + deflation controls). Mirrors the
    # walk-forward / CPCV / Monte Carlo summaries so the tear-sheet JSON is
    # traceable to the same signal; omitted when absent (backward compatible).
    bias_flag = results.get("bias_controls_engaged")
    if bias_flag is None:
        for _analysis in (analysis or {}).values():
            if isinstance(_analysis, dict) and isinstance(_analysis.get("summary"), dict):
                bias_flag = _analysis["summary"].get("bias_controls_engaged")
                if bias_flag is not None:
                    break
    if bias_flag is not None:
        summary["bias_controls_engaged"] = bool(bias_flag)

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
