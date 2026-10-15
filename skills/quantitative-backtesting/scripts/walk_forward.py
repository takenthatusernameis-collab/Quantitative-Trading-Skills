#!/usr/bin/env python3
"""
Walk-forward analysis and parameter optimization.

Splits historical data into rolling training and testing windows to validate
strategy robustness across market regimes. Monte Carlo simulation lives in
the standalone `monte_carlo.py` module and is re-exported here for backward
compatibility.
"""

import argparse
import json
import math
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional, Union
from itertools import product

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.strategy_builder import build_strategy
from scripts.data_loader import load_data, validate_data, validate_point_in_time, _compute_benchmark_total_return, adjust_for_splits
from scripts.performance import calculate_metrics, generate_report, _annualization_factor, _benchmark_stats
from scripts.reporting import generate_tear_sheet
from monte_carlo import monte_carlo_simulation


def _split_train_val_test(
    data: Union[pd.DataFrame, dict],
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    test_frac: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split data chronologically into train/validation/test sets.

    Args:
        data: DataFrame with OHLCV data indexed by date (or dict panel)
        train_frac: Fraction of data for training (default 0.6)
        val_frac: Fraction of data for validation (default 0.2)
        test_frac: Fraction of data for testing (default 0.2)

    Returns:
        Tuple of (train_data, val_data, test_data) DataFrames

    Raises:
        ValueError: If fractions don't sum to ~1.0 or data is empty
    """
    if isinstance(data, dict):
        data = _dict_to_multiindex(data)

    if not isinstance(data.index, pd.DatetimeIndex):
        try:
            data.index = pd.DatetimeIndex(data.index)
        except Exception:
            pass
    data = data.sort_index()

    n = len(data)
    if n == 0:
        raise ValueError("Data is empty")

    total_frac = train_frac + val_frac + test_frac
    if abs(total_frac - 1.0) > 1e-9:
        raise ValueError(f"Fractions must sum to 1.0, got {total_frac}")

    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)

    # Ensure each split has at least some data
    if train_end == 0 or val_end == train_end or val_end >= n:
        raise ValueError("Data too small for requested split fractions")

    train_data = data.iloc[:train_end]
    val_data = data.iloc[train_end:val_end]
    test_data = data.iloc[val_end:]

    # Enforce strict chronological separation between the three splits.
    # A leak (a validation or test bar appearing in the training set, or
    # a test bar appearing in the validation set) would silently invalidate
    # the "held-out test set has never been used in any selection step"
    # guarantee, so the check is an executable invariant rather than a
    # documentation note. The check is also exposed as a standalone
    # helper (`_verify_split_separation`) so it can be reused and tested
    # independently of the full out-of-sample pipeline.
    _verify_split_separation(train_data, val_data, test_data)

    return train_data, val_data, test_data


def _verify_split_separation(
    train_data: pd.DataFrame,
    val_data: pd.DataFrame,
    test_data: pd.DataFrame,
    strict: bool = True,
) -> Dict[str, Any]:
    """Verify that train/validation/test splits are pairwise disjoint and
    chronologically ordered.

    This encodes the critical invariant that the held-out test set has
    never been used in any parameter selection or confirmation step.
    Without this check, a slicing bug (e.g. an inclusive ``<=`` boundary
    or an overlapping window) would silently leak future information
    into the training/selection phase, producing an in-sample-optimistic
    result that is indistinguishable from a genuine out-of-sample one.

    Args:
        train_data: Training split (earliest).
        val_data: Validation split (middle).
        test_data: Test split (latest, held out).
        strict: If True, raise ValueError on any violation. If False,
            return the check result without raising (useful for diagnostics).

    Returns:
        Dict with keys:
            - 'disjoint': bool, True when all three index sets are pairwise disjoint
            - 'chronological': bool, True when train_end < val_start and val_end < test_start
            - 'train_val_overlap': int, number of timestamps shared by train and val
            - 'val_test_overlap': int, number of timestamps shared by val and test
            - 'train_test_overlap': int, number of timestamps shared by train and test
            - 'train_end': last train timestamp (or None)
            - 'val_start': first validation timestamp (or None)
            - 'val_end': last validation timestamp (or None)
            - 'test_start': first test timestamp (or None)
            - 'train_size'/'val_size'/'test_size': bar counts

    Raises:
        ValueError: When strict=True and any overlap or chronological
            violation is detected.
    """
    result: Dict[str, Any] = {
        "disjoint": True,
        "chronological": True,
        "train_val_overlap": 0,
        "val_test_overlap": 0,
        "train_test_overlap": 0,
        "train_end": None,
        "val_start": None,
        "val_end": None,
        "test_start": None,
        "train_size": int(len(train_data)),
        "val_size": int(len(val_data)),
        "test_size": int(len(test_data)),
    }

    # Empty splits are not a separation *violation* per se (they are a
    # data-availability problem caught by the caller), but they make the
    # overlap arithmetic trivial and must not be treated as "disjoint".
    if len(train_data) == 0 or len(val_data) == 0 or len(test_data) == 0:
        result["disjoint"] = False
        result["chronological"] = False
        if strict:
            raise ValueError(
                "Split contains an empty segment: "
                f"train={len(train_data)}, val={len(val_data)}, test={len(test_data)}"
            )
        return result

    train_idx = set(train_data.index)
    val_idx = set(val_data.index)
    test_idx = set(test_data.index)

    tv_overlap = len(train_idx & val_idx)
    vt_overlap = len(val_idx & test_idx)
    tt_overlap = len(train_idx & test_idx)

    result["train_val_overlap"] = tv_overlap
    result["val_test_overlap"] = vt_overlap
    result["train_test_overlap"] = tt_overlap
    result["disjoint"] = (tv_overlap == 0 and vt_overlap == 0 and tt_overlap == 0)

    train_end_ts = train_data.index[-1]
    val_start_ts = val_data.index[0]
    val_end_ts = val_data.index[-1]
    test_start_ts = test_data.index[0]

    result["train_end"] = str(train_end_ts)
    result["val_start"] = str(val_start_ts)
    result["val_end"] = str(val_end_ts)
    result["test_start"] = str(test_start_ts)

    # Chronological ordering: the last training bar must precede the first
    # validation bar, and the last validation bar must precede the first
    # test bar. Using ``<=`` (rather than ``<``) would allow adjacent
    # splits to share a boundary timestamp, which is a leak.
    chronological = (train_end_ts < val_start_ts) and (val_end_ts < test_start_ts)
    result["chronological"] = bool(chronological)

    if strict and (not result["disjoint"] or not result["chronological"]):
        reasons = []
        if tv_overlap:
            reasons.append(f"train/validation share {tv_overlap} timestamp(s)")
        if vt_overlap:
            reasons.append(f"validation/test share {vt_overlap} timestamp(s)")
        if tt_overlap:
            reasons.append(f"train/test share {tt_overlap} timestamp(s)")
        if not chronological:
            reasons.append(
                f"chronological order violated: train_end={train_end_ts}, "
                f"val_start={val_start_ts}, val_end={val_end_ts}, "
                f"test_start={test_start_ts}"
            )
        raise ValueError(
            "Train/validation/test split is not strictly separated: "
            + "; ".join(reasons)
        )

    return result


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
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    **kwargs,
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
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (multiple-testing correction) for each period's in-sample
            parameter selection, plus an aggregate correction on the
            combined out-of-sample returns with n_trials equal to the
            total number of configurations evaluated across all periods.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)

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
    total_evaluated_trials = 0
    all_trial_sharpes: List[float] = []
    period_benchmark_stats = []

    for period in periods:
        train_data = period["train_data"]
        test_data = period["test_data"]

        best_sharpe = -np.inf
        best_params = None
        best_test_returns = None
        period_trial_sharpes: List[float] = []
        best_train_returns = None

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
                    test_data, test_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost
                )

                # Evaluate on training set
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost
                )

                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                else:
                    sharpe = -np.inf

                if apply_deflation and np.isfinite(sharpe):
                    period_trial_sharpes.append(float(sharpe))

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_test_returns = test_returns
                    if apply_deflation:
                        best_train_returns = train_returns

            except Exception:
                continue

        best_params_per_period.append(best_params)
        all_trial_sharpes.extend(period_trial_sharpes)
        total_evaluated_trials += len(period_trial_sharpes)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            period["best_params"] = best_params
            period["best_sharpe"] = best_sharpe
            period["test_returns"] = best_test_returns
            # Compute benchmark stats for this period
            if benchmark is not None:
                if isinstance(benchmark, list) and len(benchmark) > 1:
                    # Multiple benchmarks: surface a per-period Deflated Alpha
                    # correction (multiple-testing control across the benchmark
                    # set).  Uses the shared helper so the correction is applied
                    # identically to the aggregate path.
                    correction = _benchmark_list_alpha_correction(
                        best_test_returns, benchmark,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                    period["benchmark_stats"] = correction["per_benchmark"]
                    period["deflated_alpha"] = correction["deflated_alpha"]
                    period_benchmark_stats.append(correction["per_benchmark"])
                else:
                    # Single benchmark (DataFrame or single-element list):
                    # backward-compatible path (no cross-benchmark deflation).
                    bench = benchmark[0] if isinstance(benchmark, list) else benchmark
                    benchmark_returns = _compute_benchmark_returns(bench, best_test_returns, total_return_benchmark)
                    if benchmark_returns is not None:
                        period_ann_factor = _annualization_factor(best_test_returns.index)
                        bench_stats = _benchmark_stats(
                            best_test_returns, benchmark_returns, period_ann_factor,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        period_benchmark_stats.append(bench_stats)
                    else:
                        period_benchmark_stats.append(None)
            else:
                period_benchmark_stats.append(None)
            if apply_deflation and best_train_returns is not None and period_trial_sharpes:
                # Deflate the in-sample selection Sharpe by the number of
                # configurations compared in this period's grid search.
                period["deflated_sharpe"] = deflated_sharpe_ratio(
                    sharpe_ratio=best_sharpe,
                    returns=best_train_returns,
                    n_trials=len(period_trial_sharpes),
                    trial_sharpes=period_trial_sharpes,
                )
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

    # Benchmark comparison on combined OOS returns
    if benchmark is not None and len(oos_returns) > 0:
        if isinstance(benchmark, list) and len(benchmark) > 1:
            # Multiple benchmarks: surface a cross-benchmark Deflated Alpha
            # correction on the aggregate out-of-sample record, mirroring the
            # calculate_metrics / benchmark_list path.
            correction = _benchmark_list_alpha_correction(
                oos_returns, benchmark,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=benchmark_commission,
                benchmark_slippage=benchmark_slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
            summary["benchmark_metrics"] = correction["per_benchmark"]
            if correction["deflated_alpha"] is not None:
                summary["deflated_alpha"] = correction["deflated_alpha"]
        else:
            # Single benchmark (DataFrame or single-element list): backward compat
            bench = benchmark[0] if isinstance(benchmark, list) else benchmark
            benchmark_returns = _compute_benchmark_returns(bench, oos_returns, total_return_benchmark)
            if benchmark_returns is not None:
                summary = _add_benchmark_to_summary(
                    summary, oos_returns, benchmark_returns,
                    commission=benchmark_commission, slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )

    # Add per-period benchmark metrics to summary
    if period_benchmark_stats:
        summary['benchmark_metrics_per_period'] = period_benchmark_stats

    # Aggregate multiple-testing correction on the combined out-of-sample
    # returns. The conservative interpretation: the OOS record was produced
    # by a search that evaluated total_evaluated_trials configurations, so
    # the OOS Sharpe is deflated by all of them. Use the pooled cross-period
    # trial Sharpes for the cross-sectional SR* estimator (conservative:
    # between-period variation inflates the null Sharpe).
    #
    # The guard is `len(oos_returns) > 1` only: a constant OOS return series
    # (zero variance) is a degenerate case, not a reason to skip the
    # correction. `deflated_sharpe_ratio` handles it internally (it sets
    # `z = -inf` when `returns.std() == 0`), yielding the conservative
    # DSR = 0, p_value = 1, z_score = None. Skipping the key with an
    # `oos_returns.std() > 0` guard would be inconsistent with `run_backtest`
    # and the `monte-carlo` subcommand, which both emit the degenerate dict
    # when `n_trials` is provided.
    if apply_deflation and len(oos_returns) > 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=summary.get("oos_sharpe", 0.0),
            returns=oos_returns,
            n_trials=max(total_evaluated_trials, 1),
            trial_sharpes=all_trial_sharpes if all_trial_sharpes else None,
        )

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
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    n_splits: int = 5,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    **kwargs,
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
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        n_splits: Number of train/test splits
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (Bailey & Lopez de Prado, 2014) for every combination,
            correcting each Sharpe ratio for the number of trials in
            the grid. Adds a 'deflated_sharpe' dict to each result
            with keys 'deflated_sharpe_ratio', 'p_value',
            'expected_max_sharpe', 'n_trials', etc.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)

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

    # Pre-compute benchmark returns if benchmark provided
    benchmark_returns = None
    if benchmark is not None:
        if total_return_benchmark:
            benchmark_returns = _compute_benchmark_total_return(benchmark)
        else:
            benchmark_returns = benchmark["close"].pct_change()

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
                data, signals, commission, slippage,
                impact_coefficient, adv_window, borrow_cost, funding_cost
            )

            if len(returns) > 1:
                ann_factor = _annualization_factor(returns.index)
                excess = returns - 0.02 / ann_factor
                sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor) if returns.std() > 0 else 0
                total_return = (1 + returns).prod() - 1

                result = {
                    "params": params,
                    "sharpe_ratio": float(sharpe),
                    "total_return": float(total_return),
                    "n_periods": len(returns),
                }

                # Add benchmark comparison metrics if benchmark provided
                if benchmark_returns is not None and len(benchmark_returns) > 0:
                    bench_stats = _benchmark_stats(
                        returns, benchmark_returns, ann_factor,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                    result.update(bench_stats)

                results.append(result)
                if apply_deflation:
                    # Transient key: the return series is consumed by
                    # the deflation step below and never returned.
                    results[-1]["_returns"] = returns
        except Exception:
            continue

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    # Multiple-testing correction: deflate every combination's Sharpe
    # by the number of ranked trials, using the cross-sectional
    # dispersion of the trial Sharpes to estimate the Sharpe
    # attainable from luck.
    if apply_deflation and results:
        n_trials = len(results)
        trial_sharpes = [r["sharpe_ratio"] for r in results]
        for result in results:
            result["deflated_sharpe"] = deflated_sharpe_ratio(
                sharpe_ratio=result["sharpe_ratio"],
                returns=result.pop("_returns"),
                n_trials=n_trials,
                trial_sharpes=trial_sharpes,
            )

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

    # Surface the aggregate Deflated Sharpe Ratio when the
    # walk-forward run computed one (apply_deflation=True).
    wf_summary = wf_results.get("summary", {})
    if isinstance(wf_summary, dict) and "deflated_sharpe" in wf_summary:
        diagnostics["deflated_sharpe"] = wf_summary["deflated_sharpe"]

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


def deflated_sharpe_ratio(
    sharpe_ratio: float,
    returns: pd.Series,
    n_trials: int,
    trial_sharpes: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Compute the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Searching over a grid of parameter combinations is a multiple-testing
    problem: with enough configurations, luck alone produces an attractive
    in-sample Sharpe ratio. The Deflated Sharpe Ratio (DSR) corrects the
    estimated Sharpe for this selection bias and for the non-normality
    (skewness, kurtosis) of the return distribution.

    Formula (all Sharpe quantities in per-period, non-annualized units):

        DSR = Phi( (SR_hat - SR*) * sqrt(T - 1)
                    / sqrt(1 - gamma3 * SR_hat + ((gamma4 - 1) / 4) * SR_hat^2) )

    where SR_hat is the per-period estimated Sharpe, T the number of return
    observations, gamma3 the return skewness, gamma4 the return kurtosis
    (not excess), Phi the standard normal CDF, and SR* the expected maximum
    Sharpe ratio under the null hypothesis of no skill.

    SR* is estimated from the cross-sectional dispersion of the trial Sharpe
    ratios when `trial_sharpes` is provided (SR* = std(SR_trials) *
    sqrt(2 * ln(N))), and otherwise from the i.i.d.-normal null approximation
    (SR* = sqrt(2 * ln(N) / T)). Both estimators are conservative: they
    slightly overstate the Sharpe attainable from luck.

    Args:
        sharpe_ratio: Annualized Sharpe ratio of the strategy being evaluated.
        returns: Per-period return series behind `sharpe_ratio`.
        n_trials: Number of configurations tested (N).
        trial_sharpes: Optional list of the annualized Sharpe ratios of all
            trials. When provided (recommended), the cross-sectional
            dispersion of the trials estimates SR*; otherwise the i.i.d.-
            normal null approximation is used.

    Returns:
        Dictionary with:
            - 'deflated_sharpe_ratio': DSR in [0, 1]; the probability that
              the strategy's true Sharpe exceeds the best Sharpe expected
              from luck alone across the N trials
            - 'p_value': 1 - DSR
            - 'sharpe_ratio': input annualized Sharpe ratio
            - 'expected_max_sharpe': SR* in annualized units (the deflation
              benchmark)
            - 'z_score': standardized distance passed to Phi
            - 'n_trials': number of trials N
            - 'n_observations': T
            - 'skewness', 'kurtosis': return moments used in the correction
    """
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")

    returns = returns.dropna()
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations for Deflated Sharpe Ratio")

    ann_factor = _annualization_factor(returns.index)
    t_obs = len(returns)
    sr = float(sharpe_ratio) / np.sqrt(ann_factor)

    ln_trials = np.log(max(int(n_trials), 1))

    # Expected maximum Sharpe under the null (per-period units)
    sr_star = None
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        trial_sr = np.asarray([float(s) for s in trial_sharpes], dtype=float)
        trial_sr = trial_sr / np.sqrt(ann_factor)
        trial_std = float(np.std(trial_sr, ddof=1))
        if trial_std > 0 and np.isfinite(trial_std):
            sr_star = trial_std * np.sqrt(2.0 * ln_trials)
    if sr_star is None:
        sr_star = float(np.sqrt(2.0 * ln_trials / t_obs))

    # Variance of the Sharpe estimator under non-normality (skew/kurt are
    # invariant to constant shifts, so raw-return moments are valid for a
    # Sharpe computed on excess returns)
    skew = float(returns.skew())
    kurt = float(returns.kurtosis()) + 3.0  # pandas reports excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    denom = np.sqrt(variance_term)

    vol = float(returns.std())
    if vol > 0:
        z = (sr - sr_star) * np.sqrt(t_obs - 1) / denom
    else:
        # Degenerate (constant) returns carry no information about skill
        z = -np.inf

    dsr = 0.5 * (1.0 + math.erf(z / np.sqrt(2.0)))
    dsr = float(min(max(dsr, 0.0), 1.0))

    return {
        "deflated_sharpe_ratio": dsr,
        "p_value": 1.0 - dsr,
        "sharpe_ratio": float(sharpe_ratio),
        "expected_max_sharpe": float(sr_star * np.sqrt(ann_factor)),
        "z_score": float(z) if np.isfinite(z) else None,
        "n_trials": int(n_trials),
        "n_observations": int(t_obs),
        "skewness": float(skew),
        "kurtosis": float(kurt),
    }


def deflated_alpha_ratio(
    alpha: float,
    returns: pd.Series,
    benchmark_returns: pd.Series,
    n_benchmarks: int,
    trial_alphas: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Compute the Deflated Alpha Ratio (analogue to Deflated Sharpe Ratio).

    Testing multiple benchmarks is a multiple-testing problem: with enough
    benchmarks, luck alone produces an attractive alpha. The Deflated Alpha
    Ratio (DAR) corrects the estimated alpha for this selection bias and for
    the non-normality (skewness, kurtosis) of the return distribution.

    Formula (all alpha quantities in annualized units):

        DAR = Phi( (alpha_hat - alpha*) * sqrt(T - 1)
                    / sqrt(1 - gamma3 * alpha_hat + ((gamma4 - 1) / 4) * alpha_hat^2) )

    where alpha_hat is the estimated alpha, T the number of return
    observations, gamma3 the return skewness, gamma4 the return kurtosis
    (not excess), Phi the standard normal CDF, and alpha* the expected maximum
    alpha under the null hypothesis of no skill.

    alpha* is estimated from the cross-sectional dispersion of the trial alphas
    when `trial_alphas` is provided (alpha* = std(alpha_trials) *
    sqrt(2 * ln(N))), and otherwise from the i.i.d.-normal null approximation
    (alpha* = sqrt(2 * ln(N) / T) * sigma_benchmark), where sigma_benchmark
    is the volatility of the benchmark returns. Both estimators are conservative:
    they slightly overstate the alpha attainable from luck.

    Args:
        alpha: Annualized alpha of the strategy being evaluated.
        returns: Per-period return series of the strategy.
        benchmark_returns: Per-period return series of the benchmark.
        n_benchmarks: Number of benchmarks tested (N).
        trial_alphas: Optional list of the annualized alphas of all
            benchmarks tested. When provided (recommended), the cross-sectional
            dispersion of the alphas estimates alpha*; otherwise the i.i.d.-
            normal null approximation is used.

    Returns:
        Dictionary with:
            - 'deflated_alpha_ratio': DAR in [0, 1]; the probability that
              the strategy's true alpha exceeds the best alpha expected
              from luck alone across the N benchmarks
            - 'p_value': 1 - DAR
            - 'alpha': input annualized alpha
            - 'expected_max_alpha': alpha* in annualized units (the deflation
              benchmark)
            - 'z_score': standardized distance passed to Phi
            - 'n_benchmarks': number of benchmarks N
            - 'n_observations': T
            - 'skewness', 'kurtosis': return moments used in the correction
    """
    if n_benchmarks < 1:
        raise ValueError("n_benchmarks must be at least 1")

    returns = returns.dropna()
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations for Deflated Alpha Ratio")

    ann_factor = _annualization_factor(returns.index)
    t_obs = len(returns)
    alpha_per_period = float(alpha) / np.sqrt(ann_factor)

    ln_benchmarks = np.log(max(int(n_benchmarks), 1))

    # Expected maximum alpha under the null (per-period units)
    alpha_star = None
    if trial_alphas is not None and len(trial_alphas) >= 2:
        trial_alpha = np.asarray([float(a) for a in trial_alphas], dtype=float)
        # Convert to per-period alpha for consistency
        trial_alpha = trial_alpha / np.sqrt(ann_factor)
        trial_std = float(np.std(trial_alpha, ddof=1))
        if trial_std > 0 and np.isfinite(trial_std):
            # Scale by benchmark volatility similar to how Sharpe uses std of returns
            benchmark_vol = float(benchmark_returns.std() * np.sqrt(ann_factor))
            if benchmark_vol > 0:
                alpha_star = trial_std * np.sqrt(2.0 * ln_benchmarks) * benchmark_vol
    if alpha_star is None:
        # Fallback to i.i.d.-normal null approximation
        benchmark_vol = float(benchmark_returns.std() * np.sqrt(ann_factor))
        if benchmark_vol > 0:
            alpha_star = float(np.sqrt(2.0 * ln_benchmarks / t_obs)) * benchmark_vol
        else:
            alpha_star = 0.0

    # Variance of the alpha estimator under non-normality (skew/kurt are
    # invariant to constant shifts, so raw-return moments are valid for alpha)
    skew = float(returns.skew())
    kurt = float(returns.kurtosis()) + 3.0  # pandas reports excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    variance_term = 1.0 - skew * alpha_per_period + ((kurt - 1.0) / 4.0) * alpha_per_period * alpha_per_period
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    denom = np.sqrt(variance_term)

    vol = float(returns.std())
    if vol > 0:
        z = (alpha_per_period - alpha_star) * np.sqrt(t_obs - 1) / denom
    else:
        # Degenerate (constant) returns carry no information about skill
        z = -np.inf

    dar = 0.5 * (1.0 + math.erf(z / np.sqrt(2.0)))
    dar = float(min(max(dar, 0.0), 1.0))

    return {
        "deflated_alpha_ratio": dar,
        "p_value": 1.0 - dar,
        "alpha": float(alpha),
        "expected_max_alpha": float(alpha_star),
        "z_score": float(z) if np.isfinite(z) else None,
        "n_benchmarks": int(n_benchmarks),
        "n_observations": int(t_obs),
        "skewness": float(skew),
        "kurtosis": float(kurt),
    }


def _calculate_strategy_returns(
    data: Union[pd.DataFrame, dict],
    signals: pd.Series,
    commission: float,
    slippage: float,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
) -> pd.Series:
    """Calculate strategy returns from signals and market data.

    Args:
        data: OHLCV data (DataFrame, MultiIndex panel, or dict of DataFrames)
        signals: Position signals (1=long, -1=short, 0=flat)
        commission: Commission rate per trade (as decimal, e.g., 0.0002 = 2 bps)
        slippage: Slippage rate per trade (as decimal)
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
            Typical values: 0.1-1.0 for linear impact models.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied per period on short exposure;
            the per-period rate is borrow_cost divided by the periods per
            year inferred from the data's index (252 for business-daily,
            52 for weekly, etc.).
        funding_cost: Annual funding cost rate for leveraged positions (as
            decimal, e.g., 0.02 = 2% per year). Applied per period on gross
            exposure exceeding 1x; the per-period rate is funding_cost
            divided by the periods per year inferred from the data's index.
    """
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
        vols = []
        for df in data.values():
            aligned = df.reindex(common_index)
            rets.append(aligned["close"].pct_change())
            vols.append(aligned["volume"])
        raw_returns = pd.concat(rets, axis=1).mean(axis=1)
        volume = pd.concat(vols, axis=1).mean(axis=1)
    elif isinstance(data.columns, pd.MultiIndex):
        # For panel data, compute equal-weighted portfolio returns
        close = data["close"]
        raw_returns = close.pct_change().mean(axis=1)
        volume = data["volume"].mean(axis=1)
    else:
        close = data["close"]
        raw_returns = close.pct_change()
        volume = data["volume"]

    positions = signals.shift(1)  # Trade at next period's open

    # Transaction costs: apply on position changes
    position_changes = positions.diff().abs()
    costs = position_changes * (commission + slippage)

    # Market impact model: impact = (position_notional / ADV) * impact_coefficient
    # Position notional = |position| * price (equity value of the position)
    # ADV = rolling average of daily volume (in shares) * price
    if impact_coefficient > 0 and volume is not None:
        # Average Daily Volume in shares (rolling)
        adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
        # Average Daily Volume in notional (shares * price)
        adv_notional = adv_shares * close
        # Position notional = |position| * equity (we approximate with close price * initial_capital)
        # Since we don't have equity at this level, we use position * close as a proxy
        # The cost is applied as a fraction of notional on position changes
        position_notional = position_changes * close
        # Market impact as fraction of notional traded
        market_impact = (position_notional / adv_notional.replace(0, np.nan)) * impact_coefficient
        market_impact = market_impact.fillna(0)
        costs = costs + market_impact

    # Borrow and funding costs are annualized rates applied per period.
    # The per-period rate divides by the number of periods per year inferred
    # from the data's index (e.g. 252 for business-daily, 365 for
    # calendar-daily, 52 for weekly, 12 for monthly), matching the
    # annualization used for the strategy's own return metrics. Falls back
    # to 252 when the frequency cannot be inferred.
    ann_factor = _annualization_factor(raw_returns.index)

    # Borrow cost for short positions
    # Applied per period on the absolute value of short positions
    if borrow_cost > 0:
        # Convert annual rate to per-period rate
        period_borrow_rate = borrow_cost / ann_factor
        # Short positions are negative; borrow cost applies to absolute short exposure
        short_positions = positions.clip(upper=0).abs()
        borrow_costs = short_positions * period_borrow_rate
        costs = costs + borrow_costs

    # Funding cost for leveraged positions (gross exposure > 1)
    # Applied per period on the amount of leverage used beyond 100% equity
    if funding_cost > 0:
        # Convert annual rate to per-period rate
        period_funding_rate = funding_cost / ann_factor
        # Gross leverage = absolute position size
        gross_exposure = positions.abs()
        # Funding cost applies to leverage beyond 1x (i.e., gross_exposure - 1 when > 1)
        leverage_excess = (gross_exposure - 1).clip(lower=0)
        funding_costs = leverage_excess * period_funding_rate
        costs = costs + funding_costs

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
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    **kwargs,
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
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (multiple-testing correction) for each fold's in-sample
            parameter selection, plus an aggregate correction on the
            combined out-of-sample returns with n_trials equal to the
             total number of configurations evaluated across all folds.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)

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
    total_evaluated_trials = 0
    all_trial_sharpes: List[float] = []
    fold_benchmark_stats = []

    for fold in folds:
        train_data = fold["train_data"]
        test_data = fold["test_data"]

        best_sharpe = -np.inf
        best_params = None
        best_test_returns = None
        fold_trial_sharpes: List[float] = []
        best_train_returns = None

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
                    test_data, test_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost
                )

                # Evaluate on training set
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost
                )

                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                else:
                    sharpe = -np.inf

                if apply_deflation and np.isfinite(sharpe):
                    fold_trial_sharpes.append(float(sharpe))

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_test_returns = test_returns
                    if apply_deflation:
                        best_train_returns = train_returns

            except Exception:
                continue

        best_params_per_fold.append(best_params)
        all_trial_sharpes.extend(fold_trial_sharpes)
        total_evaluated_trials += len(fold_trial_sharpes)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            fold["best_params"] = best_params
            fold["best_sharpe"] = best_sharpe
            fold["test_returns"] = best_test_returns
            # Compute benchmark stats for this fold
            if benchmark is not None:
                if isinstance(benchmark, list) and len(benchmark) > 1:
                    # Multiple benchmarks: surface a per-fold Deflated Alpha
                    # correction (multiple-testing control across the benchmark
                    # set).  Uses the shared helper so the correction is applied
                    # identically to the aggregate path.
                    correction = _benchmark_list_alpha_correction(
                        best_test_returns, benchmark,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                    fold["benchmark_stats"] = correction["per_benchmark"]
                    fold["deflated_alpha"] = correction["deflated_alpha"]
                    fold_benchmark_stats.append(correction["per_benchmark"])
                else:
                    # Single benchmark (DataFrame or single-element list):
                    # backward-compatible path (no cross-benchmark deflation).
                    bench = benchmark[0] if isinstance(benchmark, list) else benchmark
                    benchmark_returns = _compute_benchmark_returns(bench, best_test_returns, total_return_benchmark)
                    if benchmark_returns is not None:
                        fold_ann_factor = _annualization_factor(best_test_returns.index)
                        bench_stats = _benchmark_stats(
                            best_test_returns, benchmark_returns, fold_ann_factor,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        fold_benchmark_stats.append(bench_stats)
                    else:
                        fold_benchmark_stats.append(None)
            else:
                fold_benchmark_stats.append(None)
            if apply_deflation and best_train_returns is not None and fold_trial_sharpes:
                # Deflate the in-sample selection Sharpe by the number
                # of configurations compared in this fold's grid search.
                fold["deflated_sharpe"] = deflated_sharpe_ratio(
                    sharpe_ratio=best_sharpe,
                    returns=best_train_returns,
                    n_trials=len(fold_trial_sharpes),
                    trial_sharpes=fold_trial_sharpes,
                )
        else:
            fold["best_params"] = None
            fold["best_sharpe"] = None
            fold["test_returns"] = pd.Series(dtype=float)
            fold_benchmark_stats.append(None)

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

    # Aggregate multiple-testing correction on the combined out-of-sample
    # returns. The conservative interpretation: the OOS record was produced
    # by a search that evaluated total_evaluated_trials configurations, so
    # the OOS Sharpe is deflated by all of them. Use the pooled cross-fold
    # trial Sharpes for the cross-sectional SR* estimator (conservative:
    # between-fold variation inflates the null Sharpe).
    #
    # The guard is `len(oos_returns) > 1` only: a constant OOS return series
    # (zero variance) is a degenerate case, not a reason to skip the
    # correction. `deflated_sharpe_ratio` handles it internally (it sets
    # `z = -inf` when `returns.std() == 0`), yielding the conservative
    # DSR = 0, p_value = 1, z_score = None. Skipping the key with an
    # `oos_returns.std() > 0` guard would be inconsistent with `run_backtest`
    # and the `monte-carlo` subcommand, which both emit the degenerate dict
    # when `n_trials` is provided.
    if apply_deflation and len(oos_returns) > 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=summary.get("oos_sharpe", 0.0),
            returns=oos_returns,
            n_trials=max(total_evaluated_trials, 1),
            trial_sharpes=all_trial_sharpes if all_trial_sharpes else None,
        )

    # Benchmark comparison on combined OOS returns
    if benchmark is not None and len(oos_returns) > 0:
        if isinstance(benchmark, list) and len(benchmark) > 1:
            # Multiple benchmarks: surface a cross-benchmark Deflated Alpha
            # correction on the aggregate out-of-sample record, mirroring the
            # calculate_metrics / benchmark_list path.
            correction = _benchmark_list_alpha_correction(
                oos_returns, benchmark,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=benchmark_commission,
                benchmark_slippage=benchmark_slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
            summary["benchmark_metrics"] = correction["per_benchmark"]
            if correction["deflated_alpha"] is not None:
                summary["deflated_alpha"] = correction["deflated_alpha"]
        else:
            # Single benchmark (DataFrame or single-element list): backward compat
            bench = benchmark[0] if isinstance(benchmark, list) else benchmark
            benchmark_returns = _compute_benchmark_returns(bench, oos_returns, total_return_benchmark)
            if benchmark_returns is not None:
                summary = _add_benchmark_to_summary(
                    summary, oos_returns, benchmark_returns,
                    commission=benchmark_commission, slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )

    # Add per-fold benchmark metrics to summary
    if fold_benchmark_stats:
        summary['benchmark_metrics_per_fold'] = fold_benchmark_stats

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


def out_of_sample_validation(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    test_frac: float = 0.2,
    validation_method: str = "walk_forward",
    walk_forward_train_months: int = 12,
    walk_forward_test_months: int = 3,
    walk_forward_step_months: int = 3,
    cpcv_n_splits: int = 10,
    cpcv_test_size: float = 0.1,
    cpcv_purge_size: float = 0.0,
    cpcv_embargo_size: float = 0.0,
    selection_criterion: str = "best_oos_sharpe",
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    apply_deflation: bool = False,
    benchmark: Optional[List[pd.DataFrame]] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """
    Perform rigorous out-of-sample validation with chronological train/validation/test split.

    This function implements a three-phase validation framework to prevent data leakage:
    1. TRAIN: Walk-forward analysis or CPCV on the training portion to select optimal parameters
    2. VALIDATE: Evaluate selected parameters on the validation portion (confirmation)
    3. TEST: Final evaluation on the held-out test set (never used in any selection step)

    Args:
        data: OHLCV DataFrame indexed by date (or dict panel)
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        train_frac: Fraction of data for training (default 0.6)
        val_frac: Fraction of data for validation (default 0.2)
        test_frac: Fraction of data for testing (default 0.2)
        validation_method: "walk_forward" or "cpcv" for parameter selection on training data
        walk_forward_train_months: Training window size in months for walk-forward
        walk_forward_test_months: Testing window size in months for walk-forward
        walk_forward_step_months: Step size between walk-forward iterations
        cpcv_n_splits: Number of sequential groups for CPCV
        cpcv_test_size: Fraction of each group to use as test set in CPCV
        cpcv_purge_size: Fraction of observations to purge from training around test
        cpcv_embargo_size: Fraction of observations to embargo after test set
        selection_criterion: How to select final params from validation results:
            - "best_oos_sharpe": Best out-of-sample Sharpe from walk-forward/CPCV
            - "most_stable": Most frequently selected params across periods/folds
            - "best_avg_sharpe": Best average Sharpe across periods/folds
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade
        impact_coefficient: Market impact coefficient
        adv_window: Rolling window for Average Daily Volume calculation
        borrow_cost: Annual borrow cost rate for short positions
        funding_cost: Annual funding cost rate for leveraged positions
        apply_deflation: Compute Deflated Sharpe Ratio for multiple-testing correction
        benchmark: Optional list of benchmark OHLCV DataFrames for buy-and-hold comparison. When multiple benchmarks are provided, alpha p-values are corrected for multiple comparisons using a Deflated Alpha analogue.
        total_return_benchmark: Compute benchmark returns using total return (dividends + price)
        benchmark_commission: Commission per trade for benchmark (applies to all benchmarks if multiple provided)
        benchmark_slippage: Slippage per trade for benchmark (applies to all benchmarks if multiple provided)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%) (applies to all benchmarks if multiple provided)
    Returns:
        Dictionary with:
            - 'train_val_test_split': Dict with split boundaries and sizes
            - 'validation_results': Full results from walk_forward_analysis or cpcv_analysis on training data
            - 'selected_params': Parameters selected by the selection criterion
            - 'validation_performance': Performance of selected params on validation data
            - 'test_performance': Final performance on held-out test data
            - 'test_benchmark': Benchmark comparison on test data (if benchmark provided). When multiple benchmarks are provided, this is a list of benchmark comparisons, and the summary includes multiple-testing correction for benchmark alpha.
            - 'summary': Aggregate summary with key metrics, deflated Sharpe, and deflated alpha p-values when multiple benchmarks are provided
    """
    # Normalize data format
    if isinstance(data, dict):
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

    # Split data chronologically
    train_data, val_data, test_data = _split_train_val_test(
        data, train_frac=train_frac, val_frac=val_frac, test_frac=test_frac
    )

    # Record split boundaries
    split_info = {
        "train_start": train_data.index[0],
        "train_end": train_data.index[-1],
        "val_start": val_data.index[0],
        "val_end": val_data.index[-1],
        "test_start": test_data.index[0],
        "test_end": test_data.index[-1],
        "train_size": len(train_data),
        "val_size": len(val_data),
        "test_size": len(test_data),
        "train_frac": train_frac,
        "val_frac": val_frac,
        "test_frac": test_frac,
    }

    # Executable invariant: assert the three splits are pairwise disjoint
    # and chronologically ordered. A leak here would silently invalidate
    # the "held-out test set has never been used in any selection step"
    # guarantee, so the check result is recorded in the summary for audit.
    separation_check = _verify_split_separation(train_data, val_data, test_data)
    split_info["separation_check"] = separation_check

    # Phase 1: VALIDATION - Run walk-forward or CPCV on training data
    if validation_method == "walk_forward":
        validation_results = walk_forward_analysis(
            data=train_data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=walk_forward_train_months,
            test_months=walk_forward_test_months,
            step_months=walk_forward_step_months,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            apply_deflation=apply_deflation,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=benchmark_commission,
            benchmark_slippage=benchmark_slippage,
            benchmark_expense_ratio=benchmark_expense_ratio,
        )
    elif validation_method == "cpcv":
        validation_results = cpcv_analysis(
            data=train_data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=cpcv_n_splits,
            test_size=cpcv_test_size,
            purge_size=cpcv_purge_size,
            embargo_size=cpcv_embargo_size,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            apply_deflation=apply_deflation,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=benchmark_commission,
            benchmark_slippage=benchmark_slippage,
            benchmark_expense_ratio=benchmark_expense_ratio,
        )
    else:
        raise ValueError(f"Unknown validation_method: {validation_method}. Use 'walk_forward' or 'cpcv'.")

    # Phase 2: SELECTION - Select best parameters based on criterion
    selected_params = _select_parameters(
        validation_results=validation_results,
        validation_method=validation_method,
        criterion=selection_criterion,
    )

    if selected_params is None:
        return {
            "train_val_test_split": split_info,
            "validation_results": validation_results,
            "selected_params": None,
            "validation_performance": None,
            "test_performance": None,
            "test_benchmark": None,
            "summary": {
                "error": "No valid parameters found in validation phase",
                "train_val_test_split": split_info,
            },
        }

    # Phase 3: CONFIRMATION - Evaluate selected params on validation data
    strategy = strategy_factory(selected_params)
    val_signals = strategy.generate_signals(val_data)
    val_returns = _calculate_strategy_returns(
        val_data, val_signals, commission, slippage,
        impact_coefficient, adv_window, borrow_cost, funding_cost
    )

    ann_factor = _annualization_factor(val_returns.index)
    excess = val_returns - 0.02 / ann_factor
    val_sharpe = float(excess.mean() / excess.std() * np.sqrt(ann_factor)) if len(val_returns) > 1 and val_returns.std() > 0 else 0.0
    val_total_return = float((1 + val_returns).prod() - 1) if len(val_returns) > 0 else 0.0

    validation_performance = {
        "selected_params": selected_params,
        "val_total_return": val_total_return,
        "val_sharpe": val_sharpe,
        "val_volatility": float(val_returns.std() * np.sqrt(ann_factor)) if len(val_returns) > 1 else 0.0,
        "val_n_periods": len(val_returns),
    }

    # Phase 4: FINAL TEST - Evaluate on held-out test data
    test_signals = strategy.generate_signals(test_data)
    test_returns = _calculate_strategy_returns(
        test_data, test_signals, commission, slippage,
        impact_coefficient, adv_window, borrow_cost, funding_cost
    )

    ann_factor_test = _annualization_factor(test_returns.index)
    excess_test = test_returns - 0.02 / ann_factor_test
    test_sharpe = float(excess_test.mean() / excess_test.std() * np.sqrt(ann_factor_test)) if len(test_returns) > 1 and test_returns.std() > 0 else 0.0
    test_total_return = float((1 + test_returns).prod() - 1) if len(test_returns) > 0 else 0.0

    test_performance = {
        "test_total_return": test_total_return,
        "test_sharpe": test_sharpe,
        "test_volatility": float(test_returns.std() * np.sqrt(ann_factor_test)) if len(test_returns) > 1 else 0.0,
        "test_n_periods": len(test_returns),
        "test_returns": test_returns,
    }

    # Benchmark comparison on test set
    test_benchmark = None
    if benchmark is not None and len(test_returns) > 0:
        # Handle multiple benchmarks for multiple-testing correction
        if isinstance(benchmark, list):
            # Process each benchmark
            benchmark_results = []
            p_values = []
            for i, bench in enumerate(benchmark):
                benchmark_returns = _compute_benchmark_returns(bench, test_returns, total_return_benchmark)
                if benchmark_returns is not None:
                    if benchmark_cost_is_periodic and "splits" in bench.columns:
                        bench_stats = _benchmark_stats_with_splits(
                            test_returns, benchmark_returns, ann_factor_test,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                            benchmark_data=bench,
                        )
                    else:
                        bench_stats = _benchmark_stats(
                            test_returns, benchmark_returns, ann_factor_test,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                    benchmark_results.append(bench_stats)
                    if 'alpha_pvalue' in bench_stats and bench_stats['alpha_pvalue'] is not None:
                        p_values.append(bench_stats['alpha_pvalue'])
                    else:
                        p_values.append(1.0)  # If no p-value, treat as non-significant
                else:
                    benchmark_results.append(None)
                    p_values.append(1.0)

            # Apply multiple-testing correction to alpha p-values using Deflated Alpha analogue
            if p_values and len(p_values) > 1:
                # Collect trial alphas for Deflated Alpha calculation
                trial_alphas = []
                for bench_result in benchmark_results:
                    if bench_result is not None and 'alpha' in bench_result:
                        trial_alphas.append(bench_result['alpha'])

                # Apply Deflated Alpha correction to each benchmark result
                for i, bench_result in enumerate(benchmark_results):
                    if bench_result is not None and 'alpha' in bench_result and len(trial_alphas) >= 2:
                        # Use the benchmark returns for this specific benchmark to calculate volatility
                        bench_idx = i if isinstance(benchmark, list) else 0
                        if isinstance(benchmark, list) and bench_idx < len(benchmark):
                            bench_returns = _compute_benchmark_returns(
                                benchmark[bench_idx], test_returns, total_return_benchmark
                            )
                            if bench_returns is not None:
                                dar_result = deflated_alpha_ratio(
                                    alpha=bench_result['alpha'],
                                    returns=test_returns,
                                    benchmark_returns=bench_returns,
                                    n_benchmarks=len(p_values),
                                    trial_alphas=trial_alphas
                                )
                                # Store both original and corrected p-values
                                bench_result['alpha_pvalue_original'] = p_values[i]
                                bench_result['alpha_pvalue'] = dar_result['p_value']
                                # Also store the deflated alpha for transparency
                                bench_result['deflated_alpha'] = dar_result['deflated_alpha_ratio']
                                bench_result['expected_max_alpha'] = dar_result['expected_max_alpha']
                            else:
                                # Fallback to Bonferroni if benchmark returns computation fails
                                corrected_p = min(p_values[i] * len(p_values), 1.0)
                                bench_result['alpha_pvalue_original'] = p_values[i]
                                bench_result['alpha_pvalue'] = corrected_p
                        else:
                            # Fallback to Bonferroni
                            corrected_p = min(p_values[i] * len(p_values), 1.0)
                            bench_result['alpha_pvalue_original'] = p_values[i]
                            bench_result['alpha_pvalue'] = corrected_p
                    elif bench_result is not None:
                        # Fallback to Bonferroni if we don't have enough trial alphas
                        corrected_p = min(p_values[i] * len(p_values), 1.0)
                        bench_result['alpha_pvalue_original'] = p_values[i]
                        bench_result['alpha_pvalue'] = corrected_p

            test_benchmark = benchmark_results
        else:
            # Single benchmark (backward compatibility)
            benchmark_returns = _compute_benchmark_returns(benchmark, test_returns, total_return_benchmark)
            if benchmark_returns is not None:
                if benchmark_cost_is_periodic and "splits" in benchmark.columns:
                    test_benchmark = _benchmark_stats_with_splits(
                        test_returns, benchmark_returns, ann_factor_test,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        benchmark_data=benchmark,
                    )
                else:
                    test_benchmark = _benchmark_stats(
                        test_returns, benchmark_returns, ann_factor_test,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                test_performance.update(test_benchmark)

    # Aggregate summary
    summary = {
        "train_val_test_split": split_info,
        "validation_method": validation_method,
        "selection_criterion": selection_criterion,
        "selected_params": selected_params,
        "validation_total_return": val_total_return,
        "validation_sharpe": val_sharpe,
        "test_total_return": test_total_return,
        "test_sharpe": test_sharpe,
        "test_volatility": test_performance["test_volatility"],
    }

    # Add multiple benchmark information to summary if applicable
    if isinstance(test_benchmark, list):
        summary["multiple_benchmarks"] = True
        summary["benchmark_count"] = len(test_benchmark)
        # Collect alpha p-values (both original and corrected if available)
        alpha_pvalues = []
        alpha_pvalues_original = []
        deflated_alphas = []
        expected_max_alphas = []
        for bench_result in test_benchmark:
            if bench_result is not None:
                if 'alpha_pvalue_original' in bench_result:
                    alpha_pvalues_original.append(bench_result['alpha_pvalue_original'])
                    alpha_pvalues.append(bench_result['alpha_pvalue'])  # corrected
                    if 'deflated_alpha' in bench_result:
                        deflated_alphas.append(bench_result['deflated_alpha'])
                    if 'expected_max_alpha' in bench_result:
                        expected_max_alphas.append(bench_result['expected_max_alpha'])
                elif 'alpha_pvalue' in bench_result:
                    alpha_pvalues.append(bench_result['alpha_pvalue'])
        if alpha_pvalues:
            summary["alpha_pvalues"] = alpha_pvalues
            if alpha_pvalues_original:
                summary["alpha_pvalues_original"] = alpha_pvalues_original
        if deflated_alphas:
            summary["deflated_alphas"] = deflated_alphas
        if expected_max_alphas:
            summary["expected_max_alphas"] = expected_max_alphas

    # Add Deflated Sharpe Ratio on test returns if requested
    # n_trials = total configurations evaluated in validation phase
    total_trials = 0
    if validation_method == "walk_forward":
        for period in validation_results.get("periods", []):
            if period.get("best_params") is not None:
                # Count evaluated configs for this period
                total_trials += len(list(product(*param_grid.values())))
    elif validation_method == "cpcv":
        for fold in validation_results.get("folds", []):
            if fold.get("best_params") is not None:
                total_trials += len(list(product(*param_grid.values())))

    if apply_deflation and len(test_returns) > 1 and total_trials > 0:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=test_sharpe,
            returns=test_returns,
            n_trials=total_trials,
            trial_sharpes=None,  # We don't have the trial sharpes from validation here
        )

    # Add benchmark information to summary (only for single benchmark for backward compatibility)
    if test_benchmark and not isinstance(test_benchmark, list):
        summary.update(test_benchmark)

    return {
        "train_val_test_split": split_info,
        "validation_results": validation_results,
        "selected_params": selected_params,
        "validation_performance": validation_performance,
        "test_performance": test_performance,
        "test_benchmark": test_benchmark,
        "summary": summary,
    }


def _select_parameters(
    validation_results: Dict[str, Any],
    validation_method: str,
    criterion: str = "best_oos_sharpe",
) -> Optional[Dict[str, Any]]:
    """Select optimal parameters from validation results based on criterion."""
    if validation_method == "walk_forward":
        periods = validation_results.get("periods", [])
        valid_periods = [p for p in periods if p.get("best_params") is not None]

        if not valid_periods:
            return None

        if criterion == "best_oos_sharpe":
            # Select params from period with best test Sharpe
            best_period = max(valid_periods, key=lambda p: p.get("best_sharpe", -np.inf))
            return best_period["best_params"]

        elif criterion == "most_stable":
            # Most frequently selected params across periods
            from collections import Counter
            param_tuples = [tuple(sorted(p["best_params"].items())) for p in valid_periods]
            if param_tuples:
                most_common = Counter(param_tuples).most_common(1)[0][0]
                return dict(most_common)
            return None

        elif criterion == "best_avg_sharpe":
            # Params with best average Sharpe across periods where they were selected
            from collections import defaultdict
            param_sharpes = defaultdict(list)
            for p in valid_periods:
                key = tuple(sorted(p["best_params"].items()))
                param_sharpes[key].append(p["best_sharpe"])

            best_key = max(param_sharpes.keys(), key=lambda k: np.mean(param_sharpes[k]))
            return dict(best_key)

    elif validation_method == "cpcv":
        folds = validation_results.get("folds", [])
        valid_folds = [f for f in folds if f.get("best_params") is not None]

        if not valid_folds:
            return None

        if criterion == "best_oos_sharpe":
            best_fold = max(valid_folds, key=lambda f: f.get("best_sharpe", -np.inf))
            return best_fold["best_params"]

        elif criterion == "most_stable":
            from collections import Counter
            param_tuples = [tuple(sorted(f["best_params"].items())) for f in valid_folds]
            if param_tuples:
                most_common = Counter(param_tuples).most_common(1)[0][0]
                return dict(most_common)
            return None

        elif criterion == "best_avg_sharpe":
            from collections import defaultdict
            param_sharpes = defaultdict(list)
            for f in valid_folds:
                key = tuple(sorted(f["best_params"].items()))
                param_sharpes[key].append(f["best_sharpe"])

            best_key = max(param_sharpes.keys(), key=lambda k: np.mean(param_sharpes[k]))
            return dict(best_key)

    # Default fallback
    if validation_method == "walk_forward" and validation_results.get("periods"):
        for p in validation_results["periods"]:
            if p.get("best_params") is not None:
                return p["best_params"]
    elif validation_method == "cpcv" and validation_results.get("folds"):
        for f in validation_results["folds"]:
            if f.get("best_params") is not None:
                return f["best_params"]

    return None


def run_cpcv(args) -> int:
    """Run CPCV analysis from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        benchmark_paths = args.benchmark if isinstance(args.benchmark, list) else [args.benchmark]
        print(f"Loading benchmark data from {', '.join(benchmark_paths)}...")
        if len(benchmark_paths) == 1:
            benchmark, benchmark_provenance = _load_benchmark(benchmark_paths[0], total_return_benchmark)
        else:
            benchmark = []
            benchmark_provenance = []
            for bench_file in benchmark_paths:
                b, prov = _load_benchmark(bench_file, total_return_benchmark)
                benchmark.append(b)
                benchmark_provenance.append(prov)

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
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    benchmark_returns_list = None
    if benchmark is not None and len(results["oos_returns"]) > 0:
        if isinstance(benchmark, list):
            # Multiple benchmarks: the aggregate Deflated Alpha comparison is
            # already computed inside cpcv_analysis; expose the aligned
            # benchmark returns to calculate_metrics (which surfaces the
            # canonical deflated_alpha via its benchmark_list path).
            benchmark_returns_list = []
            for b in benchmark:
                br = _compute_benchmark_returns(b, results["oos_returns"], total_return_benchmark)
                if br is not None:
                    benchmark_returns_list.append(br)
            if benchmark_returns_list and results["summary"].get("deflated_alpha") is None:
                # Defensive: ensure a deflated_alpha surfaces even if cpcv_analysis
                # did not compute one (e.g. degenerate returns).
                correction = _benchmark_list_alpha_correction(
                    results["oos_returns"], benchmark,
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=bench_commission,
                    benchmark_slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                )
                if correction["deflated_alpha"] is not None:
                    results["summary"]["deflated_alpha"] = correction["deflated_alpha"]
                results["summary"]["benchmark_metrics"] = correction["per_benchmark"]
        else:
            benchmark_returns = _compute_benchmark_returns(benchmark, results["oos_returns"], total_return_benchmark)
            if benchmark_returns is not None:
                # Single benchmark: backward-compatible summary update
                results["summary"] = _add_benchmark_to_summary(
                    results["summary"], results["oos_returns"], benchmark_returns,
                    commission=bench_commission, slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                    benchmark_data=benchmark,
                )
                print(
                    f"Benchmark Correlation: {results['summary'].get('correlation_with_benchmark', 'N/A'):.4f}"
                )
                print(
                    f"Alpha (annualized): {results['summary'].get('alpha', 'N/A'):.2%}"
                )
                print(
                    f"Beta: {results['summary'].get('beta', 'N/A'):.4f}"
                )
                pval = results["summary"].get("alpha_pvalue")
                print(
                    f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                )
                rs = results["summary"].get("r_squared")
                print(
                    f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
                )

    print(f"Number of CPCV folds: {results['summary']['n_folds']}")
    print(f"Total OOS Return: {results['summary']['total_oos_return']:.2%}")
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    print(f"Avg Parameter Stability: {results['summary'].get('avg_param_stability', 'N/A'):.2f}")
    print(f"Overfitting Risk: {results['summary'].get('overfitting_risk', 'N/A')}")

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

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
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
    if benchmark_provenance is not None:
        if isinstance(benchmark_provenance, list):
            summary_data["benchmark_provenance"] = [prov.to_dict() for prov in benchmark_provenance]
        else:
            summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
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
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
            },
        }
        if benchmark_returns is not None:
            report_results["benchmark"] = benchmark_returns
        elif benchmark_returns_list:
            report_results["benchmark_list"] = benchmark_returns_list
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_cpcv")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_cpcv",
            analysis_results={"cpcv": results},
        )
        print(f"Detailed report saved to: {args.output}/")

    return 0


