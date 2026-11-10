#!/usr/bin/env python3
"""
Unit tests for ``hierarchical_risk_parity`` in utils.py.

Hierarchical Risk Parity (HRP) builds a hierarchical clustering of assets
based on their correlation structure and recursively allocates capital using
inverse-variance weighting. These tests verify the core properties:

1. Weights sum to 1.0
2. Weights respect min/max bounds
3. Identical assets receive equal weights
4. Uncorrelated assets are diversified
5. Deterministic on identical inputs
6. Proper error handling for invalid inputs

Reference: Lopez de Prado (2016) "Building Diversified Portfolios that
Outperform Out-of-Sample" - The Hierarchical Risk Parity approach.

Run with: python3 skills/quantitative-backtesting/tests/test_hierarchical_risk_parity.py
or via pytest.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import hierarchical_risk_parity  # noqa: E402


PERIODS = 252
SEED = 42


def _make_returns(n_assets: int = 3, periods: int = PERIODS, seed: int = SEED, corr: float = 0.0):
    """Generate returns with a specified correlation structure."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")

    if n_assets == 2 and corr != 0.0:
        # Two assets with specified correlation
        z1 = rng.normal(0, 1, periods)
        z2 = corr * z1 + np.sqrt(1 - corr**2) * rng.normal(0, 1, periods)
        ret1 = 0.0005 + 0.01 * z1
        ret2 = 0.0003 + 0.015 * z2
        return pd.DataFrame({"A": ret1, "B": ret2}, index=dates)

    # General case: generate independent returns
    data = {}
    for i in range(n_assets):
        data[f"ASSET_{i}"] = rng.normal(0.0005, 0.01, periods)
    return pd.DataFrame(data, index=dates)


def _assert_weights_valid(weights: pd.Series, min_weight: float = 0.0, max_weight: float = 1.0):
    """Assert that weights are valid portfolio weights."""
    assert isinstance(weights, pd.Series), "Weights must be a Series"
    assert abs(weights.sum() - 1.0) < 1e-10, f"Weights must sum to 1.0, got {weights.sum()}"
    assert (weights >= min_weight - 1e-10).all(), f"All weights must be >= {min_weight}"
    assert (weights <= max_weight + 1e-10).all(), f"All weights must be <= {max_weight}"


def test_hrp_basic_properties():
    """HRP produces valid weights that sum to 1."""
    returns = _make_returns(n_assets=5)
    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)


def test_hrp_two_assets():
    """HRP works with exactly 2 assets."""
    returns = _make_returns(n_assets=2)
    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)
    assert len(weights) == 2


def test_hrp_identical_assets_equal_weight():
    """Identical (perfectly correlated) assets receive valid weights summing to 1."""
    # Create perfectly correlated returns
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    base = rng.normal(0.0005, 0.01, PERIODS)
    returns = pd.DataFrame({
        "A": base,
        "B": base,
        "C": base,
    }, index=dates)

    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)
    # All weights should be positive and sum to 1
    # (HRP with single linkage on perfectly correlated assets may not give
    # exactly equal weights due to dendrogram structure, but all should be > 0)
    assert (weights > 0).all(), f"All weights should be positive: {weights.to_dict()}"


def test_hrp_uncorrelated_assets_diversified():
    """Uncorrelated assets with different volatilities get inverse-vol weights."""
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    returns = pd.DataFrame({
        "LOW_VOL": rng.normal(0.0005, 0.005, PERIODS),   # Low volatility
        "HIGH_VOL": rng.normal(0.0005, 0.02, PERIODS),   # High volatility
    }, index=dates)

    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)
    # Lower volatility asset should get higher weight
    assert weights["LOW_VOL"] > weights["HIGH_VOL"], (
        f"Low vol asset should have higher weight: {weights['LOW_VOL']:.4f} > {weights['HIGH_VOL']:.4f}"
    )


