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
    deflated_sharpe_ratio,
    _calculate_cpcv_summary,
    run_cpcv,
    _make_strategy_factory,
    _calculate_strategy_returns,
    _annualization_factor,
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


def _make_multiasset_dict(n=500, n_assets=4, seed=42):
    """Create dict of symbol -> OHLCV DataFrame for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    rng = np.random.default_rng(seed)
    data_dict = {}
    for i, sym in enumerate(symbols):
        drift = 0.0005 * (i + 1)
        rets = rng.normal(drift, 0.01, n)
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame({
            "open": prices * rng.uniform(0.995, 1.005, n),
            "high": prices * rng.uniform(1.005, 1.02, n),
            "low": prices * rng.uniform(0.98, 0.995, n),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, n),
        }, index=dates)
    return data_dict
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


def test_cpcv_aggregate_deflation_uses_pooled_trial_sharpes():
    """The aggregate CPCV DSR must use pooled cross-fold trial Sharpes.

    Mirrors the walk-forward test: the aggregate DSR on combined OOS returns
    must use the cross-sectional SR* estimator from pooled fold trial Sharpes.
    """
    # Use more data and larger test_size so test windows can accommodate
    # the slow_period lookback (max 50). 2000 periods with 8 splits,
    # test_size=0.2 gives ~50 test observations per fold.
    data = _make_sample_data(2000)
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}
    strategy_factory = _make_strategy_factory("sma_crossover")

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=8,
        test_size=0.2,
        purge_size=0.0,
        embargo_size=0.0,
        apply_deflation=True,
    )

    # Verify we have valid OOS returns and a deflated_sharpe key
    assert "deflated_sharpe" in results["summary"], (
        f"Expected deflated_sharpe in summary, got keys: {results['summary'].keys()}"
    )
    assert len(results["oos_returns"]) > 0, "Expected non-empty OOS returns"

    agg_dsr = results["summary"]["deflated_sharpe"]

    # Collect pooled trial Sharpes by re-running grid search on each fold's
    # training data.
    from itertools import product

    pooled_trial_sharpes = []
    for fold in results["folds"]:
        if fold.get("best_params") is None:
            continue
        train_data = fold["train_data"]
        test_data = fold["test_data"]
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        for combo in product(*param_values):
            params = dict(zip(param_names, combo))
            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)
                if not signals_active(test_signals):
                    continue
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, 0.0002, 0.0001
                )
                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                    if np.isfinite(sharpe):
                        pooled_trial_sharpes.append(float(sharpe))
            except Exception:
                continue

    oos_returns = results["oos_returns"]
    oos_sharpe = results["summary"].get("oos_sharpe", 0.0)
    n_trials = max(len(pooled_trial_sharpes), 1)
    expected = deflated_sharpe_ratio(
        sharpe_ratio=oos_sharpe,
        returns=oos_returns,
        n_trials=n_trials,
        trial_sharpes=pooled_trial_sharpes if pooled_trial_sharpes else None,
    )

    for key in (
        "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
        "n_trials", "n_observations", "skewness", "kurtosis",
    ):
        assert abs(agg_dsr[key] - expected[key]) < 1e-12, (
            f"Mismatch on {key}: got {agg_dsr[key]}, expected {expected[key]}"
        )

    # Also verify the cross-sectional estimator differs from i.i.d. null
    iid_null = deflated_sharpe_ratio(
        sharpe_ratio=oos_sharpe, returns=oos_returns, n_trials=n_trials
    )
    assert abs(agg_dsr["expected_max_sharpe"] - iid_null["expected_max_sharpe"]) > 1e-9


def test_cpcv_deflation():
    """CPCV with apply_deflation reports per-fold and aggregate DSR."""
    # 500 days / 4 splits / test_size=0.2 -> 25-bar test windows,
    # long enough for the slow_period=20 signals to be active.
    data = _make_sample_data(500)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [5, 10], "slow_period": [15, 20]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        apply_deflation=True,
    )

    # Aggregate DSR on the combined OOS returns
    assert len(results["oos_returns"]) > 0
    assert "deflated_sharpe" in results["summary"]
    agg = results["summary"]["deflated_sharpe"]
    assert 0.0 <= agg["deflated_sharpe_ratio"] <= 1.0
    assert agg["n_trials"] >= len(results["folds"])

    # Per-fold DSR for the in-sample selection
    n_with_params = 0
    for fold in results["folds"]:
        if fold.get("best_params") is not None:
            n_with_params += 1
            assert "deflated_sharpe" in fold
            d = fold["deflated_sharpe"]
            assert 0.0 <= d["deflated_sharpe_ratio"] <= 1.0
            assert d["n_trials"] >= 1
    assert n_with_params > 0

    # Backward compatible: default run has no DSR keys
    default = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
    )
    assert "deflated_sharpe" not in default["summary"]
    assert all("deflated_sharpe" not in f for f in default["folds"])


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


def test_cpcv_multi_asset_dict_cross_sectional_momentum():
    """CPCV works with dict panel data.

    Regression coverage: dict input previously produced zero
    folds because fold counts were derived from len(data) (the
    number of symbols, not bars); dict data is now normalized
    to a MultiIndex panel before splitting.
    """
    data = _make_multiasset_dict(n=500, n_assets=5, seed=42)
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


def test_cpcv_multi_asset_dict_dual_momentum():
    """CPCV works with dict panel data for dual momentum."""
    data = _make_multiasset_dict(n=600, n_assets=5, seed=123)
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


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function.

    Regression guard for a defect where a test function was defined after
    the ``if __name__ == "__main__"`` block (and therefore unreachable at
    runtime) yet omitted from the registry, so the suite reported a lower
    count than the number of tests actually defined. A test defined but
    never registered is dead code: it cannot fail, so it provides no
    coverage of the feature it targets.

    The check is structural: every callable named ``test_*`` at module
    scope must appear in ``TEST_REGISTRY``, and every registry entry must
    be a real module-level function. No test is executed here.
    """
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}. A test outside the "
        "runner is dead code and provides no coverage."
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    # Labels must be unique so the runner cannot silently skip a test
    # (duplicate labels would overwrite each other in a name->fn map).
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


