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
from scripts.data_loader import load_data, validate_data, validate_point_in_time
from scripts.performance import calculate_metrics, generate_report
from scripts.reporting import generate_tear_sheet
from monte_carlo import monte_carlo_simulation


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
                data, signals, commission, slippage,
                impact_coefficient, adv_window, borrow_cost, funding_cost
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
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

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
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

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
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
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
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

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
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
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
        if "deflated_sharpe" in r:
            dsr = r["deflated_sharpe"]
            print(
                f"      Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
                f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
                f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
            )

    # Attach PIT results to top-level saved results if present
    if 'pit_results' in locals() or True:
        pass

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # When saving param opt, also attach pit if we have it? But run_parameter_optimization might not have loaded with pit yet
    results_path = output_dir / "parameter_optimization.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {results_path}")

    return 0


def run_monte_carlo(args) -> int:
    """Run Monte Carlo simulation from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", False),
        pit_strict=getattr(args, "point_in_time_strict", False),
    )

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
            "point_in_time_validation": pit_results,
        },
    }
    if pit_results is not None:
        mc_save["point_in_time_validation"] = pit_results
    if dsr is not None:
        mc_save["deflated_sharpe"] = dsr
        mc_save["config"]["n_trials"] = effective_n_trials
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
        },
    }
    mc_base_metrics = calculate_metrics(mc_base_results)
    if dsr is not None:
        mc_base_metrics["deflated_sharpe"] = dsr
    generate_tear_sheet(
        mc_base_results, mc_base_metrics, args.output,
        symbol=args.symbol,
        strategy_name=f"{args.strategy}_monte_carlo",
        analysis_results={"monte_carlo": mc_results},
    )
    print(f"Tear sheet saved to: {args.output}/tear_sheet.html")

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
    common_parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3% per year)")
    common_parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2% per year)")
    common_parser.add_argument("--output", type=str, default="results", help="Output directory")
    common_parser.add_argument("--param-grid", type=str, required=True, help="Parameter grid as JSON string")
    common_parser.add_argument("--validate-point-in-time", action="store_true", help="Run point-in-time validation on the loaded data (temporal ordering, duplicate timestamps, stale-data warnings)")
    common_parser.add_argument("--point-in-time-strict", action="store_true", help="Abort when point-in-time validation finds violations (default: warn only)")

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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
