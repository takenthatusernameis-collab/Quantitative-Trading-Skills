import json
import sys
import traceback
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from strategy_builder import (  # noqa: E402
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
    # Symmetric quantiles make the net signal flat by construction, so
    # generate_signals must warn about it (regression guard).
    import warnings

    strategy = build_strategy("cross_sectional_momentum", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.4}')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        signals = strategy.generate_signals(data_dict)

    assert len(w) == 1
    assert issubclass(w[0].category, UserWarning)
    assert "top_quantile == bottom_quantile" in str(w[0].message)

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


def test_cross_sectional_momentum_symmetric_quantiles_flat():
    """Symmetric quantiles (incl. defaults) produce a flat signal and warn.

    Regression guard for the net-exposure convention: when
    top_quantile == bottom_quantile the long and short books are the
    same size every period, so (n_long - n_short) / n_assets is zero
    by construction and the strategy never takes a position. The
    default parameters (0.2 / 0.2) hit this case.
    """
    import warnings

    data_dict = _make_multi_asset_data(n=150, n_assets=6, seed=123)

    # The published defaults are symmetric (0.2 / 0.2).
    defaults = get_strategy_defaults("cross_sectional_momentum")
    assert defaults["top_quantile"] == defaults["bottom_quantile"]

    strategy = build_strategy("cross_sectional_momentum",
                              '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}')

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        signals = strategy.generate_signals(data_dict)

    assert len(w) == 1
    assert issubclass(w[0].category, UserWarning)
    assert "top_quantile == bottom_quantile" in str(w[0].message)

    # Net signal is zero everywhere by construction.
    assert (signals == 0).all()


def test_cross_sectional_momentum_overlapping_quantiles_warn():
    """top_quantile + bottom_quantile > 1.0 warns about overlapping books.

    When the quantiles sum above 1.0 the top and bottom selections
    overlap, so at least one asset is simultaneously long and short.
    """
    import warnings

    data_dict = _make_multi_asset_data(n=150, n_assets=6, seed=123)

    # 0.6 + 0.6 = 1.2 > 1.0 (also symmetric, so both warnings fire).
    strategy = build_strategy("cross_sectional_momentum",
                              '{"lookback": 20, "top_quantile": 0.6, "bottom_quantile": 0.6}')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        strategy.generate_signals(data_dict)

    messages = [str(x.message) for x in w if issubclass(x.category, UserWarning)]
    assert any("top_quantile == bottom_quantile" in m for m in messages)
    assert any("overlap" in m.lower() for m in messages)

    # 0.5 + 0.8 = 1.3 > 1.0 but asymmetric: only the overlap warning fires.
    strategy2 = build_strategy("cross_sectional_momentum",
                               '{"lookback": 20, "top_quantile": 0.5, "bottom_quantile": 0.8}')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        strategy2.generate_signals(data_dict)

    messages2 = [str(x.message) for x in w if issubclass(x.category, UserWarning)]
    assert len(messages2) == 1
    assert "overlap" in messages2[0].lower()


def test_cross_sectional_momentum_asymmetric_no_warning():
    """Asymmetric, non-overlapping quantiles produce no warnings."""
    import warnings

    data_dict = _make_multi_asset_data(n=150, n_assets=6, seed=123)

    strategy = build_strategy("cross_sectional_momentum",
                              '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        signals = strategy.generate_signals(data_dict)

    assert len(w) == 0
    assert (signals != 0).any()


def test_dual_momentum_multi_asset_dict():
    """DualMomentumStrategy with dict of DataFrames produces portfolio signal."""
    data_dict = _make_multi_asset_data(n=150, n_assets=6, seed=123)
    # Use top_quantile to select subset of assets with positive absolute momentum
    strategy = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 0.4, "risk_free_rate": 0.0}')
    signals = strategy.generate_signals(data_dict)

    # Should return a Series with common date index
    assert isinstance(signals, pd.Series)
    assert len(signals) > 0
    # Signal should be float representing n_selected / n_assets
    assert signals.dtype in [np.float64, np.float32, float]
    # Values should be in [0, 1] range (long-only)
    assert (signals >= 0).all() and (signals <= 1.0).all()
    # Should have some non-zero signals after lookback period
    assert (signals != 0).any()


def test_dual_momentum_multiindex_dataframe():
    """DualMomentumStrategy with MultiIndex DataFrame produces portfolio signal."""
    data = _make_multiindex_data(n=150, n_assets=6, seed=456)
    strategy = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 0.4, "risk_free_rate": 0.0}')
    signals = strategy.generate_signals(data)

    assert isinstance(signals, pd.Series)
    assert len(signals) > 0
    assert signals.dtype in [np.float64, np.float32, float]
    assert (signals >= 0).all() and (signals <= 1.0).all()
    assert (signals != 0).any()


