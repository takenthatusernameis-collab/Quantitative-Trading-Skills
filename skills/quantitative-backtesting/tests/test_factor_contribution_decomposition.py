#!/usr/bin/env python3
"""
Ground-truth tests for Fama-MacBeth factor contribution decomposition.

r_{i,t} = sum_k X_{i,t,k} * lambda_k + eps_{i,t}

Descriptive risk attribution only -- no profitability claim. All inputs are
synthetic with known factor premia; outputs are verified against the ground
truth. Offline, deterministic, no network, no fixtures.
"""
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from factor_models import (
    fama_macbeth,
    factor_contribution_decomposition,
    generate_fama_macbeth_test_data,
)


def test_decomposition_recovers_signal_and_noise():
    """With known premia, the residual should be ≈ noise and factors should explain most variance."""
    T, N, K = 120, 60, 3
    true_lambda = np.array([0.006, -0.004, 0.002])
    noise_scale = 0.005

    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, noise_scale=noise_scale, seed=11
    )
    result = fama_macbeth(returns, exposures, newey_west=False)
    dec = factor_contribution_decomposition(returns, exposures, result["lambda_hat"])

    # Residual should be small (≈ noise) and factor contribution should dominate.
    assert dec["residual_std"] < noise_scale * 2.5, (
        f"residual_std {dec['residual_std']:.5f} not ≈ noise {noise_scale}"
    )
    assert dec["explained_variance_ratio"] > 0.5, (
        f"factors explain only {dec['explained_variance_ratio']:.2%} of variance"
    )
    # With nonzero premia the factor contribution must not be degenerate.
    assert float(np.std(dec["factor_contrib"])) > 1e-6, "factor contribution is degenerate"

    print("test_decomposition_recovers_signal_and_noise PASSED")


def test_zero_premia_means_no_factor_contribution():
    """lambda_hat = 0 => factor_contrib = 0, residual == returns, explained ≈ 0."""
    T, N, K = 40, 30, 2
    true_lambda = np.array([0.005, -0.003])
    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=22
    )
    zero_lambda = np.zeros(K)
    dec = factor_contribution_decomposition(returns, exposures, zero_lambda)

    assert np.all(dec["factor_contrib"] == 0.0)
    assert np.all(dec["residual"] == returns)
    assert dec["residual_std"] == float(np.std(returns))
    assert dec["explained_variance_ratio"] == 0.0

    print("test_zero_premia_means_no_factor_contribution PASSED")


def test_output_structure():
    """Return dict has expected keys and shapes."""
    T, N, K = 50, 25, 3
    true_lambda = np.array([0.004, -0.002, 0.001])
    returns, exposures = generate_fama_macbeth_test_data(
        T, N, K, true_lambda, seed=33
    )
    result = fama_macbeth(returns, exposures, newey_west=False)
    dec = factor_contribution_decomposition(returns, exposures, result["lambda_hat"])

    expected_keys = {
        "factor_contrib",
        "residual",
        "factor_contrib_mean",
        "residual_std",
        "explained_variance_ratio",
    }
    assert set(dec.keys()) == expected_keys
    assert dec["factor_contrib"].shape == (T, N)
    assert dec["residual"].shape == (T, N)
    assert dec["factor_contrib_mean"].shape == (K,)
    assert isinstance(dec["residual_std"], float)
    assert isinstance(dec["explained_variance_ratio"], float)

    print("test_output_structure PASSED")


if __name__ == "__main__":
    test_decomposition_recovers_signal_and_noise()
    test_zero_premia_means_no_factor_contribution()
    test_output_structure()
    print("\nALL TESTS PASSED")
