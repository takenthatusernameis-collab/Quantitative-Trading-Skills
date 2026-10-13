#!/usr/bin/env python3
"""
Walk-forward analysis and parameter optimization.

Splits historical data into rolling training and testing windows to validate
strategy robustness across market regimes.
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional, Union
from itertools import product

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.strategy_builder import build_strategy
from scripts.data_loader import load_data, validate_data
from scripts.performance import calculate_metrics, generate_report
from scripts.reporting import generate_tear_sheet


def _dict_to_multiindex(data_dict: dict) -> pd.DataFrame:
    """Convert dict panel data (symbol -> OHLCV DataFrame) to a
    MultiIndex (field, symbol) DataFrame aligned on the common date index.

    Strategies and return calculators produce identical results for the
    dict and MultiIndex formats, so walk-forward/CPCV code paths can
    operate on a single DataFrame representation.
    """
    common_index = None
    columns = None
    for df in data_dict.values():
        if common_index is None:
            common_index = df.index
            columns = set(df.columns)
        else:
            common_index = common_index.intersection(df.index)
            columns &= set(df.columns)
    if common_index is None or len(common_index) == 0:
        raise ValueError("No common index found")

    common_index = common_index.sort_values()
    fields = sorted(columns)
    symbols = list(data_dict.keys())
    panel = pd.DataFrame(
        index=common_index,
        columns=pd.MultiIndex.from_product([fields, symbols]),
        dtype=float,
    )
    for symbol, df in data_dict.items():
        aligned = df.reindex(common_index)
        for field in fields:
            panel[(field, symbol)] = aligned[field].to_numpy()
    return panel


def walk_forward_analysis(
    data: Union[pd.DataFrame, dict],
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
    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
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
    data: Union[pd.DataFrame, dict],
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
    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
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
    # NaN != 0 evaluates to True in pandas, so we must explicitly exclude NaN
    return bool((signals.notna() & (signals != 0)).any())


def _calculate_strategy_returns(
    data: Union[pd.DataFrame, dict],
    signals: pd.Series,
    commission: float,
    slippage: float,
) -> pd.Series:
    """Calculate strategy returns from signals and market data."""
    if isinstance(data, dict):
        # For dict of dataframes, compute equal-weighted portfolio returns
        # Use first key's index as reference
        common_index = None
        for df in data.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)
        common_index = common_index.sort_values()
        rets = []
        for df in data.values():
            rets.append(df.reindex(common_index)["close"].pct_change())
        raw_returns = pd.concat(rets, axis=1).mean(axis=1)
    elif isinstance(data.columns, pd.MultiIndex):
        # For panel data, compute equal-weighted portfolio returns
        close = data["close"]
        raw_returns = close.pct_change().mean(axis=1)
    else:
        close = data["close"]
        raw_returns = close.pct_change()

    positions = signals.shift(1)  # Trade at next period's open

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
        # Implementation: for each position, with prob 1/block_size start new block
        # at random index; otherwise continue sequentially (circular wrap)
        pass

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
            if block_size >= n_obs:
                # Block larger than series - fall back to i.i.d. bootstrap
                sim_returns = base_returns.sample(n=n_obs, replace=True).values
                sim_returns = pd.Series(sim_returns, index=base_returns.index)
            else:
                # Stationary block bootstrap (Politis & Romano, 1994)
                # Blocks have geometrically distributed lengths with mean = block_size
                # Circular wrap-around ensures stationarity
                p_new_block = 1.0 / block_size
                sim_returns = np.empty(n_obs)
                returns_array = base_returns.values

                # Random starting position
                pos = np.random.randint(0, n_obs)

                for i in range(n_obs):
                    sim_returns[i] = returns_array[pos]
                    # Decide whether to start a new block
                    if np.random.random() < p_new_block:
                        pos = np.random.randint(0, n_obs)
                    else:
                        pos = (pos + 1) % n_obs  # Continue sequentially with wrap

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


def cpcv_analysis(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    n_splits: int = 10,
    test_size: float = 0.1,
    purge_size: float = 0.0,
    embargo_size: float = 0.0,
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
) -> Dict[str, Any]:
    """
    Perform Combinatorially Purged Cross-Validation (CPCV).

    CPCV addresses look-ahead bias and multiple-testing issues by:
    1. Splitting data into n_splits sequential groups
    2. For each fold, using n_splits-1 groups for training, 1 group for testing
    3. Purging (removing) observations around test set from training to prevent
       look-ahead bias (e.g., due to overlapping rolling windows)
    4. Adding embargo period after test set to prevent contamination

    Args:
        data: DataFrame with OHLCV data indexed by date
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        n_splits: Number of sequential groups to split data into
        test_size: Fraction of each group to use as test set (within the group)
        purge_size: Fraction of observations to purge from training around test
        embargo_size: Fraction of observations to embargo after test set
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade

    Returns:
        Dictionary with CPCV results including:
            - 'folds': list of fold results
            - 'best_params_per_fold': list of optimal params per fold
            - 'oos_returns': out-of-sample returns across all folds
            - 'summary': aggregate metrics
            - 'param_stability': parameter stability across folds
    """
    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must be indexed by DatetimeIndex")
        data = data.sort_index()
    n_obs = len(data)

    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")

    # Split indices into n_splits sequential groups
    group_size = n_obs // n_splits
    group_indices = []
    for i in range(n_splits):
        start = i * group_size
        end = (i + 1) * group_size if i < n_splits - 1 else n_obs
        group_indices.append((start, end))

    # For each group, create a test set (fraction test_size of the group)
    # and training set (all other groups, purged)
    folds = []
    purge_n = int(purge_size * group_size)
    embargo_n = int(embargo_size * group_size)

    for test_group_idx in range(n_splits):
        test_start, test_end = group_indices[test_group_idx]
        # Use a fraction of the group as test set
        test_n = int((test_end - test_start) * test_size)
        test_start_idx = test_start
        test_end_idx = test_start + test_n

        if test_end_idx <= test_start_idx:
            continue

        test_indices = list(range(test_start_idx, test_end_idx))

        # Training indices: all other groups, with purge/embargo
        train_indices = []
        for train_group_idx in range(n_splits):
            if train_group_idx == test_group_idx:
                continue
            tr_start, tr_end = group_indices[train_group_idx]

            # Apply purge: remove observations near test set
            # For groups before test group, purge the end
            # For groups after test group, purge the start
            if train_group_idx < test_group_idx:
                purged_end = min(tr_end, test_start_idx - purge_n)
                if purged_end > tr_start:
                    train_indices.extend(range(tr_start, purged_end))
            else:  # train_group_idx > test_group_idx
                purged_start = max(tr_start, test_end_idx + embargo_n)
                if purged_start < tr_end:
                    train_indices.extend(range(purged_start, tr_end))

        if len(train_indices) == 0 or len(test_indices) == 0:
            continue

        train_data = data.iloc[train_indices]
        test_data = data.iloc[test_indices]

        folds.append({
            "fold": len(folds),
            "test_group": test_group_idx,
            "train_start": train_data.index[0],
            "train_end": train_data.index[-1],
            "test_start": test_data.index[0],
            "test_end": test_data.index[-1],
            "train_data": train_data,
            "test_data": test_data,
            "train_indices": train_indices,
            "test_indices": test_indices,
        })

    # Grid search for best params on each training fold
    best_params_per_fold = []
    oos_returns_list = []

    for fold in folds:
        train_data = fold["train_data"]
        test_data = fold["test_data"]

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

        best_params_per_fold.append(best_params)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            fold["best_params"] = best_params
            fold["best_sharpe"] = best_sharpe
            fold["test_returns"] = best_test_returns
        else:
            fold["best_params"] = None
            fold["best_sharpe"] = None
            fold["test_returns"] = pd.Series(dtype=float)

    # Combine all out-of-sample returns
    if oos_returns_list:
        oos_returns = pd.concat(oos_returns_list)
    else:
        oos_returns = pd.Series(dtype=float)

    # Parameter stability analysis
    valid_params = [p for p in best_params_per_fold if p is not None]
    param_stability = {}
    if valid_params:
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

    # Summary metrics
    summary = _calculate_cpcv_summary(oos_returns, folds, param_stability)

    return {
        "folds": folds,
        "best_params_per_fold": best_params_per_fold,
        "oos_returns": oos_returns,
        "summary": summary,
        "param_stability": param_stability,
    }


def _calculate_cpcv_summary(
    oos_returns: pd.Series,
    folds: List[Dict[str, Any]],
    param_stability: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate summary metrics for CPCV results."""
    summary = {
        "n_folds": len(folds),
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

        summary["avg_fold_return"] = float(oos_returns.mean())
        summary["n_positive_folds"] = int((oos_returns > 0).sum())
        summary["win_rate_folds"] = float((oos_returns > 0).sum() / len(oos_returns)) if len(oos_returns) > 0 else 0.0

    # Average parameter stability
    if param_stability:
        stability_ratios = [v["stability_ratio"] for v in param_stability.values()]
        summary["avg_param_stability"] = float(np.mean(stability_ratios))
        if summary["avg_param_stability"] >= 0.5:
            summary["overfitting_risk"] = "low"
        elif summary["avg_param_stability"] >= 0.3:
            summary["overfitting_risk"] = "medium"
        else:
            summary["overfitting_risk"] = "high"
    else:
        summary["avg_param_stability"] = 0.0
        summary["overfitting_risk"] = "high"

    return summary


def run_cpcv(args) -> int:
    """Run CPCV analysis from CLI args."""
    print(f"Loading data from {args.data}...")
    data = _load_and_validate_data(args.data, args.symbol, args.start, args.end)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running CPCV analysis with {args.strategy} (n_splits={args.n_splits})...")
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=args.n_splits,
        test_size=args.test_size,
        purge_size=args.purge_size,
        embargo_size=args.embargo_size,
        commission=args.commission,
        slippage=args.slippage,
    )

    print(f"Number of CPCV folds: {results['summary']['n_folds']}")
    print(f"Total OOS Return: {results['summary']['total_oos_return']:.2%}")
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    print(f"Avg Parameter Stability: {results['summary'].get('avg_param_stability', 'N/A'):.2f}")
    print(f"Overfitting Risk: {results['summary'].get('overfitting_risk', 'N/A')}")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "cpcv_summary.json"
    summary_data = {
        "summary": results["summary"],
        "param_stability": results["param_stability"],
        "best_params_per_fold": results["best_params_per_fold"],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "n_splits": args.n_splits,
            "test_size": args.test_size,
            "purge_size": args.purge_size,
            "embargo_size": args.embargo_size,
            "commission": args.commission,
            "slippage": args.slippage,
            "param_grid": param_grid,
        },
    }
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"CPCV summary saved to: {summary_path}")

    # Generate full report if OOS returns available
    if len(results["oos_returns"]) > 0:
        equity = (1 + results["oos_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["oos_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
            },
        }
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_cpcv")
        generate_tear_sheet(report_results, metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_cpcv")
        print(f"Detailed report saved to: {args.output}/")

    return 0


def _make_strategy_factory(strategy_type: str):
    """Create a strategy factory function for the given strategy type."""
    def factory(params: Dict[str, Any]):
        return build_strategy(strategy_type, json.dumps(params))
    return factory


def _load_and_validate_data(data_path: str, symbol: str, start: str, end: str) -> pd.DataFrame:
    """Load and validate data from file."""
    data = load_data(data_path, symbol=symbol, start=start, end=end)
    if not validate_data(data):
        raise ValueError("Data validation failed!")
    return data


def _parse_param_grid(param_grid_str: str) -> Dict[str, List[Any]]:
    """Parse parameter grid from JSON string."""
    try:
        param_grid = json.loads(param_grid_str)
        # Ensure all values are lists
        for k, v in param_grid.items():
            if not isinstance(v, list):
                param_grid[k] = [v]
        return param_grid
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON for param_grid: {e}")


def run_walk_forward(args) -> int:
    """Run walk-forward analysis from CLI args."""
    print(f"Loading data from {args.data}...")
    data = _load_and_validate_data(args.data, args.symbol, args.start, args.end)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running walk-forward analysis with {args.strategy}...")
    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        commission=args.commission,
        slippage=args.slippage,
    )

    print(f"Number of walk-forward periods: {results['summary']['n_periods']}")
    print(f"Total OOS Return: {results['summary']['total_oos_return']:.2%}")
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")

    # Check for overfitting
    diagnostics = overfitting_check(results)
    print(f"Overfitting Risk: {diagnostics['overfitting_risk']}")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "walk_forward_summary.json"
    summary_data = {
        "summary": results["summary"],
        "diagnostics": diagnostics,
        "best_params_per_period": results["best_params_per_period"],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "train_months": args.train_months,
            "test_months": args.test_months,
            "step_months": args.step_months,
            "commission": args.commission,
            "slippage": args.slippage,
            "param_grid": param_grid,
        },
    }
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"Walk-forward summary saved to: {summary_path}")

    # Generate full report if OOS returns available
    if len(results["oos_returns"]) > 0:
        equity = (1 + results["oos_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["oos_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
            },
        }
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_walk_forward")
        generate_tear_sheet(report_results, metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_walk_forward")
        print(f"Detailed report saved to: {args.output}/")

    return 0


def run_parameter_optimization(args) -> int:
    """Run parameter optimization from CLI args."""
    print(f"Loading data from {args.data}...")
    data = _load_and_validate_data(args.data, args.symbol, args.start, args.end)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running parameter optimization with {args.strategy}...")
    results = parameter_optimization(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        commission=args.commission,
        slippage=args.slippage,
    )

    if not results:
        print("No valid parameter combinations found!")
        return 1

    print(f"\nTop {min(args.top_n, len(results))} parameter combinations:")
    print("-" * 80)
    print(f"{'Rank':<5} {'Sharpe':<10} {'Total Return':<15} {'Params'}")
    print("-" * 80)
    for i, r in enumerate(results[:args.top_n]):
        print(f"{i+1:<5} {r['sharpe_ratio']:<10.4f} {r['total_return']:<15.2%} {r['params']}")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results_path = output_dir / "parameter_optimization.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {results_path}")

    return 0