def _make_strategy_factory(strategy_type: str):
    """Create a strategy factory function for the given strategy type."""
    def factory(params: Dict[str, Any]):
        return build_strategy(strategy_type, json.dumps(params))
    return factory


def _load_and_validate_data(
    data_path: str,
    symbol: str,
    start: str,
    end: str,
    validate_pit: bool = False,
    pit_strict: bool = False,
) -> tuple[pd.DataFrame, Optional[Dict[str, Any]]]:
    """Load and validate data from file.

    When validate_pit is True, run point-in-time validation on the
    loaded frame (temporal ordering, duplicate timestamps, stale-data
    warnings) and print the results. With pit_strict, violations raise
    so the analysis aborts instead of continuing on suspect data.

    Returns:
        tuple of (data_frame, pit_results_dict_or_None)
    """
    data = load_data(data_path, symbol=symbol, start=start, end=end)
    if not validate_data(data):
        raise ValueError("Data validation failed!")
    pit = None
    if validate_pit:
        pit = validate_point_in_time(data)
        if pit["violations"]:
            print("Point-in-time validation violations:")
            for violation in pit["violations"]:
                print(f"  - {violation}")
        if pit["warnings"]:
            print("Point-in-time validation warnings:")
            for warning in pit["warnings"]:
                print(f"  - {warning}")
        if not pit["violations"] and not pit["warnings"]:
            print("Point-in-time validation passed (no violations or warnings).")
        elif not pit["violations"]:
            print("Point-in-time validation passed (no violations).")
        if pit_strict and not pit["passed"]:
            raise ValueError(
                "Point-in-time validation failed in strict mode: "
                + "; ".join(pit["violations"])
            )
    return data, pit


