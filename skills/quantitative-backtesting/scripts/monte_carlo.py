#!/usr/bin/env python3
"""
Monte Carlo simulation for strategy return robustness.

Resamples strategy returns (with optional block bootstrapping to preserve
autocorrelation) to generate synthetic equity curves and compute the
distribution of key performance metrics.

This module is standalone: it depends only on pandas/numpy, so it can be
imported directly (`from monte_carlo import monte_carlo_simulation`) without
pulling in the walk-forward orchestration code.

Automatic block length selection for the stationary bootstrap follows
Politis & White (2004) "Automatic Block-Length Selection for the
Dependent Bootstrap" and Patton, Politis & White (2009) "Correction to
Automatic Block-Length Selection for the Dependent Bootstrap".
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Union


def _annualization_factor(index: pd.Index) -> float:
    """Estimate periods per year from DatetimeIndex."""
    if not isinstance(index, pd.DatetimeIndex):
        return 252
    try:
        freq = pd.infer_freq(index)
        if freq is None:
            return 252
        # Normalize to the lowercase base alias (pandas 3.x returns e.g.
        # "h", "min", "ms", "ME", "QE-DEC"). Match on the full base alias
        # rather than freq[0]: "min" (minute), "M"/"ME" (month), and "ms"
        # (millisecond) all start with "m", so first-char matching collides.
        base = freq.lower().split("-")[0]
        freq_map = {
            "b": 252, "d": 365, "w": 52, "me": 12, "ms": 12,
            "qe": 4, "ye": 1, "h": int(252 * 6.5),
            "min": int(252 * 6.5 * 60),
        }
        return freq_map.get(base, 252)
    except Exception:
        return 252


def estimate_optimal_block_size(
    returns: pd.Series,
    max_lag: Optional[int] = None,
    method: str = "politis_white_2004",
) -> int:
    """
    Estimate optimal block size for stationary bootstrap.

    Implements automatic block length selection for the dependent bootstrap
    following Politis & White (2004) "Automatic Block-Length Selection for
    the Dependent Bootstrap" and Patton, Politis & White (2009) correction.

    The optimal block length b* minimizes the mean squared error of the
    bootstrap variance estimator. For a stationary process with autocorrelation
    structure, the estimator is:

        b* = (2 * q * n)^(1/3)

    where q is the sum of squared autocorrelations (the "spectral density
    at zero" estimator) and n is the sample size.

    Args:
        returns: Series of returns (or any stationary time series)
        max_lag: Maximum lag for autocorrelation estimation (default: min(10*n^(1/4), n-1))
        method: "politis_white_2004" (default) or "simple_ar1" for AR(1) approximation

    Returns:
        Optimal block size as integer (minimum 2, maximum n//2)

    References:
        - Politis & White (2004) Econometric Reviews 23(1): 53-70
        - Patton, Politis & White (2009) Econometric Reviews 28(4): 372-375
    """
    returns = returns.dropna()
    n = len(returns)
    if n < 4:
        return 2

    if max_lag is None:
        # Rule of thumb from Politis & White: max_lag ~ n^(1/4)
        max_lag = min(int(10 * n ** 0.25), n - 1)
    max_lag = max(1, min(max_lag, n - 1))

    # Compute sample autocorrelations
    mean_ret = returns.mean()
    var_ret = returns.var(ddof=1)
    if var_ret <= 0:
        return 2

    acf = np.zeros(max_lag + 1)
    acf[0] = 1.0
    for k in range(1, max_lag + 1):
        if k < n:
            acf[k] = np.corrcoef(returns[:-k], returns[k:])[0, 1]
            if np.isnan(acf[k]):
                acf[k] = 0.0
        else:
            acf[k] = 0.0

    if method == "simple_ar1":
        # AR(1) approximation: b* = (2 * rho / (1 - rho)^2)^(1/3) * n^(1/3)
        rho1 = acf[1]
        if rho1 <= 0:
            return 2
        b_opt = (2 * rho1 / (1 - rho1) ** 2) ** (1 / 3) * n ** (1 / 3)
    else:
        # Politis & White (2004): q = sum_{k=1}^{max_lag} k * acf(k)^2
        # (using Bartlett kernel weights; the original paper uses flat-top kernel
        # but Bartlett is simpler and the correction in Patton et al. 2009 addresses bias)
        q = 0.0
        for k in range(1, max_lag + 1):
            q += k * acf[k] ** 2
        # If q is zero or negative (no autocorrelation), use minimum block size
        if q <= 0:
            return 2
        b_opt = (2 * q * n) ** (1 / 3)

    # Clamp to reasonable bounds
    b_opt = int(np.ceil(b_opt))
    return max(2, min(b_opt, n // 2))


def monte_carlo_simulation(
    base_returns: pd.Series,
    n_simulations: int = 2000,
    confidence_levels: List[float] = None,
    block_size: Union[int, str, None] = None,
    seed: Optional[int] = None,
    **kwargs,
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
        block_size: If int, use stationary block bootstrap with fixed block size.
                    If "auto", estimate optimal block size using Politis & White (2004).
                    If None (default), use simple i.i.d. resampling.

    Returns:
        Dictionary with:
            - 'simulated_equity_curves': List of simulated equity curves (DataFrame)
            - 'metric_distributions': Dict of metric -> array of simulated values
            - 'confidence_intervals': Dict of metric -> {level: (lower, upper)}
            - 'probability_of_ruin': Fraction of sims where equity < initial * threshold
            - 'summary': Summary statistics of metric distributions
            - 'block_size_used': The block size used (int or None)
    """
    if confidence_levels is None:
        confidence_levels = [0.90, 0.95, 0.99]

    if len(base_returns) < 2:
        raise ValueError("Need at least 2 return observations for Monte Carlo")

    base_returns = base_returns.dropna()
    n_obs = len(base_returns)
    ann_factor = _annualization_factor(base_returns.index)

    # Seeded RNG makes repeated simulations identical (reproducible sweep
    # artifacts and reports). When no seed is provided, fall back to the
    # legacy global numpy RNG.
    rng = np.random.default_rng(seed) if seed is not None else None

    # Handle automatic block size selection
    block_size_used = None
    if isinstance(block_size, str) and block_size.lower() == "auto":
        block_size_used = estimate_optimal_block_size(base_returns)
    elif isinstance(block_size, int) and block_size > 1:
        block_size_used = block_size
    else:
        block_size_used = None

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
        if block_size_used is not None and block_size_used > 1:
            if block_size_used >= n_obs:
                # Block larger than series - fall back to i.i.d. bootstrap
                sim_returns = base_returns.sample(n=n_obs, replace=True).values
                sim_returns = pd.Series(sim_returns, index=base_returns.index)
            else:
                # Stationary block bootstrap (Politis & Romano, 1994)
                # Blocks have geometrically distributed lengths with mean = block_size
                # Circular wrap-around ensures stationarity
                p_new_block = 1.0 / block_size_used
                sim_returns = np.empty(n_obs)
                returns_array = base_returns.values

                # Random starting position
                pos = int(rng.integers(0, n_obs)) if rng is not None else int(np.random.randint(0, n_obs))

                for i in range(n_obs):
                    sim_returns[i] = returns_array[pos]
                    # Decide whether to start a new block
                    draw = rng.random() if rng is not None else np.random.random()
                    if draw < p_new_block:
                        pos = int(rng.integers(0, n_obs)) if rng is not None else int(np.random.randint(0, n_obs))
                    else:
                        pos = (pos + 1) % n_obs  # Continue sequentially with wrap
                sim_returns = pd.Series(sim_returns, index=base_returns.index)
        else:
            # Simple i.i.d. bootstrap
            if rng is not None:
                sim_returns = base_returns.values[rng.integers(0, n_obs, size=n_obs)]
            else:
                sim_returns = base_returns.sample(n=n_obs, replace=True).values
            sim_returns = pd.Series(sim_returns, index=base_returns.index)

        # Build equity curve
        equity = (1 + sim_returns).cumprod()

        # Calculate metrics
        total_ret = equity.iloc[-1] - 1
        growth = 1 + total_ret
        if growth <= 0 or not np.isfinite(growth):
            # The simulated equity has been wiped out (growth <= 0): the
            # geometric annualization `growth ** (ann_factor / n_obs)` is not
            # a real number. Represent the bust as a total loss (-100%
            # annualized) rather than NaN, so the metric distribution,
            # summary statistics, and confidence intervals stay finite and
            # interpretable. The actual cumulative loss is preserved in
            # `total_return` (which may be below -1 for negative equity).
            ann_ret = -1.0
        else:
            ann_ret = growth ** (ann_factor / n_obs) - 1
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
        "block_size_used": block_size_used,
    }