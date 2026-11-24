#!/usr/bin/env python3
"""
Fama-MacBeth cross-sectional regression utility for factor-model capability.

This module provides a self-contained implementation of the Fama-MacBeth (1973)
two-step procedure for estimating factor risk premia from cross-sectional
regressions of asset returns on factor exposures.

Step 1 (per period): Cross-sectional OLS of asset returns on factor exposures
    r_t = X_t * lambda_t + eps_t

Step 2 (time series): Average the per-period factor returns and compute
t-statistics using Newey-West HAC standard errors.

References:
    Fama, E. F. & MacBeth, J. D. (1973). "Risk, Return, and Equilibrium:
    Empirical Tests." Journal of Political Economy, 81(3), 607-636.
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List, Tuple


def _ols_cross_section(returns: np.ndarray, exposures: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Single-period cross-sectional OLS: returns = exposures @ lambda + noise.

    Args:
        returns: (N,) array of asset returns for one period
        exposures: (N, K) array of factor exposures for one period

    Returns:
        lambda_hat: (K,) estimated factor returns for this period
        residuals: (N,) residuals from the regression
    """
    N, K = exposures.shape
    if N < K:
        # Underdetermined: return NaN
        return np.full(K, np.nan), np.full(N, np.nan)

    # Remove rows with NaN in returns or any exposure
    valid = np.isfinite(returns) & np.all(np.isfinite(exposures), axis=1)
    if valid.sum() < K:
        return np.full(K, np.nan), np.full(N, np.nan)

    y = returns[valid]
    X = exposures[valid]

    # Check for constant columns (drop them)
    X_std = X.std(axis=0)
    non_const = X_std > 1e-12
    if not np.any(non_const):
        return np.full(K, np.nan), np.full(N, np.nan)

    X_nc = X[:, non_const]
    try:
        # Solve using least squares for numerical stability
        beta_nc, residuals, rank, s = np.linalg.lstsq(X_nc, y, rcond=None)
        lambda_hat = np.full(K, np.nan)
        lambda_hat[non_const] = beta_nc
        resid = np.full(N, np.nan)
        resid[valid] = y - X_nc @ beta_nc
        return lambda_hat, resid
    except np.linalg.LinAlgError:
        return np.full(K, np.nan), np.full(N, np.nan)


def _newey_west_var(x: np.ndarray, bandwidth: Optional[int] = None) -> float:
    """
    Newey-West HAC long-run variance of a mean-zero series.

    Uses the Bartlett kernel with automatic bandwidth selection
    floor(4 * (T / 100) ** (2 / 9)) following Newey & West (1994).
    """
    x = np.asarray(x, dtype=float).ravel()
    x = x - x.mean()
    T = x.shape[0]
    if T < 2:
        return 0.0
    if bandwidth is None:
        bandwidth = int(np.floor(4.0 * (T / 100.0) ** (2.0 / 9.0)))
    bandwidth = max(0, min(int(bandwidth), T - 1))
    gamma0 = float(np.dot(x, x)) / T
    var = gamma0
    for lag in range(1, bandwidth + 1):
        w = 1.0 - lag / (bandwidth + 1.0)
        gamma = float(np.dot(x[lag:], x[:-lag])) / T
        var += 2.0 * w * gamma
    return max(var, 0.0)