def _load_benchmark(benchmark_path: str, total_return_benchmark: bool = False) -> tuple[pd.DataFrame, Optional[Any]]:
    """Load benchmark data and return (benchmark_df, benchmark_provenance)."""
    benchmark, provenance = load_data(benchmark_path, return_provenance=True)
    if not validate_data(benchmark):
        raise ValueError("Benchmark data validation failed!")
    print(
        f"Loaded benchmark: {provenance.final_shape[0]} rows "
        f"(checksum {provenance.checksum}, "
        f"total_return_type: {provenance.total_return_type})"
    )
    if total_return_benchmark:
        if provenance.total_return_type == "total":
            print("Using total-return benchmark (dividends/adj_close included)")
        else:
            print("Warning: --total-return-benchmark requested but benchmark data has no dividends/adj_close column; falling back to price-only returns")
    return benchmark, provenance


def _compute_benchmark_returns(
    benchmark: pd.DataFrame,
    strategy_returns: pd.Series,
    total_return_benchmark: bool = False,
) -> Optional[pd.Series]:
    """Compute buy-and-hold benchmark returns aligned to strategy returns.

    The benchmark return for period t is the close-to-close return
    from t-1 to t (no shift). Aligned to the strategy returns index
    via inner join on common trading dates.

    If total_return_benchmark is True, uses _compute_benchmark_total_return
    which includes dividends/adj_close when available.
    """
    if total_return_benchmark:
        benchmark_returns = _compute_benchmark_total_return(benchmark)
    else:
        benchmark_returns = benchmark["close"].pct_change()
    _, aligned_benchmark = strategy_returns.align(benchmark_returns, join="inner")
    if len(aligned_benchmark) > 0:
        return aligned_benchmark
    return None