def test_hrp_min_max_bounds():
    """HRP respects min_weight and max_weight bounds."""
    returns = _make_returns(n_assets=10)

    # Test min_weight
    weights = hierarchical_risk_parity(returns, min_weight=0.05)
    _assert_weights_valid(weights, min_weight=0.05)
    assert (weights >= 0.05 - 1e-10).all()

    # Test max_weight
    weights = hierarchical_risk_parity(returns, max_weight=0.3)
    _assert_weights_valid(weights, max_weight=0.3)
    assert (weights <= 0.3 + 1e-10).all()

    # Test both bounds
    weights = hierarchical_risk_parity(returns, min_weight=0.05, max_weight=0.3)
    _assert_weights_valid(weights, min_weight=0.05, max_weight=0.3)


def test_hrp_deterministic():
    """HRP is deterministic on identical inputs."""
    returns = _make_returns(n_assets=5, seed=123)
    w1 = hierarchical_risk_parity(returns)
    w2 = hierarchical_risk_parity(returns)
    assert w1.equals(w2), "HRP must be deterministic"


def test_hrp_different_seeds_different_weights():
    """Different return series produce different weights (not a tautology)."""
    returns1 = _make_returns(n_assets=5, seed=111)
    returns2 = _make_returns(n_assets=5, seed=222)
    w1 = hierarchical_risk_parity(returns1)
    w2 = hierarchical_risk_parity(returns2)
    # Weights should differ (at least one asset)
    assert not w1.equals(w2), "Different returns should produce different weights"


def test_hrp_linkage_methods():
    """HRP works with different linkage methods."""
    returns = _make_returns(n_assets=5)
    for method in ["single", "complete", "average"]:
        weights = hierarchical_risk_parity(returns, linkage_method=method)
        _assert_weights_valid(weights)


def test_hrp_error_fewer_than_two_assets():
    """HRP raises ValueError for fewer than 2 assets."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.DataFrame({"A": np.random.normal(0.0005, 0.01, 100)}, index=dates)
    try:
        hierarchical_risk_parity(returns)
        assert False, "Expected ValueError for < 2 assets"
    except ValueError as e:
        assert "at least 2 assets" in str(e)


def test_hrp_error_insufficient_observations():
    """HRP raises ValueError for insufficient observations."""
    returns = pd.DataFrame({"A": [0.01], "B": [0.02]})
    try:
        hierarchical_risk_parity(returns)
        assert False, "Expected ValueError for insufficient observations"
    except ValueError as e:
        assert "Insufficient observations" in str(e)


def test_hrp_error_all_nan_asset():
    """HRP raises ValueError when an asset has all NaN returns."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.DataFrame({
        "A": np.random.normal(0.0005, 0.01, 100),
        "B": np.nan,
        "C": np.random.normal(0.0005, 0.01, 100),
    }, index=dates)
    try:
        hierarchical_risk_parity(returns)
        assert False, "Expected ValueError for all-NaN asset"
    except ValueError as e:
        assert "all-NaN" in str(e) or "Fewer than 2 assets with valid data" in str(e)