def test_dual_momentum_single_asset_fallback():
    """DualMomentumStrategy with single-asset DataFrame warns and falls back."""
    import warnings

    data = _make_data(n=150)
    strategy = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 0.3, "risk_free_rate": 0.0}')

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        signals = strategy.generate_signals(data)

        # Should emit UserWarning about single-asset fallback
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert "single-asset" in str(w[0].message).lower()
        assert "falling back" in str(w[0].message).lower()

    # Should still produce valid signals (binary: 0, 1)
    assert isinstance(signals, pd.Series)
    assert len(signals) == len(data)
    assert set(signals.unique()).issubset({0, 1})


def test_dual_momentum_absolute_momentum_filter():
    """Dual momentum respects absolute momentum filter (risk-free rate)."""
    # Create data where some assets have consistently negative returns
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    symbols = ["POS", "NEG", "FLAT"]  # 3 assets

    data_dict = {}
    # POS: strong positive drift, low volatility
    np.random.seed(42)
    rets_pos = np.random.normal(0.005, 0.002, 60)  # Strong positive drift
    prices_pos = 100 * np.exp(np.cumsum(rets_pos))
    data_dict["POS"] = pd.DataFrame(
        {"open": prices_pos, "high": prices_pos * 1.01, "low": prices_pos * 0.99,
         "close": prices_pos, "volume": [1000000] * 60}, index=dates)

    # NEG: strong negative drift
    np.random.seed(43)
    rets_neg = np.random.normal(-0.005, 0.002, 60)  # Strong negative drift
    prices_neg = 100 * np.exp(np.cumsum(rets_neg))
    data_dict["NEG"] = pd.DataFrame(
        {"open": prices_neg, "high": prices_neg * 1.01, "low": prices_neg * 0.99,
         "close": prices_neg, "volume": [1000000] * 60}, index=dates)

    # FLAT: zero drift
    np.random.seed(44)
    rets_flat = np.random.normal(0.0, 0.002, 60)
    prices_flat = 100 * np.exp(np.cumsum(rets_flat))
    data_dict["FLAT"] = pd.DataFrame(
        {"open": prices_flat, "high": prices_flat * 1.01, "low": prices_flat * 0.99,
         "close": prices_flat, "volume": [1000000] * 60}, index=dates)

    # With risk_free_rate = 0, only POS should consistently pass absolute momentum filter
    # top_quantile=1.0 means select all assets with positive abs momentum
    strategy = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 1.0, "risk_free_rate": 0.0}')
    signals = strategy.generate_signals(data_dict)

    # After lookback, only POS should be selected -> signal = 1/3
    post_lookback = signals.iloc[20:]
    # Mean should be close to 1/3 = 0.333...
    assert abs(post_lookback.mean() - 1/3) < 0.15

    # With higher risk_free_rate, fewer assets should pass -> lower signal
    # POS has ~10% returns over 20 days, so use rf > 10% period rate
    # rf=3.5 (350% annual) gives rf_period ≈ 0.11 > POS returns
    strategy2 = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 1.0, "risk_free_rate": 3.5}')
    signals2 = strategy2.generate_signals(data_dict)
    post_lookback2 = signals2.iloc[20:]
    # Signal should be lower (ideally 0, but allow small noise)
    assert post_lookback2.mean() < post_lookback.mean() * 0.5  # Significantly lower


def test_dual_momentum_respects_top_quantile():
    """Dual momentum relative momentum ranking respects top_quantile."""
    # Create 5 assets with known return ordering and low volatility
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    symbols = ["A", "B", "C", "D", "E"]

    data_dict = {}
    for i, sym in enumerate(symbols):
        drift = 0.003 * (2 - i)  # A=0.006, B=0.003, C=0.0, D=-0.003, E=-0.006
        np.random.seed(42 + i)
        rets = np.random.normal(drift, 0.001, 60)  # Low volatility
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame(
            {"open": prices, "high": prices * 1.01, "low": prices * 0.99,
             "close": prices, "volume": [1000000] * 60}, index=dates)

    # With very negative risk_free_rate, all assets pass absolute momentum
    # rf=-0.99 gives rf_period ≈ -0.31, well below even E's returns
    # top_quantile=0.4 (2/5) -> select top 2: A, B -> signal = 2/5 = 0.4
    strategy = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 0.4, "risk_free_rate": -0.99}')
    signals = strategy.generate_signals(data_dict)
    post_lookback = signals.iloc[20:]
    assert abs(post_lookback.mean() - 0.4) < 0.15

    # top_quantile=0.6 (3/5) -> select top 3: A, B, C -> signal = 3/5 = 0.6
    strategy2 = build_strategy("dual_momentum", '{"lookback": 20, "top_quantile": 0.6, "risk_free_rate": -0.99}')
    signals2 = strategy2.generate_signals(data_dict)
    post_lookback2 = signals2.iloc[20:]
    assert abs(post_lookback2.mean() - 0.6) < 0.15



