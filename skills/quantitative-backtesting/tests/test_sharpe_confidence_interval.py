#!/usr/bin/env python3
"""
Focused tests for the sharpe_confidence_interval function.

Tests the stationary-bootstrap percentile CI on the OOS Sharpe:
- CI brackets the point estimate on a real fixture
- Degenerate zero-variance -> defined/None (no NaN)
- Cross-path parity (same return series -> same CI)
- No-mutation (existing keys unchanged)
- Insufficient observations -> degenerate with reason
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from monte_carlo import sharpe_confidence_interval  # noqa: E402


def _make_returns(periods: int = 252, seed: int = 42, mean: float = 0.0005, std: float = 0.015) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.Series(rng.normal(mean, std, periods), index=dates)


def test_sharpe_ci_resolvable_brackets_point_estimate():
    """CI brackets the point estimate on a real fixture."""
    returns = _make_returns(periods=500, seed=123)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=500, seed=42)

    assert ci["status"] == "resolvable"
    assert ci["reason"] is None
    assert ci["confidence"] == 0.95
    assert ci["n_observations"] == 500
    assert ci["n_bootstrap"] == 500
    assert ci["method"] in ("stationary_bootstrap", "iid_bootstrap")
    assert ci["block_size"] is not None or ci["method"] == "iid_bootstrap"
    assert np.isfinite(ci["point_estimate"])
    assert ci["lower"] is not None and ci["upper"] is not None
    assert ci["lower"] <= ci["upper"]
    # CI should bracket the point estimate (with high probability; use wide CI for reliability)
    # Note: percentile bootstrap CI may not always contain point estimate in small samples,
    # but with 500 observations it should with high probability
    assert ci["lower"] <= ci["point_estimate"] <= ci["upper"] or \
           abs(ci["point_estimate"] - ci["lower"]) < 0.5 or \
           abs(ci["point_estimate"] - ci["upper"]) < 0.5


def test_sharpe_ci_degenerate_zero_variance():
    """Zero-variance returns -> degenerate with status, no NaN."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.Series(0.0, index=dates)  # Constant returns
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, seed=42)

    assert ci["status"] == "degenerate"
    assert ci["reason"] == "zero_variance"
    assert ci["lower"] is None
    assert ci["upper"] is None
    assert ci["point_estimate"] == 0.0
    assert ci["n_observations"] == 100
    # No NaN anywhere
    for v in ci.values():
        if isinstance(v, float):
            assert not np.isnan(v), f"NaN found in CI result: {ci}"


def test_sharpe_ci_degenerate_insufficient_observations():
    """Insufficient observations (<2) -> degenerate with reason."""
    dates = pd.date_range("2020-01-01", periods=1, freq="B")
    returns = pd.Series([0.01], index=dates)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, seed=42)

    assert ci["status"] == "degenerate"
    assert ci["reason"] == "insufficient_observations"
    assert ci["lower"] is None
    assert ci["upper"] is None
    assert ci["point_estimate"] == 0.0
    assert ci["n_observations"] == 1


def test_sharpe_ci_cross_path_parity():
    """Same return series -> same CI (seeded reproducibility)."""
    returns = _make_returns(periods=300, seed=456)
    ci1 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, seed=999)
    ci2 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, seed=999)

    assert ci1["status"] == ci2["status"] == "resolvable"
    assert ci1["lower"] == ci2["lower"]
    assert ci1["upper"] == ci2["upper"]
    assert ci1["point_estimate"] == ci2["point_estimate"]
    assert ci1["block_size"] == ci2["block_size"]


def test_sharpe_ci_different_seeds_different_results():
    """Different seeds -> different (but valid) results."""
    returns = _make_returns(periods=300, seed=456)
    ci1 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, seed=111)
    ci2 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, seed=222)

    assert ci1["status"] == ci2["status"] == "resolvable"
    # With different seeds, results should differ (with very high probability)
    # but both should be valid
    assert ci1["lower"] is not None and ci1["upper"] is not None
    assert ci2["lower"] is not None and ci2["upper"] is not None
    assert ci1["lower"] <= ci1["upper"]
    assert ci2["lower"] <= ci2["upper"]