def _add_benchmark_to_summary(
    summary: Dict[str, Any],
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    commission: float = 0.0,
    slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    total_return_benchmark: bool = False,
    benchmark_cost_is_periodic: bool = False,
    benchmark_data: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Add benchmark comparison metrics to a summary dict.

    Computes benchmark total/annualized return, correlation, alpha, beta,
    the alpha t-statistic, its two-sided p-value, and the regression R^2
    from the aligned return series (delegates to ``_benchmark_stats``).

    Args:
        summary: Dictionary to update with benchmark metrics.
        strategy_returns: Strategy returns series.
        benchmark_returns: Benchmark returns series.
        commission: Commission rate per trade.
        slippage: Slippage rate per trade.
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%).
        total_return_benchmark: If True, compute benchmark returns using total return (dividends + price).
        benchmark_data: Original benchmark OHLCV data with splits column (optional).
    """
    if len(benchmark_returns) == 0:
        return summary

    ann_factor = _annualization_factor(strategy_returns.index)

    # If we have benchmark data and periodic costs are requested, use split-aware cost calculation
    if benchmark_cost_is_periodic and benchmark_data is not None and "splits" in benchmark_data.columns:
        # Align benchmark data with returns
        _, aligned_benchmark_data = strategy_returns.align(benchmark_data, join="inner")
        if len(aligned_benchmark_data) > 0:
            stats = _benchmark_stats_with_splits(
                strategy_returns, benchmark_returns, ann_factor,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=commission,
                benchmark_slippage=slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                benchmark_data=aligned_benchmark_data,
            )
        else:
            stats = _benchmark_stats(
                strategy_returns, benchmark_returns, ann_factor,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=commission,
                benchmark_slippage=slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
    else:
        stats = _benchmark_stats(
            strategy_returns, benchmark_returns, ann_factor,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=commission,
            benchmark_slippage=slippage,
            benchmark_expense_ratio=benchmark_expense_ratio,
            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
        )
    summary.update(stats)
    return summary


def _benchmark_stats_with_splits(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    ann_factor: float,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    benchmark_data: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute benchmark stats with split-adjusted returns.

    When benchmark OHLCV data includes a ``splits`` column, prices are
    adjusted for splits before computing returns.  This prevents the
    artificial return drop that a stock split would otherwise introduce on
    the split date (e.g. a 2-for-1 split halves the close price), which
    would distort benchmark comparison metrics and cost calculations.

    After recomputing returns from split-adjusted prices, the function
    delegates to ``_benchmark_stats`` and forwards ``benchmark_cost_is_periodic``
    unchanged so that periodic or round-trip cost handling is preserved.
    """
    if benchmark_data is not None and "splits" in benchmark_data.columns:
        benchmark_data = adjust_for_splits(benchmark_data)

    if benchmark_data is not None and "close" in benchmark_data.columns:
        if total_return_benchmark:
            adjusted_benchmark_returns = _compute_benchmark_total_return(benchmark_data)
        else:
            adjusted_benchmark_returns = benchmark_data["close"].pct_change()
        _, aligned_bench = strategy_returns.align(
            adjusted_benchmark_returns, join="inner"
        )
        if len(aligned_bench) > 0:
            benchmark_returns = aligned_bench

    return _benchmark_stats(
        strategy_returns,
        benchmark_returns,
        ann_factor,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=benchmark_commission,
        benchmark_slippage=benchmark_slippage,
        benchmark_expense_ratio=benchmark_expense_ratio,
        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
    )


