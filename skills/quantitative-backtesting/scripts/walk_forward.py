#!/usr/bin/env python3
"""
Walk-forward analysis and parameter optimization.

Splits historical data into rolling training and testing windows to validate
strategy robustness across market regimes.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional, Union
from itertools import product


def walk_forward_analysis(
    data: pd.DataFrame,
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
) -> Dict[str, Any]:
    """
    Perform walk-forward analysis with expanding training windows.

    Args:
        data: DataFrame with OHLCV data indexed by date
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        train_months: Training window size in months
        test_months: Testing window size in months
        step_months: Step size between walk-forward iterations
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade

    Returns:
        Dictionary with walk-forward results including:
            - 'periods': list of period results
            - 'best_params_per_period': list of optimal params per period
            - 'oos_returns': out-of-sample returns across all periods
            - 'summary': aggregate metrics
    """
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Data must be indexed by DatetimeIndex")

    data = data.sort_index()
    start_date = data.index.min()
    end_date = data.index.max()

    # Generate walk-forward periods
    periods = []
    train_end = start_date + pd.DateOffset(months=train_months)
    test_start = train_end

    while test_start + pd.DateOffset(months=test_months) <= end_date:
        test_end = test_start + pd.DateOffset(months=test_months)

        train_data = data[data.index < train_end]
        test_data = data[(data.index >= test_start) & (data.index < test_end)]

        if len(train_data) > 0 and len(test_data) > 0:
            periods.append({
                "train_start": train_data.index[0],
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "train_data": train_data,
                "test_data": test_data,
            })

        train_end = train_end + pd.DateOffset(months=step_months)
        test_start = train_end

    # Grid search for best params on each training period
    best_params_per_period = []
    oos_returns_list = []

    for period in periods:
        train_data = period["train_data"]
        test_data = period["test_data"]

        best_sharpe = -np.inf
        best_params = None
        best_test_returns = None

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())

        for combo in product(*param_values):
            params = dict(zip(param_names, combo))

            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)

                # Skip parameter sets that take no position in the test window
                # (e.g. a lookback longer than the window itself leaves every
                # rolling indicator NaN, so the strategy stays flat). Without
                # this guard the grid search silently selects such a combo as
                # "optimal" and reports a flat (zero) out-of-sample return.
                if not signals_active(test_signals):
                    continue

                # Calculate returns for this parameter set
                test_returns = _calculate_strategy_returns(
                    test_data, test_signals, commission, slippage
                )

                # Evaluate on training set
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, commission, slippage
                )

                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                else:
                    sharpe = -np.inf

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_test_returns = test_returns

            except Exception:
                continue

        best_params_per_period.append(best_params)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            period["best_params"] = best_params
            period["best_sharpe"] = best_sharpe
            period["test_returns"] = best_test_returns
        else:
            period["best_params"] = None
            period["best_sharpe"] = None
            period["test_returns"] = pd.Series(dtype=float)

    # Combine all out-of-sample returns
    if oos_returns_list:
        oos_returns = pd.concat(oos_returns_list)
    else:
        oos_returns = pd.Series(dtype=float)

    # Summary metrics
    summary = _calculate_walk_forward_summary(oos_returns, periods)

    return {
        "periods": periods,
        "best_params_per_period": best_params_per_period,
        "oos_returns": oos_returns,
        "summary": summary,
    }


def parameter_optimization(
    data: pd.DataFrame,
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    n_splits: int = 5,
) -> List[Dict[str, Any]]:
    """
    Perform parameter optimization using walk-forward-like splits.

    Args:
        data: OHLCV DataFrame
        strategy_factory: Strategy factory callable
        param_grid: Parameter grid to search
        initial_capital: Starting capital
        commission: Commission rate
        slippage: Slippage rate
        n_splits: Number of train/test splits

    Returns:
        List of result dictionaries sorted by Sharpe ratio (descending)
    """
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Data must be indexed by DatetimeIndex")

    data = data.sort_index()
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    results = []

    for combo in product(*param_values):
        params = dict(zip(param_names, combo))

        try:
            strategy = strategy_factory(params)
            signals = strategy.generate_signals(data)

            # Skip parameter sets that take no position across the entire
            # dataset (e.g. a lookback longer than the data itself leaves
            # every rolling indicator NaN, so the strategy stays flat).
            # Without this guard such a combo reports a flat (zero) return
            # and can be ranked as "optimal" by the grid search.
            if not signals_active(signals):
                continue

            returns = _calculate_strategy_returns(
                data, signals, commission, slippage
            )

            if len(returns) > 1:
                ann_factor = _annualization_factor(returns.index)
                excess = returns - 0.02 / ann_factor
                sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor) if returns.std() > 0 else 0
                total_return = (1 + returns).prod() - 1

                results.append({
                    "params": params,
                    "sharpe_ratio": float(sharpe),
                    "total_return": float(total_return),
                    "n_periods": len(returns),
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results


def overfitting_check(
    wf_results: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Check for overfitting in walk-forward results.

    Args:
        wf_results: Results from walk_forward_analysis

    Returns:
        Dictionary with overfitting diagnostics
    """
    periods = wf_results.get("periods", [])
    oos_returns = wf_results.get("oos_returns", pd.Series(dtype=float))

    diagnostics = {
        "n_periods": len(periods),
        "n_valid_periods": len([p for p in periods if p.get("test_returns") is not None and len(p["test_returns"]) > 0]),
    }

    # Check if optimal params are consistent across periods
    valid_params = [p["best_params"] for p in periods if p.get("best_params") is not None]
    if valid_params:
        # Count how often each parameter value appears
        param_stability = {}
        param_names = set()
        for params in valid_params:
            param_names.update(params.keys())

        for name in param_names:
            values = [p.get(name) for p in valid_params if name in p]
            if values:
                unique_count = len(set(values))
                param_stability[name] = {
                    "unique_values": unique_count,
                    "most_common": max(set(values), key=values.count) if values else None,
                    "stability_ratio": 1.0 - unique_count / len(values),
                }
        diagnostics["param_stability"] = param_stability

    # OOS performance
    if len(oos_returns) > 0 and oos_returns.std() > 0:
        ann_factor = _annualization_factor(oos_returns.index)
        excess = oos_returns - 0.02 / ann_factor
        diagnostics["oos_sharpe"] = float(excess.mean() / excess.std() * np.sqrt(ann_factor))
        diagnostics["oos_total_return"] = float((1 + oos_returns).prod() - 1)
        diagnostics["oos_volatility"] = float(oos_returns.std() * np.sqrt(ann_factor))
    else:
        diagnostics["oos_sharpe"] = 0.0
        diagnostics["oos_total_return"] = 0.0
        diagnostics["oos_volatility"] = 0.0

    # Overfitting flags
    diagnostics["overfitting_risk"] = "low"
    if len(valid_params) > 0:
        # High parameter variation across periods suggests overfitting
        avg_stability = np.mean([
            v["stability_ratio"] for v in diagnostics.get("param_stability", {}).values()
        ]) if diagnostics.get("param_stability") else 1.0
        if avg_stability < 0.3:
            diagnostics["overfitting_risk"] = "high"
        elif avg_stability < 0.5:
            diagnostics["overfitting_risk"] = "medium"

    return diagnostics