def fama_macbeth(
    asset_returns: np.ndarray,
    factor_exposures: np.ndarray,
    newey_west: bool = True,
    bandwidth: Optional[int] = None,
    min_periods: int = 1,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fama-MacBeth two-step cross-sectional regression.

    Step 1: For each time period t, run cross-sectional OLS:
        r_{i,t} = sum_k X_{i,t,k} * lambda_{k,t} + eps_{i,t}

    Step 2: Time-series averages and t-statistics:
        lambda_k = mean_t(lambda_{k,t})
        t_k = sqrt(T) * lambda_k / se(lambda_k)

    Args:
        asset_returns: (T, N) array of asset returns. T = time periods, N = assets.
        factor_exposures: (T, N, K) array of factor exposures.
            K = number of factors.
        newey_west: If True, use Newey-West HAC standard errors for t-stats.
            If False, use simple i.i.d. standard errors.
        bandwidth: Manual bandwidth for Newey-West. If None, use automatic.
        min_periods: Minimum number of valid cross-sectional observations
            required per period (default 1, but practical minimum is K+1).
        seed: Random seed (reserved for future bootstrap extensions).

    Returns:
        Dict containing:
            - lambda_hat: (K,) time-series mean factor returns (risk premia)
            - lambda_t: (T, K) per-period factor returns
            - t_stats: (K,) t-statistics for each factor
            - se: (K,) standard errors
            - n_periods: number of valid time periods
            - n_assets_avg: average number of assets per period
            - bandwidth: bandwidth used (if newey_west=True)
            - residuals_t: (T, N) per-period residuals (NaN where not estimated)
    """
    T, N = asset_returns.shape
    _, N2, K = factor_exposures.shape
    if N != N2:
        raise ValueError(f"asset_returns shape {asset_returns.shape} incompatible with factor_exposures {factor_exposures.shape}")

    # Pre-allocate
    lambda_t = np.full((T, K), np.nan)
    residuals_t = np.full((T, N), np.nan)
    valid_periods = []

    for t in range(T):
        r_t = asset_returns[t]
        X_t = factor_exposures[t]
        # Count valid assets this period
        valid_assets = np.isfinite(r_t) & np.all(np.isfinite(X_t), axis=1)
        if valid_assets.sum() >= min_periods:
            lam, resid = _ols_cross_section(r_t, X_t)
            lambda_t[t] = lam
            residuals_t[t] = resid
            valid_periods.append(t)

    if not valid_periods:
        return {
            "lambda_hat": np.full(K, np.nan),
            "lambda_t": lambda_t,
            "t_stats": np.full(K, np.nan),
            "se": np.full(K, np.nan),
            "n_periods": 0,
            "n_assets_avg": 0.0,
            "bandwidth": bandwidth,
            "residuals_t": residuals_t,
        }

    valid_periods = np.array(valid_periods)
    lambda_valid = lambda_t[valid_periods]
    T_valid = len(valid_periods)

    # Time-series means (factor risk premia)
    # Handle per-factor all-NaN columns (e.g., constant exposure dropped)
    # to avoid RuntimeWarning from np.nanmean on empty slices
    all_nan_mask = np.all(np.isnan(lambda_valid), axis=0)
    lambda_hat = np.full(K, np.nan)
    if not np.all(all_nan_mask):
        # At least one factor has some finite values
        valid_cols = ~all_nan_mask
        lambda_hat[valid_cols] = np.nanmean(lambda_valid[:, valid_cols], axis=0)

    # Standard errors
    se = np.full(K, np.nan)
    t_stats = np.full(K, np.nan)

    for k in range(K):
        series = lambda_valid[:, k]
        finite_mask = np.isfinite(series)
        if finite_mask.sum() < 2:
            continue
        series_f = series[finite_mask]
        T_f = len(series_f)

        if newey_west:
            lrv = _newey_west_var(series_f, bandwidth)
            se[k] = np.sqrt(lrv / T_f) if T_f > 0 else np.nan
        else:
            # i.i.d. standard error
            se[k] = series_f.std(ddof=1) / np.sqrt(T_f) if T_f > 1 else np.nan

        if se[k] > 0 and np.isfinite(lambda_hat[k]):
            t_stats[k] = np.sqrt(T_f) * lambda_hat[k] / se[k]

    n_assets_avg = np.mean([np.sum(np.isfinite(asset_returns[t]) & np.all(np.isfinite(factor_exposures[t]), axis=1))
                            for t in valid_periods])

    return {
        "lambda_hat": lambda_hat,
        "lambda_t": lambda_t,
        "t_stats": t_stats,
        "se": se,
        "n_periods": T_valid,
        "n_assets_avg": float(n_assets_avg),
        "bandwidth": bandwidth if newey_west else None,
        "residuals_t": residuals_t,
    }


def fama_macbeth_single_factor(
    asset_returns: np.ndarray,
    factor_exposure: np.ndarray,
    newey_west: bool = True,
    bandwidth: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Specialized single-factor Fama-MacBeth with closed-form verification.

    When K=1, the cross-sectional OLS reduces to:
        beta_t = cov(r_t, X_t) / var(X_t)
        lambda_t = beta_t

    And the time-series mean lambda_hat should equal the average of these.

    Args:
        asset_returns: (T, N) array
        factor_exposure: (T, N) array (single factor)
        newey_west: Use Newey-West standard errors
        bandwidth: Manual bandwidth

    Returns:
        Same dict as fama_macbeth plus 'closed_form_lambda_t' for verification.
    """
    T, N = asset_returns.shape
    if factor_exposure.shape != (T, N):
        raise ValueError("factor_exposure must have shape (T, N)")

    # Reshape to 3D for the general function
    exposures_3d = factor_exposure.reshape(T, N, 1)
    result = fama_macbeth(asset_returns, exposures_3d, newey_west, bandwidth)

    # Compute closed-form single-factor betas for verification
    closed_form_lambda = np.full(T, np.nan)
    for t in range(T):
        r_t = asset_returns[t]
        x_t = factor_exposure[t]
        valid = np.isfinite(r_t) & np.isfinite(x_t)
        if valid.sum() >= 2:
            r_v = r_t[valid]
            x_v = x_t[valid]
            x_var = np.var(x_v, ddof=1)
            if x_var > 1e-12:
                cov = np.cov(r_v, x_v, ddof=1)[0, 1]
                closed_form_lambda[t] = cov / x_var

    result["closed_form_lambda_t"] = closed_form_lambda
    return result


def generate_fama_macbeth_test_data(
    T: int,
    N: int,
    K: int,
    true_lambda: np.ndarray,
    noise_scale: float = 0.01,
    exposure_scale: float = 1.0,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic panel data with known factor structure for testing.

    Returns:
        asset_returns: (T, N) generated as X @ true_lambda + noise
        factor_exposures: (T, N, K) random exposures
    """
    rng = np.random.default_rng(seed)
    # Generate random factor exposures
    factor_exposures = rng.normal(0, exposure_scale, size=(T, N, K))
    # Generate returns: X @ lambda + noise
    asset_returns = np.zeros((T, N))
    for t in range(T):
        asset_returns[t] = factor_exposures[t] @ true_lambda + rng.normal(0, noise_scale, size=N)
    return asset_returns, factor_exposures


if __name__ == "__main__":
    # Quick sanity check
    T, N, K = 100, 50, 3
    true_lambda = np.array([0.005, -0.003, 0.002])
    returns, exposures = generate_fama_macbeth_test_data(T, N, K, true_lambda, seed=123)
    result = fama_macbeth(returns, exposures)
    print("Estimated lambda:", result["lambda_hat"])
    print("True lambda:     ", true_lambda)
    print("T-stats:         ", result["t_stats"])
    print("SE:              ", result["se"])
    print("Valid periods:   ", result["n_periods"])
    print("OK")