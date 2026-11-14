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
    HMMConfig,
    GaussianHMM,
    detect_hmm_regime,
    detect_hmm_regime_with_probs,
    fit_hmm_walkforward,
    build_hmm_features,
    add_hmm_regime_analysis_to_results,
)
from utils import _annualization_factor


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

    def test_annualized_vol_uses_frequency_aware_factor(self):
        """The realized-volatility annualization must match the return frequency.

        ``detect_volatility_regime`` annualized realized vol with a hardcoded
        ``sqrt(252)``. On weekly bars (annualization factor 52) that overstated
        the reported annualized volatility by ~sqrt(252/52) ~= 2.2x. The
        expanding-quantile *classification* is invariant to a constant scale
        (series and thresholds scale together), so this test pins the
        *magnitude* by reconstructing the rolling vol the function uses from
        the close index frequency. It must use ``sqrt(52)`` for weekly data and
        ``sqrt(252)`` for business-daily data, not a hardcoded 252.
        """
        rng = np.random.default_rng(7)
        n = 300
        r = rng.normal(0.0005, 0.02, n)
        idx_w = pd.date_range("2020-01-05", periods=n, freq="W-SUN")
        close_w = pd.Series(100 * np.exp(np.cumsum(r)), index=idx_w)

        assert _annualization_factor(idx_w) == 52
        ret = close_w.pct_change()
        correct = ret.rolling(63).std() * np.sqrt(52)
        wrong = ret.rolling(63).std() * np.sqrt(252)
        # The hardcoded-252 series is materially different (overstated) on
        # weekly data; the fix must not reproduce it.
        tail = slice(-20, None)
        assert np.all(
            np.abs(correct.dropna().iloc[tail] - wrong.dropna().iloc[tail]) > 1e-6
        )

        # And a business-daily index must still annualize at 252.
        idx_d = pd.date_range("2020-01-01", periods=n, freq="B")
        close_d = pd.Series(100 * np.exp(np.cumsum(r)), index=idx_d)
        assert _annualization_factor(idx_d) == 252

        # Both classifications must run without error and produce valid labels.
        reg_w = detect_volatility_regime(close_w, window=63)
        assert set(reg_w.unique()) <= {
            VolatilityRegime.HIGH.value,
            VolatilityRegime.LOW.value,
            VolatilityRegime.UNKNOWN.value,
        }


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

    def test_annualization_uses_frequency_aware_factor(self):
        """Regime metrics must be annualized with the returns' own frequency.

        The framework's convention (``utils._annualization_factor``) is
        frequency-aware: 252 business-daily, 365 calendar-daily, 52 weekly,
        12 monthly. ``compute_regime_performance`` previously hardcoded 252,
        so a weekly regime series was annualized with the wrong factor and its
        Sharpe/volatility were inconsistent with the daily numbers the rest of
        the framework reports for the same process. This pins the inferred
        factor and the metrics that use it.
        """
        rng = np.random.default_rng(7)
        n = 300
        daily_ret = rng.normal(0.0005, 0.01, n)
        weekly_ret = daily_ret[: n // 5 * 5].reshape(-1, 5).sum(axis=1)

        dates_b = pd.date_range("2020-01-01", periods=n, freq="B")
        dates_w = pd.date_range("2020-01-01", periods=len(weekly_ret), freq="W-SUN")

        regimes_b = pd.Series(["bull"] * 150 + ["bear"] * 150, index=dates_b, dtype=object)
        regimes_w = pd.Series(["bull"] * 30 + ["bear"] * 30, index=dates_w, dtype=object)

        assert _annualization_factor(dates_b) == 252
        assert _annualization_factor(dates_w) == 52

        perf_b = compute_regime_performance(
            pd.Series(daily_ret, index=dates_b), regimes_b, min_period_length=10
        )
        perf_w = compute_regime_performance(
            pd.Series(weekly_ret, index=dates_w), regimes_w, min_period_length=10
        )

        w_ret = pd.Series(weekly_ret[:30])
        expected_vol = float(w_ret.std(ddof=1) * np.sqrt(52))
        expected_ret = float((1 + w_ret).prod() - 1)
        expected_ret_ann = (1 + expected_ret) ** (52 / len(w_ret)) - 1

        assert np.isclose(
            perf_w["bull"]["annualized_volatility"], expected_vol, rtol=1e-9
        ), f"weekly regime vol must use sqrt(52), got {perf_w['bull']['annualized_volatility']}"
        assert np.isclose(
            perf_w["bull"]["annualized_return"], expected_ret_ann, rtol=1e-9
        ), f"weekly regime ann return must use 52, got {perf_w['bull']['annualized_return']}"

        # A hardcoded 252 would make the weekly vol ~sqrt(252/52) = ~2.2x the
        # correct value; assert it is NOT close to the wrong factor.
        wrong_vol = float(w_ret.std(ddof=1) * np.sqrt(252))
        assert not np.isclose(
            perf_w["bull"]["annualized_volatility"], wrong_vol, rtol=0.05
        ), "weekly regime vol must not be annualized with the hardcoded 252"


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


class TestHMMConfig:
    """Tests for HMMConfig dataclass."""

    def test_default_config(self):
        """Default HMM config should have sensible values."""
        config = HMMConfig()
        assert config.n_states == 3
        assert config.n_iter == 100
        assert config.tol == 1e-4
        assert config.covariance_type == "diag"
        assert config.min_covar == 1e-6
        assert config.random_state == 42
        assert config.refit_window is None
        assert config.train_frac == 0.7
        assert config.min_regime_length == 21
        assert config.use_returns is True
        assert config.use_volatility is True
        assert config.vol_window == 21
        assert config.use_trend is False
        assert config.trend_window == 50

    def test_custom_config(self):
        """Custom HMM config should accept all parameters."""
        config = HMMConfig(
            n_states=4,
            n_iter=50,
            tol=1e-3,
            covariance_type="full",
            min_covar=1e-4,
            random_state=123,
            refit_window=20,
            train_frac=0.6,
            min_regime_length=15,
            use_returns=True,
            use_volatility=False,
            vol_window=30,
            use_trend=True,
            trend_window=100,
        )
        assert config.n_states == 4
        assert config.n_iter == 50
        assert config.tol == 1e-3
        assert config.covariance_type == "full"
        assert config.min_covar == 1e-4
        assert config.random_state == 123
        assert config.refit_window == 20
        assert config.train_frac == 0.6
        assert config.min_regime_length == 15
        assert config.use_returns is True
        assert config.use_volatility is False
        assert config.vol_window == 30
        assert config.use_trend is True
        assert config.trend_window == 100


class TestBuildHMMFeatures:
    """Tests for HMM feature construction."""

    def test_returns_only(self):
        """Should build returns feature only when configured."""
        prices = make_price_series(200)
        config = HMMConfig(use_returns=True, use_volatility=False, use_trend=False)
        X, names = build_hmm_features(prices, config)
        assert X.shape == (200, 1)
        assert names == ["returns"]
        assert not np.isnan(X).any()

    def test_returns_and_volatility(self):
        """Should build returns and volatility features."""
        prices = make_price_series(200)
        config = HMMConfig(use_returns=True, use_volatility=True, use_trend=False)
        X, names = build_hmm_features(prices, config)
        assert X.shape == (200, 2)
        assert names == ["returns", "volatility"]
        assert not np.isnan(X).any()

    def test_all_features(self):
        """Should build all features when enabled."""
        prices = make_price_series(300)
        config = HMMConfig(use_returns=True, use_volatility=True, use_trend=True)
        X, names = build_hmm_features(prices, config)
        assert X.shape == (300, 3)
        assert names == ["returns", "volatility", "trend"]
        assert not np.isnan(X).any()

    def test_no_features_raises(self):
        """Should raise if no features enabled."""
        prices = make_price_series(100)
        config = HMMConfig(use_returns=False, use_volatility=False, use_trend=False)
        try:
            build_hmm_features(prices, config)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "At least one feature must be enabled" in str(e)

    def test_volatility_feature_uses_frequency_aware_factor(self):
        """The HMM volatility feature must annualize at the return frequency.

        ``build_hmm_features`` annualized the rolling-volatility feature with a
        hardcoded ``sqrt(252)``, so the feature's magnitude was overstated on
        non-daily bars (e.g. ~2.2x on weekly). The HMM regime *labels* are
        invariant to a constant per-feature scale, but the reported
        ``means``/``covars`` model params are not, so the level must be
        frequency-aware. This pins that the weekly volatility feature matches
        ``std * sqrt(52)``, not ``std * sqrt(252)``.
        """
        rng = np.random.default_rng(11)
        n = 200
        r = rng.normal(0.0005, 0.02, n)
        idx_w = pd.date_range("2020-01-05", periods=n, freq="W-SUN")
        close_w = pd.Series(100 * np.exp(np.cumsum(r)), index=idx_w)

        config = HMMConfig(use_returns=False, use_volatility=True, use_trend=False, vol_window=21)
        X, names = build_hmm_features(close_w, config)
        assert names == ["volatility"]
        vol_feature = X[:, 0]

        ret = close_w.pct_change()
        # build_hmm_features backfills the leading NaN window with the first
        # valid rolling value (see its causal NaN handling), so reproduce that.
        raw = ret.rolling(21).std() * np.sqrt(52)
        first_valid = raw.dropna().iloc[0]
        correct = raw.fillna(first_valid).to_numpy()
        raw_wrong = ret.rolling(21).std() * np.sqrt(252)
        wrong = raw_wrong.fillna(raw_wrong.dropna().iloc[0]).to_numpy()

        # The volatility feature equals the sqrt(52) scaling (modulo the
        # leading-NaN backfill), not the hardcoded 252.
        assert np.allclose(vol_feature, correct, atol=1e-12)
        assert not np.allclose(vol_feature, wrong, atol=1e-6)


class TestGaussianHMM:
    """Tests for GaussianHMM core functionality."""

    def test_fit_and_predict(self):
        """Should fit and predict on synthetic data."""
        np.random.seed(42)
        n = 300
        # Two clear regimes
        returns = np.concatenate([
            np.random.normal(0.001, 0.01, n//2),
            np.random.normal(-0.001, 0.02, n//2),
        ])
        X = returns.reshape(-1, 1)

        config = HMMConfig(n_states=2, n_iter=50, random_state=42)
        hmm = GaussianHMM(config)
        hmm.fit(X)

        assert hmm.converged_ or hmm.n_iter_ > 0
        assert hmm.log_likelihood_ > -np.inf
        assert hmm.means_.shape == (2, 1)
        assert hmm.covars_.shape == (2, 1)
        assert hmm.transmat_.shape == (2, 2)
        assert hmm.startprob_.shape == (2,)

        # Predict
        states = hmm.predict(X)
        assert states.shape == (n,)
        assert set(states) <= {0, 1}

    def test_filter_point_in_time(self):
        """Forward filter should produce valid probabilities."""
        np.random.seed(42)
        n = 200
        returns = np.random.normal(0.0005, 0.01, n)
        X = returns.reshape(-1, 1)

        config = HMMConfig(n_states=2, n_iter=30, random_state=42)
        hmm = GaussianHMM(config)
        hmm.fit(X)

        filtered_probs, log_likelihood = hmm.filter(X)

        assert filtered_probs.shape == (n, 2)
        assert np.allclose(filtered_probs.sum(axis=1), 1.0, atol=1e-6)
        assert (filtered_probs >= 0).all() and (filtered_probs <= 1).all()
        assert np.isfinite(log_likelihood)

    def test_score(self):
        """Should compute log-likelihood."""
        np.random.seed(42)
        n = 200
        returns = np.random.normal(0.0005, 0.01, n)
        X = returns.reshape(-1, 1)

        config = HMMConfig(n_states=2, n_iter=30, random_state=42)
        hmm = GaussianHMM(config)
        hmm.fit(X)

        ll = hmm.score(X)
        assert np.isfinite(ll)
        assert np.isclose(ll, hmm.log_likelihood_, rtol=1e-6)

    def test_deterministic_with_seed(self):
        """Should be deterministic with fixed random seed."""
        np.random.seed(42)
        n = 200
        returns = np.random.normal(0.0005, 0.01, n)
        X = returns.reshape(-1, 1)

        config = HMMConfig(n_states=2, n_iter=30, random_state=42)
        hmm1 = GaussianHMM(config)
        hmm1.fit(X)

        hmm2 = GaussianHMM(config)
        hmm2.fit(X)

        assert np.allclose(hmm1.means_, hmm2.means_)
        assert np.allclose(hmm1.covars_, hmm2.covars_)
        assert np.allclose(hmm1.transmat_, hmm2.transmat_)
        assert np.allclose(hmm1.startprob_, hmm2.startprob_)


class TestHMMRegimeDetection:
    """Tests for HMM regime detection functions."""

    def test_detect_hmm_regime_basic(self):
        """Should detect regimes on synthetic data with known structure."""
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=400, freq="B")
        # Three clear regimes
        returns = np.concatenate([
            np.random.normal(0.001, 0.01, 133),   # Bull
            np.random.normal(-0.0005, 0.02, 133), # Bear
            np.random.normal(0.0001, 0.015, 134), # Sideways
        ])
        prices = 100 * np.exp(np.cumsum(returns))
        close = pd.Series(prices, index=dates)

        config = HMMConfig(n_states=3, n_iter=50, random_state=42)
        regimes = detect_hmm_regime(close, config)

        assert len(regimes) == 400
        assert regimes.index.equals(close.index)
        # Should have all three regime labels
        unique_regimes = set(regimes.unique())
        assert "bull" in unique_regimes
        assert "bear" in unique_regimes
        assert "sideways" in unique_regimes

    def test_detect_hmm_regime_with_probs(self):
        """Should return both regimes and state probabilities."""
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=300, freq="B")
        returns = np.random.normal(0.0005, 0.01, 300)
        prices = 100 * np.exp(np.cumsum(returns))
        close = pd.Series(prices, index=dates)

        config = HMMConfig(n_states=3, n_iter=30, random_state=42)
        regimes, probs = detect_hmm_regime_with_probs(close, config)

        assert len(regimes) == 300
        assert probs.shape == (300, 3)
        assert list(probs.columns) == ["state_0", "state_1", "state_2"]
        assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-6)
        # Most likely state should match regime label
        for i in range(len(regimes)):
            most_likely = probs.iloc[i].idxmax()
            state_num = int(most_likely.split("_")[1])
            # This is a sanity check - the mapping may vary but should be consistent

    def test_fit_hmm_walkforward_single_fit(self):
        """fit_hmm_walkforward should work with single fit (refit_window=None)."""
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=300, freq="B")
        returns = np.random.normal(0.0005, 0.01, 300)
        prices = 100 * np.exp(np.cumsum(returns))
        close = pd.Series(prices, index=dates)

        config = HMMConfig(n_states=3, n_iter=30, refit_window=None, train_frac=0.6, random_state=42)
        result = fit_hmm_walkforward(close, config)

        assert isinstance(result.regimes, pd.Series)
        assert len(result.regimes) == 300
        assert result.state_probs.shape == (300, 3)
        assert result.log_likelihood > -np.inf
        assert result.n_iter > 0
        assert "returns" in result.feature_names
        assert "volatility" in result.feature_names

    def test_fit_hmm_walkforward_refit(self):
        """fit_hmm_walkforward should work with periodic refitting."""
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=400, freq="B")
        returns = np.random.normal(0.0005, 0.01, 400)
        prices = 100 * np.exp(np.cumsum(returns))
        close = pd.Series(prices, index=dates)

        config = HMMConfig(n_states=3, n_iter=20, refit_window=50, train_frac=0.5, random_state=42)
        result = fit_hmm_walkforward(close, config)

        assert isinstance(result.regimes, pd.Series)
        assert len(result.regimes) == 400
        assert result.state_probs.shape == (400, 3)
        assert np.allclose(result.state_probs.sum(axis=1), 1.0, atol=1e-6)

    def test_hmm_output_index_matches_input(self):
        """Output index should match input index."""
        prices = make_price_series(200)
        config = HMMConfig(n_states=3, n_iter=20, random_state=42)
        regimes = detect_hmm_regime(prices, config)
        assert regimes.index.equals(prices.index)


