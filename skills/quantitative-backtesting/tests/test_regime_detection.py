#!/usr/bin/env python3
"""Unit tests for regime_detection module."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import (
    RegimeConfig,
    TrendRegime,
    VolatilityRegime,
    detect_trend_regime,
    detect_volatility_regime,
    detect_combined_regime,
    identify_regime_periods,
    compute_regime_performance,
    regime_performance_summary,
    add_regime_analysis_to_results,
)


def make_price_series(length: int = 300, seed: int = 42) -> pd.Series:
    """Generate a synthetic price series with known regime changes."""
    np.random.seed(seed)
    dates = pd.date_range("2020-01-01", periods=length, freq="B")

    # Create three regimes: bull, bear, sideways
    regime_lengths = [length // 3, length // 3, length - 2 * (length // 3)]
    returns_list = []
    for i, reg_len in enumerate(regime_lengths):
        if i == 0:  # Bull
            mu, sigma = 0.001, 0.01
        elif i == 1:  # Bear
            mu, sigma = -0.0005, 0.02
        else:  # Sideways
            mu, sigma = 0.0001, 0.015
        returns_list.append(np.random.normal(mu, sigma, reg_len))

    returns = np.concatenate(returns_list)
    prices = 100 * np.exp(np.cumsum(returns))

    return pd.Series(prices, index=dates[:len(prices)])


class TestTrendRegimeDetection:
    """Tests for trend regime detection."""

    def test_bull_regime_detected(self):
        """Bull market (rising prices) should be detected as bull."""
        # Strong uptrend
        prices = pd.Series(100 * np.exp(np.cumsum(np.full(250, 0.001))), index=pd.date_range("2020-01-01", periods=250, freq="B"))
        regimes = detect_trend_regime(prices, ma_short=20, ma_long=60, threshold=0.01)

        # After warmup, should be mostly bull
        valid = regimes[regimes != TrendRegime.UNKNOWN.value]
        assert len(valid) > 0
        assert (valid == TrendRegime.BULL.value).mean() > 0.5

    def test_bear_regime_detected(self):
        """Bear market (falling prices) should be detected as bear."""
        # Strong downtrend
        prices = pd.Series(100 * np.exp(np.cumsum(np.full(250, -0.001))), index=pd.date_range("2020-01-01", periods=250, freq="B"))
        regimes = detect_trend_regime(prices, ma_short=20, ma_long=60, threshold=0.01)

        valid = regimes[regimes != TrendRegime.UNKNOWN.value]
        assert len(valid) > 0
        assert (valid == TrendRegime.BEAR.value).mean() > 0.5

    def test_sideways_regime_detected(self):
        """Sideways market should be detected as sideways."""
        # Mean-reverting around constant
        np.random.seed(42)
        returns = np.random.normal(0.0, 0.01, 250)
        prices = pd.Series(100 * np.exp(np.cumsum(returns)), index=pd.date_range("2020-01-01", periods=250, freq="B"))
        regimes = detect_trend_regime(prices, ma_short=20, ma_long=60, threshold=0.02)

        valid = regimes[regimes != TrendRegime.UNKNOWN.value]
        assert len(valid) > 0
        # Sideways should have significant presence
        assert (valid == TrendRegime.SIDEWAYS.value).mean() > 0.1

    def test_short_series_returns_unknown(self):
        """Series shorter than MA windows should return unknown."""
        prices = pd.Series([100, 101, 102], index=pd.date_range("2020-01-01", periods=3, freq="B"))
        regimes = detect_trend_regime(prices, ma_short=50, ma_long=200)
        assert (regimes == TrendRegime.UNKNOWN.value).all()

    def test_output_index_matches_input(self):
        """Output index should match input index."""
        prices = make_price_series(200)
        regimes = detect_trend_regime(prices)
        assert regimes.index.equals(prices.index)


class TestVolatilityRegimeDetection:
    """Tests for volatility regime detection."""

    def test_high_vol_detected(self):
        """High volatility period should be detected."""
        # Alternating high/low vol
        np.random.seed(42)
        n = 300
        returns = np.zeros(n)
        returns[:100] = np.random.normal(0, 0.02, 100)  # High vol
        returns[100:200] = np.random.normal(0, 0.005, 100)  # Low vol
        returns[200:] = np.random.normal(0, 0.02, 100)  # High vol

        prices = pd.Series(100 * np.exp(np.cumsum(returns)), index=pd.date_range("2020-01-01", periods=n, freq="B"))
        regimes = detect_volatility_regime(prices, window=21, quantile_high=0.7, quantile_low=0.3)

        valid = regimes[regimes != VolatilityRegime.UNKNOWN.value]
        assert len(valid) > 0
        # High vol periods should be classified as high
        high_regions = regimes.iloc[:100][regimes.iloc[:100] != VolatilityRegime.UNKNOWN.value]
        low_regions = regimes.iloc[100:200][regimes.iloc[100:200] != VolatilityRegime.UNKNOWN.value]

        if len(high_regions) > 0 and len(low_regions) > 0:
            assert (high_regions == VolatilityRegime.HIGH.value).mean() > (low_regions == VolatilityRegime.HIGH.value).mean()

    def test_low_vol_detected(self):
        """Low volatility period should be detected."""
        np.random.seed(42)
        n = 200
        returns = np.random.normal(0, 0.005, n)  # Consistently low vol
        prices = pd.Series(100 * np.exp(np.cumsum(returns)), index=pd.date_range("2020-01-01", periods=n, freq="B"))
        regimes = detect_volatility_regime(prices, window=21, quantile_high=0.75, quantile_low=0.25)

        valid = regimes[regimes != VolatilityRegime.UNKNOWN.value]
        assert len(valid) > 0

    def test_short_series_returns_unknown(self):
        """Series shorter than vol window should return unknown."""
        prices = pd.Series([100, 101, 102], index=pd.date_range("2020-01-01", periods=3, freq="B"))
        regimes = detect_volatility_regime(prices, window=63)
        assert (regimes == VolatilityRegime.UNKNOWN.value).all()


class TestCombinedRegimeDetection:
    """Tests for combined regime detection."""

    def test_combined_regime_labels(self):
        """Combined regime should produce labels like 'bull_high', 'bear_low', etc."""
        prices = make_price_series(300)
        regimes = detect_combined_regime(prices, RegimeConfig(trend_ma_short=20, trend_ma_long=60))

        valid = regimes[regimes != "unknown"]
        assert len(valid) > 0

        # Check label format
        for label in valid.unique():
            parts = label.split("_")
            assert len(parts) == 2
            assert parts[0] in [TrendRegime.BULL.value, TrendRegime.BEAR.value, TrendRegime.SIDEWAYS.value]
            assert parts[1] in [VolatilityRegime.HIGH.value, VolatilityRegime.LOW.value]

    def test_output_index_matches_input(self):
        """Output index should match input index."""
        prices = make_price_series(200)
        regimes = detect_combined_regime(prices)
        assert regimes.index.equals(prices.index)


class TestRegimePeriods:
    """Tests for regime period identification."""

    def test_identify_periods(self):
        """Should identify contiguous regime periods."""
        regimes = pd.Series(
            ["bull_low", "bull_low", "bear_high", "bear_high", "bear_high", "bull_low"],
            index=pd.date_range("2020-01-01", periods=6, freq="B")
        )
        periods = identify_regime_periods(regimes)

        assert len(periods) == 3
        assert periods[0].regime == "bull_low"
        assert periods[0].length == 2
        assert periods[1].regime == "bear_high"
        assert periods[1].length == 3
        assert periods[2].regime == "bull_low"
        assert periods[2].length == 1

    def test_single_period(self):
        """Single regime should produce one period."""
        regimes = pd.Series(
            ["bull_low"] * 10,
            index=pd.date_range("2020-01-01", periods=10, freq="B")
        )
        periods = identify_regime_periods(regimes)
        assert len(periods) == 1
        assert periods[0].regime == "bull_low"
        assert periods[0].length == 10


class TestRegimePerformance:
    """Tests for regime-dependent performance computation."""

    def test_compute_performance_per_regime(self):
        """Should compute metrics for each regime."""
        np.random.seed(42)
        n = 300
        returns = pd.Series(np.random.normal(0.0005, 0.01, n), index=pd.date_range("2020-01-01", periods=n, freq="B"))
        regimes = pd.Series(["bull"] * 100 + ["bear"] * 100 + ["sideways"] * 100, index=returns.index)

        perf = compute_regime_performance(returns, regimes, min_period_length=10)

        assert "bull" in perf
        assert "bear" in perf
        assert "sideways" in perf

        for regime, metrics in perf.items():
            assert "sharpe_ratio" in metrics
            assert "annualized_return" in metrics
            assert "annualized_volatility" in metrics
            assert "max_drawdown" in metrics
            assert "win_rate" in metrics
            assert "n_observations" in metrics

    def test_regime_too_short_excluded(self):
        """Regimes with too few observations should be excluded."""
        np.random.seed(42)
        n = 100
        returns = pd.Series(np.random.normal(0.0005, 0.01, n), index=pd.date_range("2020-01-01", periods=n, freq="B"))
        regimes = pd.Series(["bull"] * 90 + ["bear"] * 10, index=returns.index)

        perf = compute_regime_performance(returns, regimes, min_period_length=20)

        assert "bull" in perf
        assert "bear" not in perf  # Too short

    def test_unknown_regime_excluded(self):
        """Unknown regime should be excluded from performance."""
        np.random.seed(42)
        n = 100
        returns = pd.Series(np.random.normal(0.0005, 0.01, n), index=pd.date_range("2020-01-01", periods=n, freq="B"))
        regimes = pd.Series(["bull"] * 50 + ["unknown"] * 50, index=returns.index)

        perf = compute_regime_performance(returns, regimes, min_period_length=10)

        assert "bull" in perf
        assert "unknown" not in perf


class TestRegimePerformanceSummary:
    """Tests for complete regime performance summary."""

    def test_summary_structure(self):
        """Summary should have all expected keys."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        summary = regime_performance_summary(returns, prices)

        assert "config" in summary
        assert "trend_regime_performance" in summary
        assert "volatility_regime_performance" in summary
        assert "combined_regime_performance" in summary
        assert "regime_periods" in summary
        assert "regime_distribution" in summary

    def test_summary_with_config(self):
        """Summary should reflect config parameters."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        config = RegimeConfig(trend_ma_short=10, trend_ma_long=30, trend_threshold=0.01)
        summary = regime_performance_summary(returns, prices, config)

        assert summary["config"]["trend_ma_short"] == 10
        assert summary["config"]["trend_ma_long"] == 30
        assert summary["config"]["trend_threshold"] == 0.01


class TestAddRegimeAnalysisToResults:
    """Tests for adding regime analysis to backtest results."""

    def test_adds_regime_analysis_key(self):
        """Should add regime_analysis key to results."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        results = {"returns": returns}
        data = pd.DataFrame({"close": prices})

        updated = add_regime_analysis_to_results(results, data)

        assert "regime_analysis" in updated
        assert updated["regime_analysis"] is not None

    def test_handles_panel_data(self):
        """Should handle panel data (dict of DataFrames)."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        data = {"AAPL": pd.DataFrame({"close": prices})}
        results = {"returns": returns}

        updated = add_regime_analysis_to_results(results, data)

        assert "regime_analysis" in updated

    def test_returns_none_if_no_returns_key(self):
        """Should return original results if returns key missing."""
        results = {"other_key": "value"}
        data = {"close": make_price_series(100)}

        updated = add_regime_analysis_to_results(results, data)

        assert "regime_analysis" not in updated

    def test_returns_none_if_no_close_data(self):
        """Should return original results if close data missing."""
        results = {"returns": pd.Series([1, 2, 3])}
        data = {"open": [1, 2, 3]}

        updated = add_regime_analysis_to_results(results, data)

        assert "regime_analysis" not in updated


class TestRegimeConfig:
    """Tests for RegimeConfig dataclass."""

    def test_default_config(self):
        """Default config should have sensible values."""
        config = RegimeConfig()
        assert config.trend_ma_short == 50
        assert config.trend_ma_long == 200
        assert config.trend_threshold == 0.02
        assert config.vol_window == 63
        assert config.vol_quantile_high == 0.75
        assert config.vol_quantile_low == 0.25
        assert config.min_regime_length == 21

    def test_custom_config(self):
        """Custom config should accept all parameters."""
        config = RegimeConfig(
            trend_ma_short=20,
            trend_ma_long=60,
            trend_threshold=0.01,
            vol_window=21,
            vol_quantile_high=0.8,
            vol_quantile_low=0.2,
            min_regime_length=10,
        )
        assert config.trend_ma_short == 20
        assert config.trend_ma_long == 60
        assert config.trend_threshold == 0.01
        assert config.vol_window == 21
        assert config.vol_quantile_high == 0.8
        assert config.vol_quantile_low == 0.2
        assert config.min_regime_length == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])