def _benchmark_list_alpha_correction(
    strategy_returns: pd.Series,
    benchmark_list: List[pd.DataFrame],
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
) -> Dict[str, Any]:
    """Compute per-benchmark comparison stats and a cross-benchmark Deflated Alpha correction.

    Testing a strategy against multiple benchmarks is a multiple-testing problem:
    with enough benchmarks, luck alone yields an attractive alpha.  This helper
    computes the OLS alpha/beta/correlation/p-value for each benchmark
    (split-aware when ``benchmark_cost_is_periodic`` requests it and the
    benchmark data carries a ``splits`` column) and then applies the Deflated
    Alpha Ratio across the benchmark set, mirroring the correction already
    performed by ``out_of_sample_validation`` so the validation, CPCV, and
    walk-forward pipelines apply it uniformly at the per-fold/per-period and
    aggregate levels.

    Returns a dict with:
        - 'per_benchmark': list of per-benchmark stats dicts (None where a
          benchmark had no aligned returns).  When >= 2 benchmarks produced
          finite alphas each dict also carries the corrected ``alpha_pvalue``,
          ``alpha_pvalue_original``, ``deflated_alpha`` and
          ``expected_max_alpha``.
        - 'deflated_alpha': aggregate Deflated Alpha Ratio dict for the primary
          (first) benchmark when >= 2 benchmarks produced finite alphas, else
          None (same shape as ``deflated_alpha_ratio`` output).
        - 'n_benchmarks': number of benchmarks tested
    """
    per_benchmark: List[Optional[Dict[str, Any]]] = []
    p_values: List[float] = []
    benchmark_returns_list: List[Optional[pd.Series]] = []

    # Drop NaN from the strategy returns once; downstream OLS and the Deflated
    # Alpha Ratio assume a common-date aligned, NaN-free series.  This is
    # idempotent on returns already produced by _calculate_strategy_returns
    # (which dropna's), but makes the helper robust to leading-NaN pct_change
    # artifacts when callers pass arbitrary return series.
    strategy_returns = strategy_returns.dropna()

    for bench in benchmark_list:
        benchmark_returns = _compute_benchmark_returns(
            bench, strategy_returns, total_return_benchmark
        )
        if benchmark_returns is not None:
            benchmark_returns = benchmark_returns.dropna()
        benchmark_returns_list.append(benchmark_returns)
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            if benchmark_cost_is_periodic and isinstance(bench, pd.DataFrame) and "splits" in bench.columns:
                bench_stats = _benchmark_stats_with_splits(
                    strategy_returns, benchmark_returns, _annualization_factor(strategy_returns.index),
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=benchmark_commission,
                    benchmark_slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )
            else:
                bench_stats = _benchmark_stats(
                    strategy_returns, benchmark_returns, _annualization_factor(strategy_returns.index),
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=benchmark_commission,
                    benchmark_slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                )
            per_benchmark.append(bench_stats)
            p_values.append(bench_stats.get("alpha_pvalue", 1.0) if bench_stats.get("alpha_pvalue") is not None else 1.0)
        else:
            per_benchmark.append(None)
            p_values.append(1.0)

    deflated_alpha: Optional[Dict[str, Any]] = None
    n_benchmarks = len(p_values)

    if p_values and n_benchmarks > 1:
        # Collect trial alphas from benchmarks with finite alpha (cross-sectional
        # dispersion estimator for alpha*, when enough are available).
        trial_alphas = [
            r["alpha"] for r in per_benchmark
            if r is not None and "alpha" in r and np.isfinite(r["alpha"])
        ]

        for i, bench_result in enumerate(per_benchmark):
            if bench_result is None or "alpha" not in bench_result:
                continue
            if np.isfinite(bench_result["alpha"]) and len(trial_alphas) >= 2:
                bench_returns = benchmark_returns_list[i]
                if bench_returns is not None:
                    try:
                        dar = deflated_alpha_ratio(
                            alpha=bench_result["alpha"],
                            returns=strategy_returns,
                            benchmark_returns=bench_returns,
                            n_benchmarks=n_benchmarks,
                            trial_alphas=trial_alphas,
                        )
                        bench_result["alpha_pvalue_original"] = p_values[i]
                        bench_result["alpha_pvalue"] = dar["p_value"]
                        bench_result["deflated_alpha"] = dar["deflated_alpha_ratio"]
                        bench_result["expected_max_alpha"] = dar["expected_max_alpha"]
                    except Exception:
                        corrected_p = min(p_values[i] * n_benchmarks, 1.0)
                        bench_result["alpha_pvalue_original"] = p_values[i]
                        bench_result["alpha_pvalue"] = corrected_p
                else:
                    corrected_p = min(p_values[i] * n_benchmarks, 1.0)
                    bench_result["alpha_pvalue_original"] = p_values[i]
                    bench_result["alpha_pvalue"] = corrected_p
            elif bench_result is not None:
                # Fallback (Bonferroni) when too few trial alphas for the
                # cross-sectional estimator.
                corrected_p = min(p_values[i] * n_benchmarks, 1.0)
                bench_result["alpha_pvalue_original"] = p_values[i]
                bench_result["alpha_pvalue"] = corrected_p

        # Aggregate Deflated Alpha for the primary (first) benchmark.
        primary = per_benchmark[0] if per_benchmark and per_benchmark[0] is not None else None
        if primary is not None and "alpha" in primary and np.isfinite(primary["alpha"]):
            first_returns = benchmark_returns_list[0]
            if first_returns is not None:
                try:
                    deflated_alpha = deflated_alpha_ratio(
                        alpha=primary["alpha"],
                        returns=strategy_returns,
                        benchmark_returns=first_returns,
                        n_benchmarks=n_benchmarks,
                        trial_alphas=trial_alphas if len(trial_alphas) >= 2 else None,
                    )
                except Exception:
                    deflated_alpha = None

    return {
        "per_benchmark": per_benchmark,
        "deflated_alpha": deflated_alpha,
        "n_benchmarks": n_benchmarks,
    }


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
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        print(f"Loading benchmark data from {args.benchmark}...")
        benchmark, benchmark_provenance = _load_benchmark(args.benchmark, total_return_benchmark)

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
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    if benchmark is not None and len(results["oos_returns"]) > 0:
        benchmark_returns = _compute_benchmark_returns(benchmark, results["oos_returns"], total_return_benchmark)
        if benchmark_returns is not None:
            # Add benchmark metrics to summary
            results["summary"] = _add_benchmark_to_summary(
                results["summary"], results["oos_returns"], benchmark_returns,
                commission=bench_commission, slippage=bench_slippage,
                benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
                benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                benchmark_data=benchmark,
            )
            print(
                f"Benchmark Correlation: {results['summary'].get('correlation_with_benchmark', 'N/A'):.4f}"
            )
            print(
                f"Alpha (annualized): {results['summary'].get('alpha', 'N/A'):.2%}"
            )
            print(
                f"Beta: {results['summary'].get('beta', 'N/A'):.4f}"
            )
            pval = results["summary"].get("alpha_pvalue")
            print(
                f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
            )
            rs = results["summary"].get("r_squared")
            print(
                f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
            )

    print(f"Number of walk-forward periods: {results['summary']['n_periods']}")
    print(f"Total OOS Return: {results['summary']['total_oos_return']:.2%}")
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

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
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
    if benchmark_provenance is not None:
        summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
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
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
            },
        }
        if benchmark_returns is not None:
            report_results["benchmark"] = benchmark_returns
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_walk_forward")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_walk_forward",
            analysis_results={"walk_forward": results},
        )
        print(f"Detailed report saved to: {args.output}/")

    return 0


