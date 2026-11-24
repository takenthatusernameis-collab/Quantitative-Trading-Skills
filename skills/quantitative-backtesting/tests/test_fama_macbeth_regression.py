#!/usr/bin/env python3
"""
Ground-truth tests for Fama-MacBeth cross-sectional regression utility.

Tests:
1. Data generated as returns = exposures @ true_lambda + noise recovers true_lambda
2. Single-factor reduces to closed-form beta = cov/var, lambda = cov/var
3. NaN/constant-column handling
4. Seeded reproducibility

Offline, deterministic synthetic inputs only; no network, no fixtures.
"""
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from factor_models import (
    fama_macbeth,
    fama_macbeth_single_factor,
    generate_fama_macbeth_test_data,
)


def test_recovery_of_true_lambda():
    """Synthetic data with known factor premia should recover true_lambda."""
    T, N, K = 200, 100, 3
    true_lambda = np.array([0.008, -0.004, 0.002])
    noise_scale = 0.005  # Small noise relative to signal

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, noise_scale=noise_scale, seed=42
    )

    result = fama_macbeth(returns, exposures, newey_west=False)

    # With large N and small noise, estimates should be close
    lambda_hat = result["lambda_hat"]
    assert result["n_periods"] == T

    # Check each factor
    for k in range(K):
        # Bias should be small relative to true value
        rel_error = abs(lambda_hat[k] - true_lambda[k]) / abs(true_lambda[k])
        assert rel_error < 0.15, f"Factor {k}: lambda_hat={lambda_hat[k]:.6f}, true={true_lambda[k]:.6f}, rel_error={rel_error:.2%}"

    # T-stats should be significant for non-zero factors
    t_stats = result["t_stats"]
    assert abs(t_stats[0]) > 3.0, f"Factor 0 t-stat too low: {t_stats[0]}"
    assert abs(t_stats[1]) > 3.0, f"Factor 1 t-stat too low: {t_stats[1]}"

    print("test_recovery_of_true_lambda PASSED")


def test_single_factor_closed_form():
    """Single-factor Fama-MacBeth should match closed-form beta = cov/var."""
    T, N = 150, 80
    true_lambda = 0.006
    noise_scale = 0.008

    # Generate single factor data
    rng = np.random.default_rng(123)
    exposures = rng.normal(0, 1.0, size=(T, N))
    returns = np.zeros((T, N))
    for t in range(T):
        returns[t] = exposures[t] * true_lambda + rng.normal(0, noise_scale, size=N)

    result = fama_macbeth_single_factor(returns, exposures, newey_west=False)

    # Compare per-period estimates
    lambda_t_fm = result["lambda_t"].ravel()
    lambda_t_cf = result["closed_form_lambda_t"]

    valid = np.isfinite(lambda_t_fm) & np.isfinite(lambda_t_cf)
    assert valid.sum() > T * 0.9, "Too many NaN periods"

    # They should match closely (numerical precision)
    # lstsq vs cov/var can have small numerical differences
    diff = np.abs(lambda_t_fm[valid] - lambda_t_cf[valid])
    max_diff = np.max(diff)
    assert max_diff < 1e-3, f"Closed-form mismatch: max diff = {max_diff}"

    # Time-series mean should be close to true lambda
    lambda_hat = result["lambda_hat"][0]
    rel_error = abs(lambda_hat - true_lambda) / abs(true_lambda)
    assert rel_error < 0.10, f"lambda_hat={lambda_hat:.6f}, true={true_lambda:.6f}"

    print("test_single_factor_closed_form PASSED")


def test_nan_handling():
    """NaN in returns or exposures should be handled gracefully (listwise deletion per period)."""
    T, N, K = 50, 30, 2
    true_lambda = np.array([0.005, -0.003])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=456
    )

    # Inject NaN randomly
    rng = np.random.default_rng(789)
    nan_mask_ret = rng.random((T, N)) < 0.05
    nan_mask_exp = rng.random((T, N, K)) < 0.05
    returns[nan_mask_ret] = np.nan
    exposures[nan_mask_exp] = np.nan

    result = fama_macbeth(returns, exposures, newey_west=False)

    # Should still produce estimates
    assert result["n_periods"] > 0
    assert np.all(np.isfinite(result["lambda_hat"])) or np.any(np.isfinite(result["lambda_hat"]))
    assert result["lambda_t"].shape == (T, K)
    assert result["residuals_t"].shape == (T, N)

    print("test_nan_handling PASSED")


def test_constant_column_handling():
    """Constant exposure columns should be dropped without crashing."""
    T, N, K = 40, 25, 3
    true_lambda = np.array([0.005, -0.003, 0.001])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=999
    )

    # Make factor 1 constant across assets for all periods
    exposures[:, :, 1] = 1.0

    result = fama_macbeth(returns, exposures, newey_west=False)

    # Should not crash; factor 1 should be NaN (dropped)
    assert result["n_periods"] == T
    assert np.isnan(result["lambda_hat"][1])
    assert np.isnan(result["t_stats"][1])
    assert np.isnan(result["se"][1])
    # Other factors should still be estimated
    assert np.isfinite(result["lambda_hat"][0])
    assert np.isfinite(result["lambda_hat"][2])

    print("test_constant_column_handling PASSED")


