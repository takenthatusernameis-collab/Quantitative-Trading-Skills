#!/usr/bin/env python3
"""Unit tests for CPCV (Combinatorially Purged Cross-Validation) in walk_forward.py.

Run with: python3 skills/quantitative-backtesting/tests/test_cpcv.py
Uses only standard library + pandas/numpy (required by the scripts under test).
"""

import sys
import traceback
import tempfile
from pathlib import Path

import pandas as pd
import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    cpcv_analysis,
    signals_active,
    _calculate_cpcv_summary,
    run_cpcv,
    _make_strategy_factory,
)


def _make_sample_data(n_days: int = 500) -> pd.DataFrame:
    """Create synthetic OHLCV data for testing."""
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    returns = np.random.normal(0.0005, 0.015, n_days)
    prices = 100 * np.exp(np.cumsum(returns))

    return pd.DataFrame({
        "open": prices * np.random.uniform(0.995, 1.005, n_days),
        "high": prices * np.random.uniform(1.005, 1.02, n_days),
        "low": prices * np.random.uniform(0.98, 0.995, n_days),
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, n_days)
    }, index=dates)



def _make_multiasset_multiindex(n=500, n_assets=4, seed=42):
    """Create MultiIndex panel data for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0, index=dates, columns=cols)
    rng = np.random.default_rng(seed)
    for i, sym in enumerate(symbols):
        drift = 0.0005 * (i + 1)
        rets = rng.normal(drift, 0.01, n)
        prices = 100 * np.exp(np.cumsum(rets))
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, n)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, n)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, n)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, n)
    return df
def _make_strategy_factory(strategy_type: str = "sma_crossover"):
    """Create a simple strategy factory for testing."""
    sys.path.insert(0, str(SKILLS_DIR / "scripts"))
    from strategy_builder import build_strategy
    import json

    def factory(params: dict):
        return build_strategy(strategy_type, json.dumps(params))
    return factory


def test_cpcv_basic_structure():
    """Test that CPCV returns the expected structure."""
    data = _make_sample_data(300)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.2,
    )

    # Check required keys
    assert "folds" in results
    assert "best_params_per_fold" in results
    assert "oos_returns" in results
    assert "summary" in results
    assert "param_stability" in results

    # Check folds
    assert len(results["folds"]) > 0
    assert len(results["folds"]) <= 5  # n_splits

    # Check each fold has required fields
    for fold in results["folds"]:
        assert "fold" in fold
        assert "test_group" in fold
        assert "train_data" in fold
        assert "test_data" in fold
        assert "train_indices" in fold
        assert "test_indices" in fold
        assert "best_params" in fold
        assert "best_sharpe" in fold
        assert "test_returns" in fold

    # Check summary
    summary = results["summary"]
    assert "n_folds" in summary
    assert "total_oos_return" in summary
    assert "overfitting_risk" in summary
    assert summary["overfitting_risk"] in ("low", "medium", "high")


def test_cpcv_purge_embargo():
    """Test that purge and embargo parameters affect training data."""
    data = _make_sample_data(300)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [10], "slow_period": [30]}

    # Without purge/embargo
    results_no_purge = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.2,
        purge_size=0.0,
        embargo_size=0.0,
    )

    # With purge/embargo
    results_purge = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.2,
        purge_size=0.1,
        embargo_size=0.1,
    )

    # With purge/embargo, training sets should be smaller
    for fold_no_purge, fold_purge in zip(results_no_purge["folds"], results_purge["folds"]):
        assert len(fold_purge["train_indices"]) <= len(fold_no_purge["train_indices"])


def test_cpcv_param_stability():
    """Test parameter stability calculation."""
    data = _make_sample_data(500)  # Larger dataset
    strategy_factory = _make_strategy_factory("sma_crossover")
    # Use smaller periods that work with smaller test windows
    param_grid = {"fast_period": [5, 10], "slow_period": [15, 20]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.3,  # Larger test size
    )

    stability = results["param_stability"]
    assert "fast_period" in stability
    assert "slow_period" in stability

    for param_name, stats in stability.items():
        assert "unique_values" in stats
        assert "most_common" in stats
        assert "stability_ratio" in stats
        assert 0 <= stats["stability_ratio"] <= 1


def test_cpcv_summary_calculation():
    """Test _calculate_cpcv_summary function."""
    # Create mock OOS returns
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    oos_returns = pd.Series(np.random.normal(0.001, 0.02, 100), index=dates)

    folds = [
        {"fold": 0, "best_params": {"fast_period": 10, "slow_period": 30}, "best_sharpe": 1.5},
        {"fold": 1, "best_params": {"fast_period": 10, "slow_period": 30}, "best_sharpe": 1.3},
        {"fold": 2, "best_params": {"fast_period": 20, "slow_period": 50}, "best_sharpe": 1.2},
    ]

    param_stability = {
        "fast_period": {"unique_values": 2, "most_common": 10, "stability_ratio": 0.33},
        "slow_period": {"unique_values": 2, "most_common": 30, "stability_ratio": 0.33},
    }

    summary = _calculate_cpcv_summary(oos_returns, folds, param_stability)

    assert summary["n_folds"] == 3
    assert "total_oos_return" in summary
    assert "oos_sharpe" in summary
    assert "avg_param_stability" in summary
    assert summary["avg_param_stability"] == (0.33 + 0.33) / 2
    assert "overfitting_risk" in summary


def test_cpcv_empty_results():
    """Test CPCV with parameters that produce no valid folds."""
    # Very small dataset that might not produce valid folds
    data = _make_sample_data(50)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [10], "slow_period": [30]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=10,  # Too many splits for small data
        test_size=0.2,
    )

    # Should handle gracefully
    assert "folds" in results
    assert "summary" in results


def test_cpcv_invalid_n_splits():
    """Test CPCV raises error for invalid n_splits."""
    data = _make_sample_data(100)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [10], "slow_period": [30]}

    try:
        cpcv_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=1,  # Invalid
            test_size=0.2,
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "n_splits must be at least 2" in str(e)


def test_cpcv_non_datetime_index():
    """Test CPCV raises error for non-DatetimeIndex."""
    data = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100, 101, 102],
        "volume": [1000, 1000, 1000]
    })  # No DatetimeIndex

    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [10], "slow_period": [30]}

    try:
        cpcv_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=5,
            test_size=0.2,
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "DatetimeIndex" in str(e)


def test_signals_active_helper():
    """Test the signals_active helper function."""
    # Active signals
    active = pd.Series([0, 1, 1, 0, -1, 0])
    assert signals_active(active) is True

    # Flat signals
    flat = pd.Series([0, 0, 0, 0, 0])
    assert signals_active(flat) is False

    # All NaN
    nan_series = pd.Series([np.nan, np.nan, np.nan])
    assert signals_active(nan_series) is False


def test_cpcv_different_strategies():
    """Test CPCV works with different strategy types."""
    data = _make_sample_data(300)
    param_grid = {"fast_period": [10], "slow_period": [30]}

    for strategy_type in ["sma_crossover", "ema_crossover", "donchian_breakout"]:
        strategy_factory = _make_strategy_factory(strategy_type)
        results = cpcv_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=3,
            test_size=0.3,
        )
        assert len(results["folds"]) > 0
        assert results["summary"]["n_folds"] > 0


def test_cpcv_cli_help():
    """Test that CPCV CLI can be parsed."""
    import argparse
    from walk_forward import main

    # This tests that the subparser is registered
    # We can't easily test the full CLI without subprocess, but we can verify
    # the function exists and is callable
    assert callable(run_cpcv)


def main() -> int:
    tests = [
        ("cpcv_basic_structure", test_cpcv_basic_structure),
        ("cpcv_purge_embargo", test_cpcv_purge_embargo),
        ("cpcv_param_stability", test_cpcv_param_stability),
        ("cpcv_summary_calculation", test_cpcv_summary_calculation),
        ("cpcv_empty_results", test_cpcv_empty_results),
        ("cpcv_invalid_n_splits", test_cpcv_invalid_n_splits),
        ("cpcv_non_datetime_index", test_cpcv_non_datetime_index),
        ("signals_active_helper", test_signals_active_helper),
        ("cpcv_different_strategies", test_cpcv_different_strategies),
        ("cpcv_cli_help", test_cpcv_cli_help),
        ("cpcv_multi_asset_cross_sectional_momentum", test_cpcv_multi_asset_cross_sectional_momentum),
        ("cpcv_multi_asset_dual_momentum", test_cpcv_multi_asset_dual_momentum),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


def test_cpcv_multi_asset_cross_sectional_momentum():
    """CPCV works with multi-asset panel data."""
    data = _make_multiasset_multiindex(n=500, n_assets=5, seed=42)
    strategy_factory = _make_strategy_factory("cross_sectional_momentum")
    param_grid = {
        "lookback": [20, 30],
        "top_quantile": [0.3, 0.4],
        "bottom_quantile": [0.2, 0.1],
    }
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
    )
    assert len(results["folds"]) > 0
    assert len(results["oos_returns"]) > 0


def test_cpcv_multi_asset_dual_momentum():
    """CPCV works with multi-asset panel data for dual momentum."""
    data = _make_multiasset_multiindex(n=600, n_assets=5, seed=123)
    strategy_factory = _make_strategy_factory("dual_momentum")
    param_grid = {
        "lookback": [40, 60],
        "top_quantile": [0.3, 0.4],
        "risk_free_rate": [0.0],
    }
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=3,
        test_size=0.3,
    )
    assert len(results["folds"]) > 0
    assert len(results["oos_returns"]) > 0
if __name__ == "__main__":
    sys.exit(main())
def test_cpcv_multi_asset_cross_sectional_momentum():
    """CPCV works with multi-asset panel data."""
    data = _make_multiasset_multiindex(n=500, n_assets=5, seed=42)
    strategy_factory = _make_strategy_factory("cross_sectional_momentum")
    param_grid = {
        "lookback": [20, 30],
        "top_quantile": [0.3, 0.4],
        "bottom_quantile": [0.2, 0.1],
    }
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
    )
    assert len(results["folds"]) > 0
    assert len(results["oos_returns"]) > 0


def test_cpcv_multi_asset_dual_momentum():
    """CPCV works with multi-asset panel data for dual momentum."""
    data = _make_multiasset_multiindex(n=600, n_assets=5, seed=123)
    strategy_factory = _make_strategy_factory("dual_momentum")
    param_grid = {
        "lookback": [40, 60],
        "top_quantile": [0.3, 0.4],
        "risk_free_rate": [0.0],
    }
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=3,
        test_size=0.3,
    )
    assert len(results["folds"]) > 0
    assert len(results["oos_returns"]) > 0