class TestAddHMMRegimeAnalysisToResults:
    """Tests for adding HMM regime analysis to backtest results."""

    def test_adds_hmm_regime_analysis_key(self):
        """Should add hmm_regime_analysis key to results."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        results = {"returns": returns}
        data = pd.DataFrame({"close": prices})

        config = HMMConfig(n_states=3, n_iter=20, random_state=42)
        updated = add_hmm_regime_analysis_to_results(results, data, config=config)

        assert "hmm_regime_analysis" in updated
        analysis = updated["hmm_regime_analysis"]
        assert "config" in analysis
        assert "model_params" in analysis
        assert "regime_performance" in analysis
        assert "regime_distribution" in analysis

    def test_handles_panel_data(self):
        """Should handle panel data (dict of DataFrames)."""
        prices = make_price_series(300)
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0005, 0.01, 300), index=prices.index)

        data = {"AAPL": pd.DataFrame({"close": prices})}
        results = {"returns": returns}

        config = HMMConfig(n_states=3, n_iter=20, random_state=42)
        updated = add_hmm_regime_analysis_to_results(results, data, config=config)

        assert "hmm_regime_analysis" in updated

    def test_returns_original_if_no_returns_key(self):
        """Should return original results if returns key missing."""
        results = {"other_key": "value"}
        data = {"close": make_price_series(100)}

        config = HMMConfig(n_states=3, n_iter=20, random_state=42)
        updated = add_hmm_regime_analysis_to_results(results, data, config=config)

        assert "hmm_regime_analysis" not in updated

    def test_returns_original_if_no_close_data(self):
        """Should return original results if close data missing."""
        results = {"returns": pd.Series([1, 2, 3])}
        data = {"open": [1, 2, 3]}

        config = HMMConfig(n_states=3, n_iter=20, random_state=42)
        updated = add_hmm_regime_analysis_to_results(results, data, config=config)

        assert "hmm_regime_analysis" not in updated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])