def test_cpcv_surfaces_capacity_in_summary():
    """CPCV surfaces market-impact capacity in the summary when impact is
    enabled and estimable; keeps None when impact is disabled (backward
    compatible). Mirrors the walk-forward capacity surfacing."""
    data = _make_sample_data(600)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [5, 10], "slow_period": [15, 20]}

    res_on = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        impact_coefficient=0.5,
    )
    assert "capacity" in res_on["summary"], (
        f"Expected capacity key in summary, got: {list(res_on['summary'].keys())}"
    )
    assert res_on["summary"]["capacity"] is not None
    assert res_on["summary"]["capacity"] > 0

    res_off = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        impact_coefficient=0.0,
    )
    assert res_off["summary"].get("capacity") is None


def test_cpcv_surfaces_capacity_per_fold():
    """CPCV surfaces a per-fold market-impact capacity estimate so capacity
    degradation across folds/regimes is observable, mirroring the per-period
    capacity that the walk-forward path records.

    The key is present on every fold (capacity is a property of the fold's
    market data) and is None when impact is disabled (backward compatible).
    """
    data = _make_sample_data(600)
    strategy_factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [5, 10], "slow_period": [15, 20]}

    res_on = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        impact_coefficient=0.5,
    )
    folds = res_on["folds"]
    assert len(folds) > 0
    evaluated = 0
    for f in folds:
        assert "capacity" in f, (
            f"Missing per-fold capacity key on fold {f.get('fold')}"
        )
        cap = f["capacity"]
        if len(f.get("test_returns", pd.Series(dtype=float))) > 0:
            evaluated += 1
            assert cap is not None, (
                f"Expected a capacity estimate on evaluated fold {f.get('fold')}"
            )
            assert cap > 0
    assert evaluated > 0, "Expected at least one evaluated fold"

    res_off = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        impact_coefficient=0.0,
    )
    for f in res_off["folds"]:
        assert "capacity" in f
        assert f["capacity"] is None