def test_seeded_reproducibility():
    """Identical inputs + identical seed (where applicable) -> bit-identical output."""
    T, N, K = 60, 40, 2
    true_lambda = np.array([0.004, -0.002])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=111
    )

    # Run twice with same seed (seed is reserved but passed through)
    result1 = fama_macbeth(returns, exposures, newey_west=True, seed=20261124)
    result2 = fama_macbeth(returns, exposures, newey_west=True, seed=20261124)

    # All numeric outputs should be identical
    for key in ["lambda_hat", "lambda_t", "t_stats", "se", "residuals_t"]:
        v1 = result1[key]
        v2 = result2[key]
        if isinstance(v1, np.ndarray):
            assert np.array_equal(v1, v2, equal_nan=True), f"Mismatch in {key}"
        else:
            assert v1 == v2, f"Mismatch in {key}"

    # Scalar fields
    assert result1["n_periods"] == result2["n_periods"]
    assert result1["n_assets_avg"] == result2["n_assets_avg"]
    assert result1["bandwidth"] == result2["bandwidth"]

    print("test_seeded_reproducibility PASSED")


def test_newey_west_vs_iid():
    """Newey-West SE should differ from i.i.d. SE when autocorrelation present."""
    T, N, K = 200, 50, 1
    true_lambda = 0.005

    # Generate data with autocorrelated factor returns
    rng = np.random.default_rng(222)
    exposures = rng.normal(0, 1.0, size=(T, N))

    # Create autocorrelated factor returns
    lambda_series = np.zeros(T)
    lambda_series[0] = true_lambda + rng.normal(0, 0.01)
    for t in range(1, T):
        lambda_series[t] = 0.5 * lambda_series[t-1] + true_lambda + rng.normal(0, 0.01)

    returns = np.zeros((T, N))
    for t in range(T):
        returns[t] = exposures[t] * lambda_series[t] + rng.normal(0, 0.01, size=N)

    result_nw = fama_macbeth(returns, exposures.reshape(T, N, 1), newey_west=True)
    result_iid = fama_macbeth(returns, exposures.reshape(T, N, 1), newey_west=False)

    se_nw = result_nw["se"][0]
    se_iid = result_iid["se"][0]

    # Newey-West should be larger due to positive autocorrelation
    assert se_nw > se_iid * 1.1, f"NW SE ({se_nw:.6f}) not > iid SE ({se_iid:.6f})"

    print("test_newey_west_vs_iid PASSED")


def test_insufficient_assets():
    """Periods with fewer assets than factors should produce NaN for that period."""
    T, N, K = 20, 4, 5  # N < K
    true_lambda = np.array([0.005, -0.003, 0.002, -0.001, 0.001])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=333
    )

    # min_periods=K ensures periods with N < K are filtered out
    result = fama_macbeth(returns, exposures, newey_west=False, min_periods=K)

    # All periods should be invalid
    assert result["n_periods"] == 0
    assert np.all(np.isnan(result["lambda_hat"]))
    assert np.all(np.isnan(result["lambda_t"]))

    print("test_insufficient_assets PASSED")


def test_min_periods_filter():
    """min_periods should filter out periods with too few valid assets."""
    T, N, K = 30, 20, 2
    true_lambda = np.array([0.005, -0.003])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=444
    )

    # Make first 5 periods have only 1 valid asset (less than K=2)
    returns[:5, 1:] = np.nan

    result = fama_macbeth(returns, exposures, newey_west=False, min_periods=2)

    # Should have T-5 valid periods
    assert result["n_periods"] == T - 5
    assert np.all(np.isnan(result["lambda_t"][:5]))
    assert np.all(np.isfinite(result["lambda_t"][5:]))

    print("test_min_periods_filter PASSED")


def test_output_structure():
    """Verify return dict has all expected keys and shapes."""
    T, N, K = 50, 30, 3
    true_lambda = np.array([0.005, -0.003, 0.001])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=555
    )

    result = fama_macbeth(returns, exposures, newey_west=True)

    expected_keys = {
        "lambda_hat", "lambda_t", "t_stats", "se",
        "n_periods", "n_assets_avg", "bandwidth", "residuals_t"
    }
    assert set(result.keys()) == expected_keys

    assert result["lambda_hat"].shape == (K,)
    assert result["lambda_t"].shape == (T, K)
    assert result["t_stats"].shape == (K,)
    assert result["se"].shape == (K,)
    assert result["residuals_t"].shape == (T, N)
    assert isinstance(result["n_periods"], int)
    assert isinstance(result["n_assets_avg"], float)
    assert isinstance(result["bandwidth"], (int, type(None)))

    print("test_output_structure PASSED")


def test_zero_variance_factor():
    """Factor with zero variance in a period should not crash."""
    T, N, K = 25, 15, 2
    true_lambda = np.array([0.005, 0.0])

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=666
    )

    # Make factor 0 zero variance in first period
    exposures[0, :, 0] = 0.5

    result = fama_macbeth(returns, exposures, newey_west=False)

    # Should not crash; first period factor 0 should be NaN
    assert np.isnan(result["lambda_t"][0, 0])
    # Other periods should be fine
    assert np.isfinite(result["lambda_t"][1, 0])

    print("test_zero_variance_factor PASSED")


if __name__ == "__main__":
    test_recovery_of_true_lambda()
    test_single_factor_closed_form()
    test_nan_handling()
    test_constant_column_handling()
    test_seeded_reproducibility()
    test_newey_west_vs_iid()
    test_insufficient_assets()
    test_min_periods_filter()
    test_output_structure()
    test_zero_variance_factor()
    print("\nALL TESTS PASSED")