def run_parameter_optimization(args) -> int:
    """Run parameter optimization from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        print(f"Loading benchmark data from {args.benchmark}...")
        benchmark, benchmark_provenance = _load_benchmark(args.benchmark, total_return_benchmark)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running parameter optimization with {args.strategy}...")
    results = parameter_optimization(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
    )

    if not results:
        print("No valid parameter combinations found!")
        return 1

    print(f"\nTop {min(args.top_n, len(results))} parameter combinations:")
    print("-" * 80)
    print(f"{'Rank':<5} {'Sharpe':<10} {'Total Return':<15} {'Alpha':<12} {'Beta':<8} {'Corr':<8} {'Params'}")
    print("-" * 80)
    for i, r in enumerate(results[:args.top_n]):
        alpha_str = f"{r.get('alpha', 0):.2%}" if 'alpha' in r else "N/A"
        beta_str = f"{r.get('beta', 0):.4f}" if 'beta' in r else "N/A"
        corr_str = f"{r.get('correlation_with_benchmark', 0):.4f}" if 'correlation_with_benchmark' in r else "N/A"
        print(f"{i+1:<5} {r['sharpe_ratio']:<10.4f} {r['total_return']:<15.2%} {alpha_str:<12} {beta_str:<8} {corr_str:<8} {r['params']}")
        if "deflated_sharpe" in r:
            dsr = r["deflated_sharpe"]
            print(
                f"      Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
                f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
                f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
            )

    # Print benchmark comparison summary if benchmark provided
    if benchmark is not None and results and 'alpha' in results[0]:
        best = results[0]
        print(
            f"\nBenchmark Comparison (best params):"
        )
        print(
            f"  Correlation: {best.get('correlation_with_benchmark', 'N/A'):.4f}"
        )
        print(
            f"  Alpha (annualized): {best.get('alpha', 'N/A'):.2%}"
        )
        print(
            f"  Beta: {best.get('beta', 'N/A'):.4f}"
        )
        pval = best.get("alpha_pvalue")
        print(
            f"  Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
        )
        rs = best.get("r_squared")
        print(
            f"  R-squared: {rs if rs is None else f'{rs:.4f}'}"
        )
        ir = best.get("information_ratio")
        if ir is not None and np.isfinite(ir):
            print(f"  Information Ratio: {ir:.4f}")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results_path = output_dir / "parameter_optimization.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {results_path}")

    # Persist PIT validation results alongside the optimization artifact
    # so the data-integrity baseline is reproducible with the search.
    if pit_results is not None:
        pit_path = output_dir / "point_in_time_validation.json"
        with open(pit_path, "w") as f:
            json.dump(pit_results, f, indent=2, default=str)

    # Persist benchmark provenance if available
    if benchmark_provenance is not None:
        bench_prov_path = output_dir / "benchmark_provenance.json"
        with open(bench_prov_path, "w") as f:
            json.dump(benchmark_provenance.to_dict(), f, indent=2, default=str)
        print(f"Benchmark provenance saved to: {bench_prov_path}")

    return 0


def run_monte_carlo(args) -> int:
    """Run Monte Carlo simulation from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        print(f"Loading benchmark data from {args.benchmark}...")
        benchmark, benchmark_provenance = _load_benchmark(args.benchmark, total_return_benchmark)

    # First run a backtest to get base returns
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    # Use best params from optimization or first combo
    opt_results = None
    if param_grid:
        # Try to get best params from optimization
        opt_results = parameter_optimization(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            commission=args.commission,
            slippage=args.slippage,
            impact_coefficient=args.impact_coefficient,
            adv_window=args.adv_window,
            borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=bench_commission,
            benchmark_slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio,
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
    returns = _calculate_strategy_returns(data, signals, args.commission, args.slippage,
                                         args.impact_coefficient, args.adv_window,
                                         args.borrow_cost, args.funding_cost)

    # Multiple-testing correction: the base backtest's Sharpe was
    # produced by the parameter search above (or by development
    # trials the caller reports via --n-trials). When the number of
    # development trials is reported, deflate the base Sharpe for
    # selection bias and for the non-normality of returns, mirroring
    # the run_backtest --n-trials path. When the optimization
    # record is available, its trial Sharpes give the cross-sectional
    # SR* estimator (recommended over the i.i.d. null approximation).
    #
    # Trial count: when a parameter grid was searched, the internal
    # optimization evaluated len(opt_results) ranked configurations.
    # The effective trial count is max(--n-trials, len(opt_results))
    # so the deflation never understates the search, while still
    # letting the caller report additional development trials beyond
    # the grid. Without a grid (or an empty optimization record) the
    # user-supplied --n-trials is the sole source.
    dsr = None
    n_trials = getattr(args, "n_trials", None)
    effective_n_trials = None
    if n_trials is not None and int(n_trials) >= 1 and len(returns.dropna()) >= 2:
        effective_n_trials = int(n_trials)
        if opt_results:
            effective_n_trials = max(effective_n_trials, len(opt_results))
        base_results = {
            "equity_curve": (1 + returns).cumprod() * args.initial_capital,
            "returns": returns,
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "n_trials": effective_n_trials,
            },
        }
        if opt_results:
            base_results["config"]["trial_sharpes"] = [
                r["sharpe_ratio"] for r in opt_results
            ]
        dsr = calculate_metrics(base_results).get("deflated_sharpe")

    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    if benchmark is not None and len(returns) > 0:
        benchmark_returns = _compute_benchmark_returns(benchmark, returns, total_return_benchmark)
        if benchmark_returns is not None:
            bstats = _benchmark_stats(
                returns, benchmark_returns, _annualization_factor(returns.index),
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=bench_commission,
                benchmark_slippage=bench_slippage,
                benchmark_expense_ratio=bench_expense_ratio,
            )
            print(
                f"Benchmark Correlation: {bstats.get('correlation_with_benchmark', 0):.4f}"
            )
            pval = bstats.get("alpha_pvalue")
            print(
                f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
            )
            rs = bstats.get("r_squared")
            print(
                f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
            )

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
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "n_simulations": args.n_simulations,
            "block_size": args.block_size,
            "point_in_time_validation": pit_results,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
        },
    }
    if pit_results is not None:
        mc_save["point_in_time_validation"] = pit_results
    if dsr is not None:
        mc_save["deflated_sharpe"] = dsr
        mc_save["config"]["n_trials"] = effective_n_trials
    if benchmark_provenance is not None:
        mc_save["benchmark_provenance"] = benchmark_provenance.to_dict()
    if benchmark_returns is not None:
        mc_save["summary"] = _add_benchmark_to_summary(
            mc_save["summary"], returns, benchmark_returns,
            commission=bench_commission, slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
            benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
            benchmark_data=benchmark,
        )
    with open(mc_path, "w") as f:
        json.dump(mc_save, f, indent=2, default=str)
    print(f"\nMonte Carlo results saved to: {mc_path}")

    # Generate tear sheet with Monte Carlo analysis rendered as a section
    mc_equity = (1 + returns).cumprod() * args.initial_capital
    mc_base_results = {
        "equity_curve": mc_equity,
        "returns": returns,
"config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission,
                "benchmark_slippage": getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage,
                "benchmark_expense_ratio": bench_expense_ratio,
            },
        }
    if benchmark_returns is not None:
        mc_base_results["benchmark"] = benchmark_returns
    mc_base_metrics = calculate_metrics(mc_base_results)
    if dsr is not None:
        mc_base_metrics["deflated_sharpe"] = dsr
    if pit_results is not None:
        mc_base_results["point_in_time_validation"] = pit_results
    generate_tear_sheet(
        mc_base_results, mc_base_metrics, args.output,
        symbol=args.symbol,
        strategy_name=f"{args.strategy}_monte_carlo",
        analysis_results={"monte_carlo": mc_results},
    )
    print(f"Tear sheet saved to: {args.output}/tear_sheet.html")

    return 0