def run_monte_carlo(args) -> int:
    """Run Monte Carlo simulation from CLI args."""
    print(f"Loading data from {args.data}...")
    data = _load_and_validate_data(args.data, args.symbol, args.start, args.end)

    # First run a backtest to get base returns
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    # Use best params from optimization or first combo
    if param_grid:
        # Try to get best params from optimization
        opt_results = parameter_optimization(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            commission=args.commission,
            slippage=args.slippage,
        )
        if opt_results:
            best_params = opt_results[0]["params"]
            print(f"Using best params from optimization: {best_params}")
        else:
            # Use first combo
            param_names = list(param_grid.keys())
            param_values = list(param_grid.values())
            from itertools import product
            first_combo = next(product(*param_values))
            best_params = dict(zip(param_names, first_combo))
            print(f"Using first param combo: {best_params}")
    else:
        best_params = {}

    strategy = strategy_factory(best_params)
    signals = strategy.generate_signals(data)
    returns = _calculate_strategy_returns(data, signals, args.commission, args.slippage)

    print(f"Running Monte Carlo simulation with {args.n_simulations} simulations...")
    mc_results = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=args.n_simulations,
        confidence_levels=args.confidence_levels,
        block_size=args.block_size,
    )

    print(f"Probability of Ruin (>50% drawdown): {mc_results['probability_of_ruin']:.2%}")

    # Print confidence intervals for key metrics
    print("\nKey Metric Confidence Intervals (95%):")
    print("-" * 60)
    for metric in ["sharpe_ratio", "total_return", "max_drawdown", "annualized_return"]:
        if metric in mc_results["confidence_intervals"]:
            ci = mc_results["confidence_intervals"][metric].get(0.95)
            if ci:
                mean_val = mc_results["summary"][metric]["mean"]
                print(f"  {metric}: {mean_val:.4f} [{ci[0]:.4f}, {ci[1]:.4f}]")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    mc_path = output_dir / "monte_carlo_results.json"
    # Convert numpy arrays to lists for JSON serialization
    mc_save = {
        "metric_distributions": {k: v.tolist() for k, v in mc_results["metric_distributions"].items()},
        "confidence_intervals": mc_results["confidence_intervals"],
        "probability_of_ruin": mc_results["probability_of_ruin"],
        "ruin_threshold": mc_results["ruin_threshold"],
        "summary": mc_results["summary"],
        "n_simulations": mc_results["n_simulations"],
        "base_observations": mc_results["base_observations"],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "params": best_params,
            "commission": args.commission,
            "slippage": args.slippage,
            "n_simulations": args.n_simulations,
            "block_size": args.block_size,
        },
    }
    with open(mc_path, "w") as f:
        json.dump(mc_save, f, indent=2, default=str)
    print(f"\nMonte Carlo results saved to: {mc_path}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Walk-forward analysis and validation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    common_parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    common_parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to analyze")
    common_parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    common_parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    common_parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    common_parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    common_parser.add_argument("--output", type=str, default="results", help="Output directory")
    common_parser.add_argument("--param-grid", type=str, required=True, help="Parameter grid as JSON string")

    # Walk-forward analysis
    wf_parser = subparsers.add_parser("walk-forward", parents=[common_parser], help="Run walk-forward analysis")
    wf_parser.add_argument("--train-months", type=int, default=12, help="Training window size in months")
    wf_parser.add_argument("--test-months", type=int, default=3, help="Testing window size in months")
    wf_parser.add_argument("--step-months", type=int, default=3, help="Step size between iterations in months")
    wf_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    wf_parser.set_defaults(func=run_walk_forward)

    # Parameter optimization
    opt_parser = subparsers.add_parser("optimize", parents=[common_parser], help="Run parameter optimization")
    opt_parser.add_argument("--top-n", type=int, default=10, help="Number of top results to display")
    opt_parser.set_defaults(func=run_parameter_optimization)

    # Monte Carlo simulation
    mc_parser = subparsers.add_parser("monte-carlo", parents=[common_parser], help="Run Monte Carlo simulation")
    mc_parser.add_argument("--n-simulations", type=int, default=2000, help="Number of simulations")
    mc_parser.add_argument("--confidence-levels", type=float, nargs="+", default=[0.90, 0.95, 0.99], help="Confidence levels")
    mc_parser.add_argument("--block-size", type=int, help="Block size for block bootstrap")
    mc_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    mc_parser.set_defaults(func=run_monte_carlo)

    # CPCV analysis
    cpcv_parser = subparsers.add_parser("cpcv", parents=[common_parser], help="Run Combinatorially Purged Cross-Validation")
    cpcv_parser.add_argument("--n-splits", type=int, default=10, help="Number of sequential groups (folds)")
    cpcv_parser.add_argument("--test-size", type=float, default=0.1, help="Fraction of each group to use as test set")
    cpcv_parser.add_argument("--purge-size", type=float, default=0.0, help="Fraction of observations to purge from training around test set")
    cpcv_parser.add_argument("--embargo-size", type=float, default=0.0, help="Fraction of observations to embargo after test set")
    cpcv_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    cpcv_parser.set_defaults(func=run_cpcv)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