def test_cpcv_multi_asset_panel_capacity_does_not_raise():
    """A multi-asset panel must not break the capacity path.

    Regression guard: `estimate_capacity` used to call `float()` on the
    per-asset `close`/`volume` slices of a MultiIndex panel, which raised
    `TypeError: float() argument must be ... not 'Series'` and aborted the
    whole CPCV run (including the summary-level capacity estimate) whenever
    market impact was enabled on panel data.
    """
    data = _make_multiasset_multiindex(n=400, n_assets=3, seed=42)
    strategy_factory = _make_strategy_factory("cross_sectional_momentum")
    param_grid = {"lookback": [10, 20], "top_quantile": [0.4], "bottom_quantile": [0.2]}

    res = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=3,
        test_size=0.2,
        impact_coefficient=0.5,
        validate_pit=False,
    )
    assert res["summary"]["capacity"] is not None
    assert res["summary"]["capacity"] > 0
    for f in res["folds"]:
        assert "capacity" in f
        assert f["capacity"] is not None and f["capacity"] > 0


def test_cpcv_no_active_position_reports_none_and_zero_folds():
    """When every parameter set is skipped (no fold takes a position),
    total_oos_return is None -- not 0.0 -- and folds_with_position is 0, so
    "no position was ever taken" is distinguishable from "traded and lost
    everything". Symmetric quantiles make cross_sectional_momentum's net
    exposure exactly zero for every combo, so every fold is skipped."""
    data = _make_multiasset_multiindex(n=504, n_assets=5, seed=42)
    strategy_factory = _make_strategy_factory("cross_sectional_momentum")

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid={"lookback": [15, 20, 30]},
        n_splits=4,
        test_size=0.2,
    )

    summary = results["summary"]
    assert summary["n_folds"] == 4
    assert summary["folds_with_position"] == 0
    assert summary["total_oos_return"] is None
    assert len(results["oos_returns"]) == 0
    assert all(f.get("best_params") is None for f in results["folds"])


def test_cpcv_normal_run_keeps_current_numbers():
    """A run that selects parameters keeps its current numbers; only the
    no-position case changes (0.0 -> None). Deterministic on the seeded panel."""
    data = _make_multiasset_multiindex(n=504, n_assets=5, seed=42)
    strategy_factory = _make_strategy_factory("cross_sectional_momentum")

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid={"lookback": [15, 20, 30], "top_quantile": [0.4], "bottom_quantile": [0.2]},
        n_splits=4,
        test_size=0.2,
    )

    summary = results["summary"]
    assert summary["n_folds"] == 4
    assert summary["folds_with_position"] == 4
    assert summary["total_oos_return"] == 0.005399536978800246


TEST_REGISTRY = [
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
    ("cpcv_deflation", test_cpcv_deflation),
    ("cpcv_aggregate_deflation_uses_pooled_trial_sharpes", test_cpcv_aggregate_deflation_uses_pooled_trial_sharpes),
    ("cpcv_multi_asset_cross_sectional_momentum", test_cpcv_multi_asset_cross_sectional_momentum),
    ("cpcv_multi_asset_dual_momentum", test_cpcv_multi_asset_dual_momentum),
    ("cpcv_multi_asset_dict_cross_sectional_momentum", test_cpcv_multi_asset_dict_cross_sectional_momentum),
    ("cpcv_multi_asset_dict_dual_momentum", test_cpcv_multi_asset_dict_dual_momentum),
    ("cpcv_surfaces_capacity_in_summary", test_cpcv_surfaces_capacity_in_summary),
    ("cpcv_surfaces_capacity_per_fold", test_cpcv_surfaces_capacity_per_fold),
    ("cpcv_multi_asset_panel_capacity_does_not_raise", test_cpcv_multi_asset_panel_capacity_does_not_raise),
    ("cpcv_no_active_position_reports_none_and_zero_folds", test_cpcv_no_active_position_reports_none_and_zero_folds),
    ("cpcv_normal_run_keeps_current_numbers", test_cpcv_normal_run_keeps_current_numbers),
    ("main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]


def main() -> int:
    tests = TEST_REGISTRY

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


if __name__ == "__main__":
    sys.exit(main())