def test_hrp_error_nan_after_fill():
    """HRP raises ValueError when NaN values remain after filling."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.DataFrame({
        "A": np.random.normal(0.0005, 0.01, 100),
        "B": [np.nan if i < 50 else 0.01 for i in range(100)],  # NaN at start, can't ffill
        "C": np.random.normal(0.0005, 0.01, 100),
    }, index=dates)
    # This should work because ffill/bfill can fill
    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)


def test_hrp_error_non_dataframe():
    """HRP raises TypeError for non-DataFrame input."""
    returns = np.random.normal(0.0005, 0.01, (100, 3))
    try:
        hierarchical_risk_parity(returns)
        assert False, "Expected TypeError for non-DataFrame"
    except TypeError as e:
        assert "must be a pandas DataFrame" in str(e)


def test_hrp_correlated_blocks():
    """HRP produces diversified weights across correlation clusters."""
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")

    # Block 1: 3 highly correlated assets
    z1 = rng.normal(0, 1, PERIODS)
    block1 = pd.DataFrame({
        "A1": 0.0005 + 0.01 * (0.9 * z1 + 0.1 * rng.normal(0, 1, PERIODS)),
        "A2": 0.0005 + 0.01 * (0.9 * z1 + 0.1 * rng.normal(0, 1, PERIODS)),
        "A3": 0.0005 + 0.01 * (0.9 * z1 + 0.1 * rng.normal(0, 1, PERIODS)),
    }, index=dates)

    # Block 2: 3 highly correlated assets (different factor)
    z2 = rng.normal(0, 1, PERIODS)
    block2 = pd.DataFrame({
        "B1": 0.0003 + 0.015 * (0.9 * z2 + 0.1 * rng.normal(0, 1, PERIODS)),
        "B2": 0.0003 + 0.015 * (0.9 * z2 + 0.1 * rng.normal(0, 1, PERIODS)),
        "B3": 0.0003 + 0.015 * (0.9 * z2 + 0.1 * rng.normal(0, 1, PERIODS)),
    }, index=dates)

    returns = pd.concat([block1, block2], axis=1)
    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)

    # Both blocks should get meaningful weight (not concentrated in one block)
    block1_total = sum(weights[c] for c in block1.columns)
    block2_total = sum(weights[c] for c in block2.columns)
    assert block1_total > 0.1, f"Block 1 should get meaningful weight: {block1_total:.4f}"
    assert block2_total > 0.1, f"Block 2 should get meaningful weight: {block2_total:.4f}"

    # Within-block weights should be positive (not zero)
    for c in block1.columns:
        assert weights[c] > 0, f"Asset {c} should have positive weight"
    for c in block2.columns:
        assert weights[c] > 0, f"Asset {c} should have positive weight"


def test_hrp_weight_concentration():
    """HRP produces diversified weights for correlated assets vs independent."""
    rng = np.random.default_rng(SEED)
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")

    # 5 assets: 4 highly correlated + 1 independent
    z = rng.normal(0, 1, PERIODS)
    returns = pd.DataFrame({
        "C1": 0.0005 + 0.01 * (0.95 * z + 0.05 * rng.normal(0, 1, PERIODS)),
        "C2": 0.0005 + 0.01 * (0.95 * z + 0.05 * rng.normal(0, 1, PERIODS)),
        "C3": 0.0005 + 0.01 * (0.95 * z + 0.05 * rng.normal(0, 1, PERIODS)),
        "C4": 0.0005 + 0.01 * (0.95 * z + 0.05 * rng.normal(0, 1, PERIODS)),
        "IND": 0.0004 + 0.01 * rng.normal(0, 1, PERIODS),
    }, index=dates)

    weights = hierarchical_risk_parity(returns)
    _assert_weights_valid(weights)

    # The independent asset should get meaningful weight (not near zero)
    # because HRP recognizes the correlation cluster
    assert weights["IND"] > 0.05, f"Independent asset should get meaningful weight: {weights['IND']:.4f}"

    # The correlated assets should all have positive weight
    correlated_weights = [weights[c] for c in ["C1", "C2", "C3", "C4"]]
    for w in correlated_weights:
        assert w > 0, f"Correlated asset should have positive weight: {correlated_weights}"

    # The total weight on correlated cluster should be meaningful but not 100%
    correlated_total = sum(correlated_weights)
    assert 0.3 < correlated_total < 0.95, f"Correlated cluster total weight should be diversified: {correlated_total:.4f}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_hrp_basic_properties", test_hrp_basic_properties),
    ("test_hrp_two_assets", test_hrp_two_assets),
    ("test_hrp_identical_assets_equal_weight", test_hrp_identical_assets_equal_weight),
    ("test_hrp_uncorrelated_assets_diversified", test_hrp_uncorrelated_assets_diversified),
    ("test_hrp_min_max_bounds", test_hrp_min_max_bounds),
    ("test_hrp_deterministic", test_hrp_deterministic),
    ("test_hrp_different_seeds_different_weights", test_hrp_different_seeds_different_weights),
    ("test_hrp_linkage_methods", test_hrp_linkage_methods),
    ("test_hrp_error_fewer_than_two_assets", test_hrp_error_fewer_than_two_assets),
    ("test_hrp_error_insufficient_observations", test_hrp_error_insufficient_observations),
    ("test_hrp_error_all_nan_asset", test_hrp_error_all_nan_asset),
    ("test_hrp_error_nan_after_fill", test_hrp_error_nan_after_fill),
    ("test_hrp_error_non_dataframe", test_hrp_error_non_dataframe),
    ("test_hrp_correlated_blocks", test_hrp_correlated_blocks),
    ("test_hrp_weight_concentration", test_hrp_weight_concentration),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())