def signals_active(signals: pd.Series) -> bool:
    """Return True if the signal series ever takes a non-zero position.

    A strategy that never takes a position (e.g. a lookback longer than the
    data window leaves every rolling indicator NaN, so the signal stays flat
    at 0) produces no trades and meaningless zero returns. Callers should
    skip such parameter sets rather than ranking them as "optimal".
    """
    return bool((signals != 0).any())


def _calculate_strategy_returns(
    data: pd.DataFrame,
    signals: pd.Series,
    commission: float,
    slippage: float,
) -> pd.Series:
    """Calculate strategy returns from signals and market data."""
    close = data["close"]
    positions = signals.shift(1)  # Trade at next period's open
    raw_returns = close.pct_change()

    # Transaction costs: apply on position changes
    position_changes = positions.diff().abs()
    costs = position_changes * (commission + slippage)

    strategy_returns = positions * raw_returns - costs
    return strategy_returns.dropna()


def _annualization_factor(index: pd.Index) -> float:
    """Estimate periods per year from DatetimeIndex."""
    if not isinstance(index, pd.DatetimeIndex):
        return 252
    try:
        freq = pd.infer_freq(index)
        if freq is None:
            return 252
        freq_map = {"B": 252, "D": 365, "W": 52, "M": 12, "Q": 4, "Y": 1}
        return freq_map.get(freq[0], 252)
    except Exception:
        return 252