def run_out_of_sample_validation(args) -> int:
    """Run out-of-sample validation from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        print(f"Loading benchmark data from {', '.join(args.benchmark)}...")
        benchmark = []
        benchmark_provenance = []
        for bench_file in args.benchmark:
            b, prov = _load_benchmark(bench_file, total_return_benchmark)
            benchmark.append(b)
            benchmark_provenance.append(prov)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running out-of-sample validation with {args.strategy}...")
    print(f"  Train/Val/Test split: {args.train_frac:.1%}/{args.val_frac:.1%}/{args.test_frac:.1%}")
    print(f"  Validation method: {args.validation_method}")
    print(f"  Selection criterion: {args.selection_criterion}")

    results = out_of_sample_validation(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        test_frac=args.test_frac,
        validation_method=args.validation_method,
        walk_forward_train_months=args.wf_train_months,
        walk_forward_test_months=args.wf_test_months,
        walk_forward_step_months=args.wf_step_months,
        cpcv_n_splits=args.cpcv_n_splits,
        cpcv_test_size=args.cpcv_test_size,
        cpcv_purge_size=args.cpcv_purge_size,
        cpcv_embargo_size=args.cpcv_embargo_size,
        selection_criterion=args.selection_criterion,
        initial_capital=args.initial_capital,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
    )

    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Print results
    split_info = results["train_val_test_split"]
    print(f"\nTrain/Validation/Test Split:")
    print(f"  Train: {split_info['train_start'].date()} to {split_info['train_end'].date()} ({split_info['train_size']} bars)")
    print(f"  Val:   {split_info['val_start'].date()} to {split_info['val_end'].date()} ({split_info['val_size']} bars)")
    print(f"  Test:  {split_info['test_start'].date()} to {split_info['test_end'].date()} ({split_info['test_size']} bars)")

    selected = results["selected_params"]
    if selected is None:
        print("No valid parameters selected from validation phase.")
        return 1

    print(f"\nSelected Parameters: {selected}")

    val_perf = results["validation_performance"]
    print(f"\nValidation Performance:")
    print(f"  Total Return: {val_perf['val_total_return']:.2%}")
    print(f"  Sharpe Ratio: {val_perf['val_sharpe']:.4f}")

    test_perf = results["test_performance"]
    print(f"\nTest Performance (HELD-OUT, never used in selection):")
    print(f"  Total Return: {test_perf['test_total_return']:.2%}")
    print(f"  Sharpe Ratio: {test_perf['test_sharpe']:.4f}")

    summary = results["summary"]
    dsr = summary.get("deflated_sharpe")
    if dsr is not None:
        print(
            f"\nDeflated Sharpe Ratio (test): {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

    if results["test_benchmark"]:
        print(
            f"\nTest Benchmark Comparison:"
        )
        if isinstance(results["test_benchmark"], list):
            # Multiple benchmarks
            for i, bench_result in enumerate(results["test_benchmark"]):
                if bench_result is not None:
                    print(
                        f"  Benchmark {i+1}:"
                    )
                    print(
                        f"    Correlation: {bench_result.get('correlation_with_benchmark', 'N/A'):.4f}"
                    )
                    print(
                        f"    Alpha (annualized): {bench_result.get('alpha', 'N/A'):.2%}"
                    )
                    print(
                        f"    Beta: {bench_result.get('beta', 'N/A'):.4f}"
                    )
                    # Show both original and corrected p-values if available
                    if 'alpha_pvalue_original' in bench_result:
                        print(
                            f"    Alpha p-value (original): {bench_result['alpha_pvalue_original'] if bench_result['alpha_pvalue_original'] is None else f'{bench_result['alpha_pvalue_original']:.4f}'}"
                        )
                        print(
                            f"    Alpha p-value (corrected): {bench_result['alpha_pvalue'] if bench_result['alpha_pvalue'] is None else f'{bench_result['alpha_pvalue']:.4f}'}"
                        )
                    else:
                        pval = bench_result.get("alpha_pvalue")
                        print(
                            f"    Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                        )
                    rs = bench_result.get("r_squared")
                    print(
                        f"    R-squared: {rs if rs is None else f'{rs:.4f}'}"
                    )
                else:
                    print(f"  Benchmark {i+1}: Failed to compute")
        else:
            # Single benchmark (backward compatibility)
            print(
                f"  Correlation: {results['test_benchmark'].get('correlation_with_benchmark', 'N/A'):.4f}"
            )
            print(
                f"  Alpha (annualized): {results['test_benchmark'].get('alpha', 'N/A'):.2%}"
            )
            print(
                f"  Beta: {results['test_benchmark'].get('beta', 'N/A'):.4f}"
            )
            pval = results["test_benchmark"].get("alpha_pvalue")
            print(
                f"  Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
            )
            rs = results["test_benchmark"].get("r_squared")
            print(
                f"  R-squared: {rs if rs is None else f'{rs:.4f}'}"
            )

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "out_of_sample_summary.json"
    summary_data = {
        "summary": results["summary"],
        "train_val_test_split": results["train_val_test_split"],
        "selected_params": results["selected_params"],
        "validation_performance": results["validation_performance"],
        "test_performance": {
            "test_total_return": results["test_performance"]["test_total_return"],
            "test_sharpe": results["test_performance"]["test_sharpe"],
            "test_volatility": results["test_performance"]["test_volatility"],
            "test_n_periods": results["test_performance"]["test_n_periods"],
        },
        "test_benchmark": results["test_benchmark"],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "train_frac": args.train_frac,
            "val_frac": args.val_frac,
            "test_frac": args.test_frac,
            "validation_method": args.validation_method,
            "selection_criterion": args.selection_criterion,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            # Validation method specific config
            "wf_train_months": args.wf_train_months,
            "wf_test_months": args.wf_test_months,
            "wf_step_months": args.wf_step_months,
            "cpcv_n_splits": args.cpcv_n_splits,
            "cpcv_test_size": args.cpcv_test_size,
            "cpcv_purge_size": args.cpcv_purge_size,
            "cpcv_embargo_size": args.cpcv_embargo_size,
        },
    }
    if pit_results is not None:
        summary_data["point_in_time_validation"] = pit_results
    if benchmark_provenance is not None:
        # benchmark_provenance is a single DataProvenance when one benchmark
        # was supplied, or a list of them when multiple benchmarks were
        # supplied (multi-benchmark alpha multiple-testing correction).
        if isinstance(benchmark_provenance, list):
            summary_data["benchmark_provenance"] = [
                prov.to_dict() for prov in benchmark_provenance
            ]
        else:
            summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"\nOut-of-sample summary saved to: {summary_path}")

    # Generate full report if test returns available
    if len(results["test_performance"]["test_returns"]) > 0:
        equity = (1 + results["test_performance"]["test_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["test_performance"]["test_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
                "benchmark_expense_ratio": bench_expense_ratio,
                "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            },
        }
        if results["test_benchmark"] is not None:
            # The report/tear sheet path is single-benchmark by design, so
            # use the first benchmark when multiple were supplied. The
            # multi-benchmark comparison (with Deflated Alpha correction)
            # is already surfaced in the printed summary and the JSON.
            bench_for_report = benchmark
            if isinstance(benchmark, list) and len(benchmark) > 0:
                bench_for_report = benchmark[0]
            bench_returns = _compute_benchmark_returns(
                bench_for_report,
                results["test_performance"]["test_returns"],
                total_return_benchmark,
            )
            if bench_returns is not None:
                report_results["benchmark"] = bench_returns
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        metrics = calculate_metrics(report_results)
        if dsr is not None:
            metrics["deflated_sharpe"] = dsr
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_out_of_sample")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_out_of_sample",
            analysis_results={"out_of_sample": results},
        )
        print(f"Detailed report saved to: {args.output}/")

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
    common_parser.add_argument("--impact-coefficient", type=float, default=0.0, help="Market impact coefficient (position_notional/ADV * coefficient). 0 to disable.")
    common_parser.add_argument("--adv-window", type=int, default=20, help="Rolling window for Average Daily Volume calculation")
    common_parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3%% per year)")
    common_parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2%% per year)")
    common_parser.add_argument("--output", type=str, default="results", help="Output directory")
    common_parser.add_argument("--param-grid", type=str, required=True, help="Parameter grid as JSON string")
    common_parser.add_argument("--validate-point-in-time", action="store_true", help="Run point-in-time validation on the loaded data (temporal ordering, duplicate timestamps, stale-data warnings)")
    common_parser.add_argument("--point-in-time-strict", action="store_true", help="Abort when point-in-time validation finds violations (default: warn only)")
    common_parser.add_argument("--benchmark", type=str, nargs="+", default=None, help="Path to benchmark OHLCV file(s) (e.g. SPY QQQ) for buy-and-hold baseline comparison (alpha/beta, correlation)")
    common_parser.add_argument("--total-return-benchmark", action="store_true", help="Compute benchmark returns using total return (dividends + price) when dividend/adj_close data is available, instead of price-only returns (applies to all benchmarks)")
    common_parser.add_argument("--benchmark-commission", type=float, default=None, help="Commission per trade for benchmark (as decimal). Defaults to strategy commission if not specified (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-slippage", type=float, default=None, help="Slippage per trade for benchmark (as decimal). Defaults to strategy slippage if not specified (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-expense-ratio", type=float, default=None, help="Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%). Defaults to 0 (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-cost-is-periodic", action="store_true", help="If set, apply benchmark trading costs (commission+slippage) as periodic deductions each period instead of as a round-trip cost on total return (applies to all benchmarks).")
    common_parser.add_argument("--adjust-splits", action="store_true", help="Adjust prices for stock splits using the splits column if present.")

    # Walk-forward analysis
    wf_parser = subparsers.add_parser("walk-forward", parents=[common_parser], help="Run walk-forward analysis")
    wf_parser.add_argument("--train-months", type=int, default=12, help="Training window size in months")
    wf_parser.add_argument("--test-months", type=int, default=3, help="Testing window size in months")
    wf_parser.add_argument("--step-months", type=int, default=3, help="Step size between iterations in months")
    wf_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    wf_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the parameter search and OOS results")
    wf_parser.set_defaults(func=run_walk_forward)

    # Parameter optimization
    opt_parser = subparsers.add_parser("optimize", parents=[common_parser], help="Run parameter optimization")
    opt_parser.add_argument("--top-n", type=int, default=10, help="Number of top results to display")
    opt_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) for every parameter combination")
    opt_parser.set_defaults(func=run_parameter_optimization)

    # Monte Carlo simulation
    mc_parser = subparsers.add_parser("monte-carlo", parents=[common_parser], help="Run Monte Carlo simulation")
    mc_parser.add_argument("--n-simulations", type=int, default=2000, help="Number of simulations")
    mc_parser.add_argument("--confidence-levels", type=float, nargs="+", default=[0.90, 0.95, 0.99], help="Confidence levels")
    mc_parser.add_argument("--block-size", type=int, help="Block size for block bootstrap")
    mc_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    mc_parser.add_argument("--n-trials", type=int, default=None, help="Number of development trials (parameter configurations) tested; when set, report the Deflated Sharpe Ratio (multiple-testing correction) for the base backtest Sharpe. When a --param-grid is searched, the effective count is max(n_trials, number of grid combinations evaluated) so the internal search is never understated")
    mc_parser.set_defaults(func=run_monte_carlo)

    # CPCV analysis
    cpcv_parser = subparsers.add_parser("cpcv", parents=[common_parser], help="Run Combinatorially Purged Cross-Validation")
    cpcv_parser.add_argument("--n-splits", type=int, default=10, help="Number of sequential groups (folds)")
    cpcv_parser.add_argument("--test-size", type=float, default=0.1, help="Fraction of each group to use as test set")
    cpcv_parser.add_argument("--purge-size", type=float, default=0.0, help="Fraction of observations to purge from training around test set")
    cpcv_parser.add_argument("--embargo-size", type=float, default=0.0, help="Fraction of observations to embargo after test set")
    cpcv_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    cpcv_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the fold searches and OOS results")
    cpcv_parser.set_defaults(func=run_cpcv)

    # Out-of-sample validation
    oos_parser = subparsers.add_parser("out-of-sample", parents=[common_parser], help="Run rigorous out-of-sample validation with train/validation/test split")
    oos_parser.add_argument("--train-frac", type=float, default=0.6, help="Fraction of data for training (default 0.6)")
    oos_parser.add_argument("--val-frac", type=float, default=0.2, help="Fraction of data for validation (default 0.2)")
    oos_parser.add_argument("--test-frac", type=float, default=0.2, help="Fraction of data for testing (default 0.2)")
    oos_parser.add_argument("--validation-method", type=str, choices=["walk_forward", "cpcv"], default="walk_forward", help="Method for parameter selection on training data")
    oos_parser.add_argument("--selection-criterion", type=str, choices=["best_oos_sharpe", "most_stable", "best_avg_sharpe"], default="best_oos_sharpe", help="Criterion for selecting final parameters from validation results")
    oos_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    oos_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the test results")
    # Walk-forward specific args for validation phase
    oos_parser.add_argument("--wf-train-months", type=int, default=12, help="Training window size in months for walk-forward validation")
    oos_parser.add_argument("--wf-test-months", type=int, default=3, help="Testing window size in months for walk-forward validation")
    oos_parser.add_argument("--wf-step-months", type=int, default=3, help="Step size between walk-forward iterations")
    # CPCV specific args for validation phase
    oos_parser.add_argument("--cpcv-n-splits", type=int, default=10, help="Number of sequential groups for CPCV validation")
    oos_parser.add_argument("--cpcv-test-size", type=float, default=0.1, help="Fraction of each group to use as test set in CPCV")
    oos_parser.add_argument("--cpcv-purge-size", type=float, default=0.0, help="Fraction of observations to purge from training around test")
    oos_parser.add_argument("--cpcv-embargo-size", type=float, default=0.0, help="Fraction of observations to embargo after test set")
    oos_parser.set_defaults(func=run_out_of_sample_validation)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