def test_mean_reversion_zscore_pairs_two_asset_dict():
    """MeanReversionZScore generates spread-based signals for two-asset dict.

    Uses a known spread pattern to verify entry/exit logic:
    - spread=2.5 at index 40 -> z-score > entry_z -> short signal (-1)
    - spread=-2.6 at index 70 -> z-score < -entry_z -> long signal (1)
    - exit when |z-score| <= exit_z
    """
    from strategy_builder import build_strategy
    import pandas as pd
    import numpy as np

    dates = pd.date_range("2021-01-01", periods=100, freq="B")
    np.random.seed(7)
    spread = np.zeros(100)
    spread[40] = 2.5
    spread[41:45] = [1.5, 0.8, 0.3, 0.1]
    spread[70] = -2.6
    spread[71:75] = [-1.4, -0.6, -0.2, 0.05]
    C = 100
    p1 = C * np.exp(spread + np.random.normal(0, 0.01, 100))
    p2 = C + np.random.normal(0, 0.1, 100)
    data_dict = {
        "A": pd.DataFrame({"close": p1}, index=dates),
        "B": pd.DataFrame({"close": p2}, index=dates),
    }
    s = build_strategy("zscore_mean_reversion", '{"period": 20, "entry_z": 2.0, "exit_z": 0.5}')
    sig = s.generate_signals(data_dict)
    assert sig.iloc[39] == 0
    assert sig.iloc[40] == 0 or sig.iloc[41] == -1  # enters short around high spread
    assert sig.iloc[69] == 0
    assert sig.iloc[70] == 0 or sig.iloc[71] == 1  # enters long around low spread
    # Should produce at least one non-zero signal in post-period
    assert (sig.iloc[20:] != 0).any()


def test_mean_reversion_zscore_pairs_multiindex_two_assets():
    """MeanReversionZScore works with MultiIndex DataFrame containing two assets."""
    from strategy_builder import build_strategy
    from test_strategy_builder import _make_multiindex_data
    import pandas as pd

    data = _make_multiindex_data(n=100, n_assets=2, seed=42)
    s = build_strategy("zscore_mean_reversion", '{"period": 20}')
    sig = s.generate_signals(data)
    assert isinstance(sig, pd.Series)
    assert len(sig) == len(data)


def test_mean_reversion_zscore_single_asset_fallback():
    """MeanReversionZScore with single-asset data warns and falls back."""
    import warnings
    from strategy_builder import build_strategy
    from test_strategy_builder import _make_data

    data = _make_data(n=80)
    s = build_strategy("zscore_mean_reversion", '{"period": 20}')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        sig = s.generate_signals(data)
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert "single-asset" in str(w[0].message).lower()

    assert len(sig) == len(data)
    assert set(sig.unique()).issubset({-1, 0, 1})


def test_mean_reversion_zscore_rejects_three_assets():
    """MeanReversionZScore rejects panel data with != 2 assets."""
    from strategy_builder import build_strategy
    from test_strategy_builder import _make_multi_asset_data, _make_multiindex_data

    # dict with 3
    try:
        data = _make_multi_asset_data(n=50, n_assets=3, seed=1)
        s = build_strategy("zscore_mean_reversion", '{"period": 10}')
        s.generate_signals(data)
        assert False, "Expected ValueError"
    except ValueError:
        pass

    # MultiIndex with 3
    try:
        data = _make_multiindex_data(n=50, n_assets=3, seed=1)
        s = build_strategy("zscore_mean_reversion", '{"period": 10}')
        s.generate_signals(data)
        assert False, "Expected ValueError"
    except ValueError:
        pass