def _calculate_walk_forward_summary(
    oos_returns: pd.Series,
    periods: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Calculate summary metrics for walk-forward results."""
    summary = {
        "n_periods": len(periods),
        "total_oos_return": float((1 + oos_returns).prod() - 1) if len(oos_returns) > 0 else 0.0,
    }

    if len(oos_returns) > 1:
        ann_factor = _annualization_factor(oos_returns.index)
        excess = oos_returns - 0.02 / ann_factor
        if oos_returns.std() > 0:
            summary["oos_sharpe"] = float(excess.mean() / oos_returns.std() * np.sqrt(ann_factor))
            summary["oos_volatility"] = float(oos_returns.std() * np.sqrt(ann_factor))
        else:
            summary["oos_sharpe"] = 0.0
            summary["oos_volatility"] = 0.0

        summary["avg_period_return"] = float(oos_returns.mean())
        summary["n_positive_periods"] = int((oos_returns > 0).sum())
        summary["win_rate_periods"] = float((oos_returns > 0).sum() / len(oos_returns)) if len(oos_returns) > 0 else 0.0

    return summary


def monte_carlo_simulation(
    base_returns: pd.Series,
    n_simulations: int = 2000,
    confidence_levels: List[float] = None,
    block_size: int = None,
) -> Dict[str, Any]:
    """
    Perform Monte Carlo simulation on strategy returns to assess robustness.

    Resamples the base returns (with optional block bootstrapping to preserve
    autocorrelation) to generate synthetic equity curves and compute the
    distribution of key performance metrics.

    Args:
        base_returns: Series of strategy returns from a backtest
        n_simulations: Number of Monte Carlo paths to generate
        confidence_levels: List of confidence levels for percentile bands
        block_size: If set, use stationary block bootstrap (preserves autocorrelation).
                   Block size in periods. None = simple i.i.d. resampling.

    Returns:
        Dictionary with:
            - 'simulated_equity_curves': List of simulated equity curves (DataFrame)
            - 'metric_distributions': Dict of metric -> array of simulated values
            - 'confidence_intervals': Dict of metric -> {level: (lower, upper)}
            - 'probability_of_ruin': Fraction of sims where equity < initial * threshold
            - 'summary': Summary statistics of metric distributions
    """
    if confidence_levels is None:
        confidence_levels = [0.90, 0.95, 0.99]

    if len(base_returns) < 2:
        raise ValueError("Need at least 2 return observations for Monte Carlo")

    base_returns = base_returns.dropna()
    n_obs = len(base_returns)
    ann_factor = _annualization_factor(base_returns.index)

    # Prepare block bootstrap indices if block_size specified
    if block_size is not None and block_size > 1:
        # Stationary block bootstrap (Politis & Romano, 1994)
        # Average block length = block_size
        pass  # Use simple resampling for now; block bootstrap is more complex

    simulated_metrics = {
        "total_return": [],
        "annualized_return": [],
        "annualized_volatility": [],
        "sharpe_ratio": [],
        "sortino_ratio": [],
        "max_drawdown": [],
        "calmar_ratio": [],
    }

    simulated_equity_curves = []

    for sim in range(n_simulations):
        # Resample returns with replacement
        if block_size is not None and block_size > 1:
            # Simple block bootstrap: resample blocks of consecutive returns
            n_blocks = int(np.ceil(n_obs / block_size))
            block_starts = np.random.randint(0, n_obs - block_size + 1, n_blocks)
            sim_returns_list = []
            for start in block_starts:
                end = min(start + block_size, n_obs)
                sim_returns_list.append(base_returns.iloc[start:end].values)
            sim_returns = np.concatenate(sim_returns_list)[:n_obs]
            sim_returns = pd.Series(sim_returns, index=base_returns.index)
        else:
            # Simple i.i.d. bootstrap
            sim_returns = base_returns.sample(n=n_obs, replace=True).values
            sim_returns = pd.Series(sim_returns, index=base_returns.index)

        # Build equity curve
        equity = (1 + sim_returns).cumprod()

        # Calculate metrics
        total_ret = equity.iloc[-1] - 1
        ann_ret = (1 + total_ret) ** (ann_factor / n_obs) - 1
        ann_vol = sim_returns.std() * np.sqrt(ann_factor)

        excess = sim_returns - 0.02 / ann_factor
        if excess.std() > 0:
            sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
            downside = excess[excess < 0]
            if downside.std() > 0:
                sortino = excess.mean() / downside.std() * np.sqrt(ann_factor)
            else:
                sortino = np.inf
        else:
            sharpe = 0.0
            sortino = 0.0

        # Drawdown
        cummax = equity.cummax()
        dd = (equity - cummax) / cummax
        max_dd = dd.min()
        calmar = abs(ann_ret / max_dd) if max_dd < 0 else np.inf

        simulated_metrics["total_return"].append(float(total_ret))
        simulated_metrics["annualized_return"].append(float(ann_ret))
        simulated_metrics["annualized_volatility"].append(float(ann_vol))
        simulated_metrics["sharpe_ratio"].append(float(sharpe) if not np.isinf(sharpe) else 0.0)
        simulated_metrics["sortino_ratio"].append(float(sortino) if not np.isinf(sortino) else 0.0)
        simulated_metrics["max_drawdown"].append(float(max_dd))
        simulated_metrics["calmar_ratio"].append(float(calmar) if not np.isinf(calmar) else 0.0)

        simulated_equity_curves.append(equity)

    # Compute confidence intervals
    confidence_intervals = {}
    for metric, values in simulated_metrics.items():
        values_arr = np.array(values)
        confidence_intervals[metric] = {}
        for level in confidence_levels:
            alpha = (1 - level) / 2
            lower = np.percentile(values_arr, alpha * 100)
            upper = np.percentile(values_arr, (1 - alpha) * 100)
            confidence_intervals[metric][level] = (float(lower), float(upper))

    # Probability of ruin (equity falls below 50% of initial)
    ruin_threshold = 0.5
    ruin_count = sum(1 for eq in simulated_equity_curves if eq.min() < ruin_threshold)
    prob_ruin = ruin_count / n_simulations

    # Summary statistics
    summary = {}
    for metric, values in simulated_metrics.items():
        values_arr = np.array(values)
        summary[metric] = {
            "mean": float(values_arr.mean()),
            "std": float(values_arr.std()),
            "median": float(np.median(values_arr)),
            "min": float(values_arr.min()),
            "max": float(values_arr.max()),
        }

    return {
        "simulated_equity_curves": simulated_equity_curves,
        "metric_distributions": {k: np.array(v) for k, v in simulated_metrics.items()},
        "confidence_intervals": confidence_intervals,
        "probability_of_ruin": prob_ruin,
        "ruin_threshold": ruin_threshold,
        "summary": summary,
        "n_simulations": n_simulations,
        "base_observations": n_obs,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.strategy_builder import build_strategy

    # Generate sample data
    np.random.seed(42)
    dates = pd.date_range("2018-01-01", periods=756, freq="B")
    returns = np.random.normal(0.0005, 0.015, 756)
    prices = 100 * np.exp(np.cumsum(returns))

    sample_data = pd.DataFrame({
        "open": prices * np.random.uniform(0.995, 1.005, 756),
        "high": prices * np.random.uniform(1.005, 1.02, 756),
        "low": prices * np.random.uniform(0.98, 0.995, 756),
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, 756),
    }, index=dates)

    # Run walk-forward analysis
    print("Running walk-forward analysis...")
    results = walk_forward_analysis(
        data=sample_data,
        strategy_factory=lambda params: build_strategy("sma_crossover", json.dumps(params)),
        param_grid={"fast_period": [10, 20, 50], "slow_period": [50, 100, 200]},
        train_months=12,
        test_months=3,
        step_months=3,
    )

    print(f"Number of walk-forward periods: {results['summary']['n_periods']}")
    print(f"Total OOS Return: {results['summary']['total_oos_return']:.2%}")
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")

    # Check for overfitting
    diagnostics = overfitting_check(results)
    print(f"Overfitting Risk: {diagnostics['overfitting_risk']}")