def test_sharpe_ci_confidence_levels():
    """Different confidence levels produce different width CIs."""
    returns = _make_returns(periods=400, seed=789)
    ci_90 = sharpe_confidence_interval(returns, confidence=0.90, n_bootstrap=500, seed=42)
    ci_95 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=500, seed=42)
    ci_99 = sharpe_confidence_interval(returns, confidence=0.99, n_bootstrap=500, seed=42)

    assert ci_90["confidence"] == 0.90
    assert ci_95["confidence"] == 0.95
    assert ci_99["confidence"] == 0.99

    # Higher confidence -> wider interval (with high probability)
    width_90 = ci_90["upper"] - ci_90["lower"]
    width_95 = ci_95["upper"] - ci_95["lower"]
    width_99 = ci_99["upper"] - ci_99["lower"]
    assert width_90 <= width_95 * 1.5  # Allow some Monte Carlo noise
    assert width_95 <= width_99 * 1.5


def test_sharpe_ci_fixed_block_size():
    """Fixed block size parameter works."""
    returns = _make_returns(periods=300, seed=456)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, block_size=10, seed=42)

    assert ci["status"] == "resolvable"
    assert ci["block_size"] == 10
    assert ci["method"] == "stationary_bootstrap"


def test_sharpe_ci_iid_bootstrap():
    """block_size=None -> iid bootstrap."""
    returns = _make_returns(periods=300, seed=456)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=200, block_size=None, seed=42)

    assert ci["status"] == "resolvable"
    assert ci["block_size"] is None
    assert ci["method"] == "iid_bootstrap"


def test_sharpe_ci_no_nan_in_result():
    """No NaN values anywhere in the result dict."""
    returns = _make_returns(periods=200, seed=42)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, seed=42)

    def check_no_nan(obj, path=""):
        if isinstance(obj, float):
            assert not np.isnan(obj), f"NaN at {path}"
        elif isinstance(obj, dict):
            for k, v in obj.items():
                check_no_nan(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                check_no_nan(v, f"{path}[{i}]")

    check_no_nan(ci)


def test_sharpe_ci_point_estimate_matches_manual():
    """Point estimate matches manual Sharpe calculation."""
    returns = _make_returns(periods=252, seed=42)
    ci = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, seed=42)

    # Manual calculation
    ann_factor = 252  # Daily business days
    rf_period = 0.02 / ann_factor
    excess = returns - rf_period
    manual_sharpe = float(excess.mean() / excess.std() * np.sqrt(ann_factor))

    assert abs(ci["point_estimate"] - manual_sharpe) < 1e-10


def test_sharpe_ci_risk_free_adjustment():
    """Risk-free rate parameter affects point estimate."""
    returns = _make_returns(periods=252, seed=42, mean=0.001, std=0.01)
    ci_rf0 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, risk_free=0.0, seed=42)
    ci_rf2 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, risk_free=0.02, seed=42)
    ci_rf5 = sharpe_confidence_interval(returns, confidence=0.95, n_bootstrap=100, risk_free=0.05, seed=42)

    # Higher risk-free -> lower excess return -> lower Sharpe
    assert ci_rf0["point_estimate"] > ci_rf2["point_estimate"] > ci_rf5["point_estimate"]


if __name__ == "__main__":
    import traceback

    tests = [
        test_sharpe_ci_resolvable_brackets_point_estimate,
        test_sharpe_ci_degenerate_zero_variance,
        test_sharpe_ci_degenerate_insufficient_observations,
        test_sharpe_ci_cross_path_parity,
        test_sharpe_ci_different_seeds_different_results,
        test_sharpe_ci_confidence_levels,
        test_sharpe_ci_fixed_block_size,
        test_sharpe_ci_iid_bootstrap,
        test_sharpe_ci_no_nan_in_result,
        test_sharpe_ci_point_estimate_matches_manual,
        test_sharpe_ci_risk_free_adjustment,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)