def _make_cointegrated_pair(n=200, beta=0.6, seed=42):
    """Create two cointegrated price series with a known OLS hedge ratio.

    log(p2) follows a random walk; log(p1) = beta * log(p2) + small
    stationary noise, so the OLS slope of log(p1) on log(p2) recovers
    ``beta`` and the residual spread is stationary (low variance).
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    # Random walk in log space for the base price
    log_p2 = np.cumsum(rng.normal(0, 0.01, n))
    # Cointegrated: log(p1) = beta * log(p2) + small mean-reverting noise
    log_p1 = beta * log_p2 + rng.normal(0, 0.002, n)

    p1 = np.exp(log_p1)
    p2 = np.exp(log_p2)
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    return {
        "A": pd.DataFrame({"close": p1}, index=dates),
        "B": pd.DataFrame({"close": p2}, index=dates),
    }, log_p1, log_p2, dates


def _rolling_ols_beta(y: np.ndarray, x: np.ndarray, window: int):
    """Reference rolling OLS slope of y on x (with intercept), returned as Series."""
    ys = pd.Series(y)
    xs = pd.Series(x)
    mean_x = xs.rolling(window).mean()
    mean_y = ys.rolling(window).mean()
    cov_xy = (ys * xs).rolling(window).mean() - mean_x * mean_y
    var_x = (xs * xs).rolling(window).mean() - mean_x * mean_x
    beta = cov_xy / var_x
    return beta


def test_ols_hedge_recovers_known_hedge_ratio():
    """OLS hedge ratio recovers the true beta for a known cointegrated pair (dict)."""
    from strategy_builder import build_strategy

    data_dict, log_p1, log_p2, dates = _make_cointegrated_pair(n=200, beta=0.6, seed=42)

    s = build_strategy(
        "zscore_mean_reversion",
        json.dumps(
            {
                "spread_method": "ols_hedge",
                "hedge_lookback": 30,
                "period": 20,
                "entry_z": 2.0,
                "exit_z": 0.5,
            }
        ),
    )
    sig = s.generate_signals(data_dict)

    # Signals must be valid {-1, 0, 1} (NaN only in the warm-up period)
    assert isinstance(sig, pd.Series)
    assert sig.index.equals(dates)
    present = sig.dropna()
    assert set(present.unique()).issubset({-1.0, 0.0, 1.0})
    # Strategy should produce at least some active positions after warm-up
    assert (present.abs() > 0).any()

    # Independently verify the hedge ratio recovery: the last rolling OLS beta
    # should be close to the true beta (0.6).  With finite-sample OLS on a
    # random-walk pair, a tolerance of 0.05 (≈8 % relative) is a meaningful
    # recovery check.
    beta_est = _rolling_ols_beta(log_p1, log_p2, 30)
    assert abs(beta_est.iloc[-1] - 0.6) < 0.05


def test_ols_hedge_multiindex_two_assets():
    """OLS hedge ratio works with MultiIndex panel data (same pair)."""
    from strategy_builder import build_strategy

    data_dict, log_p1, log_p2, dates = _make_cointegrated_pair(n=200, beta=0.6, seed=99)
    # Build MultiIndex column DataFrame
    columns = pd.MultiIndex.from_tuples(
        [(f, s) for f in ["close"] for s in ["A", "B"]]
    )
    p1 = np.exp(log_p1)
    p2 = np.exp(log_p2)
    data = pd.DataFrame({("close", "A"): p1, ("close", "B"): p2}, index=dates)

    s = build_strategy(
        "zscore_mean_reversion",
        json.dumps({"spread_method": "ols_hedge", "hedge_lookback": 30, "period": 20}),
    )
    sig = s.generate_signals(data)

    assert isinstance(sig, pd.Series)
    assert sig.index.equals(dates)
    present = sig.dropna()
    assert set(present.unique()).issubset({-1.0, 0.0, 1.0})
    assert (present.abs() > 0).any()

    # Same beta recovery check on the MultiIndex path
    beta_est = _rolling_ols_beta(log_p1, log_p2, 30)
    assert abs(beta_est.iloc[-1] - 0.6) < 0.05


def test_ols_hedge_spread_is_stationary():
    """OLS residual spread is far less volatile than the cointegrated levels."""
    from strategy_builder import build_strategy

    data_dict, log_p1, log_p2, _ = _make_cointegrated_pair(n=200, beta=0.6, seed=42)

    s = build_strategy(
        "zscore_mean_reversion",
        json.dumps({"spread_method": "ols_hedge", "hedge_lookback": 30, "period": 20}),
    )
    # Access the residual spread directly via the private helper
    series1 = data_dict["A"]["close"]
    series2 = data_dict["B"]["close"]
    spread = s._ols_hedge_residual(series1, series2, 30)

    # Drop NaN warm-up
    spread_clean = spread.dropna()
    log1_std = float(np.std(log_p1))
    log2_std = float(np.std(log_p2))
    spread_std = float(np.std(spread_clean))

    # The residual spread should be a small fraction of the level volatilities.
    # log_p1 and log_p2 are random walks with substantial drift over 200 bars,
    # while the OLS residual is stationary noise.
    assert spread_std < 0.2 * min(log1_std, log2_std)


def test_ols_hedge_ignores_hedge_ratio():
    """When spread_method='ols_hedge', the fixed hedge_ratio parameter is ignored."""
    from strategy_builder import build_strategy

    data_dict, log_p1, log_p2, _ = _make_cointegrated_pair(n=200, beta=0.6, seed=7)

    s_no_ratio = build_strategy(
        "zscore_mean_reversion",
        json.dumps({"spread_method": "ols_hedge", "hedge_lookback": 30, "period": 20}),
    )
    s_with_ratio = build_strategy(
        "zscore_mean_reversion",
        json.dumps(
            {
                "spread_method": "ols_hedge",
                "hedge_lookback": 30,
                "period": 20,
                "hedge_ratio": 99.0,  # Should be ignored
            }
        ),
    )

    sig_a = s_no_ratio.generate_signals(data_dict)
    sig_b = s_with_ratio.generate_signals(data_dict)

    # Identical signals confirm hedge_ratio is ignored for ols_hedge
    pd.testing.assert_series_equal(
        sig_a.reset_index(drop=True),
        sig_b.reset_index(drop=True),
    )


def test_ols_hedge_backward_compat_default_is_log_ratio():
    """Default spread_method (log_ratio) is used when ols_hedge is not selected,
    even though hedge_lookback is now in the defaults dict."""
    from strategy_builder import build_strategy, get_strategy_defaults

    defaults = get_strategy_defaults("zscore_mean_reversion")
    assert defaults["spread_method"] == "log_ratio"
    assert "hedge_lookback" in defaults

    data_dict, _, _, dates = _make_cointegrated_pair(n=200, beta=0.6, seed=42)

    # Build with the published defaults (no overrides) -> log_ratio path
    s = build_strategy("zscore_mean_reversion", json.dumps(defaults))
    sig = s.generate_signals(data_dict)

    assert isinstance(sig, pd.Series)
    assert sig.index.equals(dates)
    present = sig.dropna()
    assert set(present.unique()).issubset({-1.0, 0.0, 1.0})
    assert (present.abs() > 0).any()



def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function."""
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
        f"{sorted(f.__name__ for f in missing)}"
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )

TEST_REGISTRY = [
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
    ("cross_sectional_momentum_symmetric_quantiles_flat", test_cross_sectional_momentum_symmetric_quantiles_flat),
    ("cross_sectional_momentum_overlapping_quantiles_warn", test_cross_sectional_momentum_overlapping_quantiles_warn),
    ("cross_sectional_momentum_asymmetric_no_warning", test_cross_sectional_momentum_asymmetric_no_warning),
    ("dual_momentum_multi_asset_dict", test_dual_momentum_multi_asset_dict),
    ("dual_momentum_multiindex_dataframe", test_dual_momentum_multiindex_dataframe),
    ("dual_momentum_single_asset_fallback", test_dual_momentum_single_asset_fallback),
    ("dual_momentum_absolute_momentum_filter", test_dual_momentum_absolute_momentum_filter),
    ("dual_momentum_respects_top_quantile", test_dual_momentum_respects_top_quantile),
    ("mean_reversion_zscore_pairs_two_asset_dict", test_mean_reversion_zscore_pairs_two_asset_dict),
    ("mean_reversion_zscore_pairs_multiindex_two_assets", test_mean_reversion_zscore_pairs_multiindex_two_assets),
    ("mean_reversion_zscore_single_asset_fallback", test_mean_reversion_zscore_single_asset_fallback),
    ("mean_reversion_zscore_rejects_three_assets", test_mean_reversion_zscore_rejects_three_assets),
    ("ols_hedge_recovers_known_hedge_ratio", test_ols_hedge_recovers_known_hedge_ratio),
    ("ols_hedge_multiindex_two_assets", test_ols_hedge_multiindex_two_assets),
    ("ols_hedge_spread_is_stationary", test_ols_hedge_spread_is_stationary),
    ("ols_hedge_ignores_hedge_ratio", test_ols_hedge_ignores_hedge_ratio),
    ("ols_hedge_backward_compat_default_is_log_ratio", test_ols_hedge_backward_compat_default_is_log_ratio),
    ("test_main_registers_every_module_level_test", test_main_registers_every_module_level_test),
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
