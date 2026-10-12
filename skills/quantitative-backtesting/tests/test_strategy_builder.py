import json
import sys
import traceback
from typing import Dict

import numpy as np
import pandas as pd

# StrategyBuilder uses relative imports when run as module
try:
    from ..scripts.strategy_builder import (
        build_strategy,
        get_strategy_defaults,

        list_strategies,
    )
except ImportError:  # fallback for direct execution
    sys.path.insert(0, "..")
    from scripts.strategy_builder import (
        build_strategy,
        get_strategy_defaults,

        list_strategies,
    )


def _make_data(n=200):
    dates = pd.date_range("2019-01-01", periods=n, freq="D")
    prices = pd.Series([100 + i * 0.01 + (i % 10) * 0.05 for i in range(n)])
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices,
            "volume": [1000000] * n,
        },
        index=dates,
    )
    return df


def _make_multi_asset_data(n=200, n_assets=5, seed=42):
    """Create panel data for multiple assets with different return profiles."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-01", periods=n, freq="D")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]

    # Create returns with different drifts for each asset
    data_dict = {}
    for i, sym in enumerate(symbols):
        # Different drift per asset to create cross-sectional dispersion
        drift = 0.0001 * (i - n_assets // 2)  # Centered around zero
        rets = rng.normal(drift, 0.015, n)
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame(
            {
                "open": prices * rng.uniform(0.995, 1.005, n),
                "high": prices * rng.uniform(1.005, 1.02, n),
                "low": prices * rng.uniform(0.98, 0.995, n),
                "close": prices,
                "volume": rng.integers(1_000_000, 10_000_000, n),
            },
            index=dates,
        )
    return data_dict


def _make_multiindex_data(n=200, n_assets=5, seed=42):
    """Create MultiIndex column DataFrame for panel data."""
    data_dict = _make_multi_asset_data(n, n_assets, seed)
    # Build MultiIndex columns: (field, symbol)
    columns = pd.MultiIndex.from_tuples(
        [(field, sym) for sym in data_dict.keys() for field in ["open", "high", "low", "close", "volume"]]
    )
    # Reorder to group by field then symbol for easier slicing
    columns = columns.reorder_levels([0, 1]).sortlevel(0)[0]

    df = pd.DataFrame(index=data_dict[list(data_dict.keys())[0]].index, columns=columns, dtype=float)
    for sym, sym_df in data_dict.items():
        for field in ["open", "high", "low", "close", "volume"]:
            df[(field, sym)] = sym_df[field].values
    return df


def test_build_strategy_unknown_type_raises():
    try:
        build_strategy("nonexistent", "{}")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_build_strategy_parses_params():
    s = build_strategy("sma_crossover", '{"fast_period": 5, "slow_period": 15}')
    assert s.parameters["fast_period"] == 5
    assert s.parameters["slow_period"] == 15


def test_registry_listing_and_defaults_agree():
    strategies = list_strategies()
    assert "sma_crossover" in strategies
    assert "donchian_breakout" in strategies
    assert "cross_sectional_momentum" in strategies
    assert "rsi_mean_reversion" in strategies

    for name in strategies:
        params = get_strategy_defaults(name)
        assert isinstance(params, dict)
        s = build_strategy(name, json.dumps(params))
        assert s.name == name


def test_all_registered_strategies_generate_valid_signals():
    data = _make_data()
    for name in list_strategies():
        params = get_strategy_defaults(name)
        s = build_strategy(name, json.dumps(params))
        signals = s.generate_signals(data)
        # Signals must be in {0,1} and same index/length as data
        assert set(signals.unique()).issubset({0, 1, pd.NA if signals.isna().any() else 0})
        assert len(signals) == len(data)
        assert signals.index.equals(data.index)


def test_sma_crossover_signals_are_binary_with_crossovers():
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)

    assert set(signals.unique()).issubset({0, 1})
    # fast < slow over a long window must produce at least one crossover
    assert (signals.diff() != 0).sum() > 0


def test_donchian_breakout_uses_prior_period_high():
    """Donchian channel breakout uses prior N-period high (shifted)."""
    dates = pd.date_range("2020-01-01", periods=6, freq="D")
    data = pd.DataFrame(
        {
            "open": [100] * 6,
            "high": [100, 101, 102, 103, 104, 105],
            "low": [99] * 6,
            "close": [100] * 6,
            "volume": [1000000] * 6,
        },
        index=dates,
    )
    strat = build_strategy("donchian_breakout", '{"period": 5}')
    signals = strat.generate_signals(data)
    assert signals.iloc[0] == 0
    assert signals.iloc[-1] == 1
    assert signals.iloc[4] == 0  # channel not fully formed before shift gives defined value


def test_cross_sectional_momentum_multi_asset_dict():
    """CrossSectionalMomentum with dict of DataFrames produces portfolio signal."""
    data_dict = _make_multi_asset_data(n=150, n_assets=6, seed=123)
    # Use asymmetric quantiles to ensure non-zero net signal
    strategy = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}')
    signals = strategy.generate_signals(data_dict)

    # Should return a Series with common date index
    assert isinstance(signals, pd.Series)
    assert len(signals) > 0
    # Signal should be float representing (n_long - n_short) / n_assets
    assert signals.dtype in [np.float64, np.float32, float]
    # Values should be in [-1, 1] range
    assert (signals.abs() <= 1.0).all()
    # Should have some non-zero signals after lookback period
    assert (signals != 0).any()


def test_cross_sectional_momentum_multiindex_dataframe():
    """CrossSectionalMomentum with MultiIndex DataFrame produces portfolio signal."""
    data = _make_multiindex_data(n=150, n_assets=6, seed=456)
    # Use asymmetric quantiles to ensure non-zero net signal
    strategy = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}')
    signals = strategy.generate_signals(data)

    assert isinstance(signals, pd.Series)
    assert len(signals) > 0
    assert signals.dtype in [np.float64, np.float32, float]
    assert (signals.abs() <= 1.0).all()
    assert (signals != 0).any()


def test_cross_sectional_momentum_single_asset_fallback():
    """CrossSectionalMomentum with single-asset DataFrame warns and falls back."""
    import warnings

    data = _make_data(n=150)
    strategy = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.3, "bottom_quantile": 0.3}')

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        signals = strategy.generate_signals(data)

        # Should emit UserWarning about single-asset fallback
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert "single-asset" in str(w[0].message).lower()
        assert "falling back" in str(w[0].message).lower()

    # Should still produce valid signals (binary: -1, 0, 1)
    assert isinstance(signals, pd.Series)
    assert len(signals) == len(data)
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_cross_sectional_momentum_respects_quantiles():
    """Cross-sectional ranking respects top/bottom quantile parameters."""
    # Create data where we know the exact ranking
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    symbols = ["A", "B", "C", "D", "E"]  # 5 assets

    # Create returns with known ordering: A > B > C > D > E consistently
    data_dict = {}
    for i, sym in enumerate(symbols):
        drift = 0.001 * (2 - i)  # A=0.002, B=0.001, C=0.0, D=-0.001, E=-0.002
        np.random.seed(42 + i)
        rets = np.random.normal(drift, 0.005, 60)
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame(
            {"open": prices, "high": prices * 1.01, "low": prices * 0.99,
             "close": prices, "volume": [1000000] * 60},
            index=dates,
        )

    # With top_quantile=0.4 (2/5) and bottom_quantile=0.4 (2/5):
    # Top 2: A, B -> long; Bottom 2: D, E -> short; C -> flat
    # Net signal = (2 - 2) / 5 = 0
    strategy = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.4}')
    signals = strategy.generate_signals(data_dict)

    # After lookback, signal should be near 0 (2 longs - 2 shorts) / 5 = 0
    post_lookback = signals.iloc[20:]
    assert post_lookback.abs().mean() < 0.2  # Should be close to 0

    # With top_quantile=0.6 (3/5) and bottom_quantile=0.2 (1/5):
    # Top 3: A, B, C -> long; Bottom 1: E -> short
    # Net signal = (3 - 1) / 5 = 0.4
    strategy2 = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.6, "bottom_quantile": 0.2}')
    signals2 = strategy2.generate_signals(data_dict)
    post_lookback2 = signals2.iloc[20:]
    # Average should be close to 0.4
    assert abs(post_lookback2.mean() - 0.4) < 0.15


def main() -> int:
    tests = [
        ("build_strategy_unknown_type_raises", test_build_strategy_unknown_type_raises),
        ("build_strategy_parses_params", test_build_strategy_parses_params),
        ("registry_listing_and_defaults_agree", test_registry_listing_and_defaults_agree),
        ("all_registered_strategies_generate_valid_signals", test_all_registered_strategies_generate_valid_signals),
        ("sma_crossover_signals_are_binary_with_crossovers", test_sma_crossover_signals_are_binary_with_crossovers),
        ("donchian_breakout_uses_prior_period_high", test_donchian_breakout_uses_prior_period_high),
        ("cross_sectional_momentum_multi_asset_dict", test_cross_sectional_momentum_multi_asset_dict),
        ("cross_sectional_momentum_multiindex_dataframe", test_cross_sectional_momentum_multiindex_dataframe),
        ("cross_sectional_momentum_single_asset_fallback", test_cross_sectional_momentum_single_asset_fallback),
        ("cross_sectional_momentum_respects_quantiles", test_cross_sectional_momentum_respects_quantiles),
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


if __name__ == "__main__":
    sys.exit(main())
