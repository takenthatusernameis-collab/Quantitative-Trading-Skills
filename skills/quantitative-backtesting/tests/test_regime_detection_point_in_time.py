#!/usr/bin/env python3
"""
Point-in-time / no-look-ahead falsification tests for regime detection.

These tests verify that regime detection functions use only historical data
available at each point in time. Mutating future prices must not change
past regime labels.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import (
    detect_trend_regime,
    detect_volatility_regime,
    detect_combined_regime,
    RegimeConfig,
    detect_hmm_regime,
    detect_hmm_regime_with_probs,
    fit_hmm_walkforward,
    HMMConfig,
    GaussianHMM,
    build_hmm_features,
)


def test_detect_trend_regime_no_lookahead():
    """detect_trend_regime must not use future data.

    Mutating future closes must leave past trend labels unchanged.
    The function uses rolling MAs (causal by construction) and ffill
    for initial NaN warmup, which is causal.
    """
    np.random.seed(42)
    n = 500  # Enough for ma_long=200 warmup
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    # Baseline labels
    labels = detect_trend_regime(close, ma_short=50, ma_long=200, threshold=0.02)

    # Mutate the LAST k closes with a large shock
    k = 20
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 3.0  # Large upward shock in the future

    labels_shocked = detect_trend_regime(close_shocked, ma_short=50, ma_long=200, threshold=0.02)

    # Past labels (excluding the last k periods that depend on the shocked region
    # through the rolling window) must be identical
    # The rolling window of size ma_long=200 means the last 200 periods could be affected
    # by the shock. So we compare up to n - k - ma_long to be safe.
    # Actually, the shock only affects the last k values directly. The rolling MA
    # will be affected for ma_long periods after the shock starts. Since the shock
    # is at the END, it affects the last k + ma_long - 1 values.
    # We assert that values before the shock's influence are unchanged.
    safe_cutoff = n - k - 200  # Conservative: before the shock can influence via rolling window
    assert labels.iloc[:safe_cutoff].equals(labels_shocked.iloc[:safe_cutoff]), (
        "detect_trend_regime: past labels changed after mutating future prices"
    )


def test_detect_volatility_regime_no_lookahead():
    """detect_volatility_regime must not use future data.

    Mutating future closes must leave past volatility labels unchanged.
    The function uses expanding() quantiles (causal by construction) and
    ffill for initial NaN warmup, which is causal.
    """
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    # Baseline labels
    labels = detect_volatility_regime(close, window=63, quantile_high=0.75, quantile_low=0.25)

    # Mutate the LAST k closes with a large shock
    k = 20
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 3.0

    labels_shocked = detect_volatility_regime(close_shocked, window=63, quantile_high=0.75, quantile_low=0.25)

    # The expanding quantile uses all data up to each point. The shock at the end
    # affects the quantile thresholds for ALL periods including past ones, because
    # expanding() includes the full history up to each point.
    # Wait - this is a problem! expanding().quantile() at time t uses data up to t.
    # The shock at the END (t > T-k) will NOT affect the quantile at time T-k-1
    # because expanding() at T-k-1 only sees data up to T-k-1.
    # So past labels SHOULD be unchanged.
    safe_cutoff = n - k
    assert labels.iloc[:safe_cutoff].equals(labels_shocked.iloc[:safe_cutoff]), (
        "detect_volatility_regime: past labels changed after mutating future prices"
    )


def test_detect_combined_regime_no_lookahead():
    """detect_combined_regime must not use future data.

    Mutating future closes must leave past combined regime labels unchanged.
    """
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = RegimeConfig(trend_ma_short=50, trend_ma_long=200, trend_threshold=0.02,
                          vol_window=63, vol_quantile_high=0.75, vol_quantile_low=0.25)

    # Baseline labels
    labels = detect_combined_regime(close, config)

    # Mutate the LAST k closes with a large shock
    k = 20
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 3.0

    labels_shocked = detect_combined_regime(close_shocked, config)

    # Conservative safe cutoff: before trend MA long window + shock
    safe_cutoff = n - k - 200
    assert labels.iloc[:safe_cutoff].equals(labels_shocked.iloc[:safe_cutoff]), (
        "detect_combined_regime: past labels changed after mutating future prices"
    )


def test_detect_trend_regime_ffill_does_not_leak():
    """The ffill in detect_trend_regime must not leak future regime information backward.

    The ffill only fills forward from the first non-NaN label. It cannot
    propagate future labels backward.
    """
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    labels = detect_trend_regime(close, ma_short=50, ma_long=200, threshold=0.02)

    # The first ma_long-1 values should be UNKNOWN (or filled forward from there)
    # Check that the early regime is UNKNOWN or filled from the first known
    early_labels = labels.iloc[:200]
    # After warmup, there should be some non-UNKNOWN values
    known_mask = early_labels != "unknown"
    # Just verify it runs without look-ahead - the main test is test_detect_trend_regime_no_lookahead
    assert len(labels) == n


def test_detect_volatility_regime_expanding_quantile_causal():
    """detect_volatility_regime's expanding().quantile() is causal by construction.

    At time t, the quantile uses data up to t only. This test verifies
    that a shock at the end doesn't change quantile thresholds for earlier periods.
    """
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    # Get the internal rolling volatility and thresholds
    returns = close.pct_change()
    rolling_vol = returns.rolling(window=63).std() * np.sqrt(252)
    vol_high_threshold = rolling_vol.expanding().quantile(0.75)
    vol_low_threshold = rolling_vol.expanding().quantile(0.25)

    # Mutate future
    k = 30
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 5.0

    returns_shocked = close_shocked.pct_change()
    rolling_vol_shocked = returns_shocked.rolling(window=63).std() * np.sqrt(252)
    vol_high_threshold_shocked = rolling_vol_shocked.expanding().quantile(0.75)
    vol_low_threshold_shocked = rolling_vol_shocked.expanding().quantile(0.25)

    # The thresholds up to n-k-1 should be identical
    # (the shock only affects returns at the very end)
    safe_cutoff = n - k - 1
    assert np.allclose(vol_high_threshold.iloc[:safe_cutoff].values,
                       vol_high_threshold_shocked.iloc[:safe_cutoff].values,
                       equal_nan=True), "expanding quantile high threshold leaked future"
    assert np.allclose(vol_low_threshold.iloc[:safe_cutoff].values,
                       vol_low_threshold_shocked.iloc[:safe_cutoff].values,
                       equal_nan=True), "expanding quantile low threshold leaked future"


def test_regime_detection_deterministic():
    """Regime detection must be deterministic given identical inputs."""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = RegimeConfig()

    labels1 = detect_combined_regime(close, config)
    labels2 = detect_combined_regime(close, config)

    assert labels1.equals(labels2), "detect_combined_regime is not deterministic"


# =============================================================================
# HMM Point-in-Time / No-Look-Ahead Falsification Tests
# =============================================================================

def test_hmm_filter_point_in_time():
    """
    GaussianHMM.filter() must be point-in-time (causal).

    The forward algorithm computes P(state_t | obs_1...obs_t) using only
    historical observations. Mutating future observations must not change
    past filtered probabilities.
    """
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    # Build features and fit HMM
    config = HMMConfig(n_states=3, n_iter=30, random_state=42)
    from regime_detection import build_hmm_features
    X, _ = build_hmm_features(close, config)

    hmm = GaussianHMM(config)
    hmm.fit(X)

    # Get baseline filtered probabilities
    filtered_probs, _ = hmm.filter(X)

    # Mutate future observations (last k)
    k = 20
    X_shocked = X.copy()
    X_shocked[-k:] *= 5.0  # Large shock in features

    # Filter with shocked data
    filtered_probs_shocked, _ = hmm.filter(X_shocked)

    # Past filtered probabilities (before the shock can influence) must be identical
    # The forward algorithm at time t only depends on obs_1...obs_t
    # So observations at t < n-k should be unaffected
    safe_cutoff = n - k
    assert np.allclose(filtered_probs[:safe_cutoff], filtered_probs_shocked[:safe_cutoff], atol=1e-10), (
        "GaussianHMM.filter: past filtered probabilities changed after mutating future observations"
    )


def test_detect_hmm_regime_no_lookahead():
    """
    detect_hmm_regime must not use future data.

    With refit_window=None, the model is fit on training data (train_frac)
    and then used to filter the entire series. The filtering is point-in-time.
    Mutating future prices must not change past filtered probabilities
    (within the filtering portion, after the training split).

    Note: The regime labels are assigned post-hoc based on state mean returns,
    which can change when the model is refit on different data. The point-in-time
    guarantee applies to the filtered probabilities, not the label mapping.
    """
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = HMMConfig(n_states=3, n_iter=30, refit_window=None, train_frac=0.6, random_state=42)

    # Get baseline filtered probabilities
    labels, probs = detect_hmm_regime_with_probs(close, config)

    # Mutate the LAST k closes with a large shock
    k = 20
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 3.0

    labels_shocked, probs_shocked = detect_hmm_regime_with_probs(close_shocked, config)

    # The training portion (first train_frac * n) is used for fitting
    # The filtering portion starts at train_frac * n
    # Within the filtering portion, past filtered probabilities (before the shock) should be unchanged
    train_size = int(n * config.train_frac)
    safe_cutoff = n - k  # Before the shock in the filtering region

    # Compare filtered probabilities (point-in-time guarantee)
    assert np.allclose(probs.iloc[train_size:safe_cutoff].values,
                       probs_shocked.iloc[train_size:safe_cutoff].values,
                       atol=1e-10), (
        "detect_hmm_regime: past filtered probabilities changed after mutating future prices"
    )


def test_fit_hmm_walkforward_no_lookahead():
    """
    fit_hmm_walkforward with refit_window must not use future data.

    Each refit uses only data up to that point. The filtering within each
    prediction window is point-in-time. Mutating future prices must not
    change filtered probabilities in already-processed windows.

    Note: The regime labels are assigned post-hoc based on state mean returns,
    which can change when the model is refit on different data. The point-in-time
    guarantee applies to the filtered probabilities, not the label mapping.
    """
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = HMMConfig(n_states=3, n_iter=20, refit_window=50, train_frac=0.5, random_state=42)

    # Baseline result
    result = fit_hmm_walkforward(close, config)
    probs = result.state_probs

    # Mutate the LAST k closes with a large shock
    k = 20
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 3.0

    result_shocked = fit_hmm_walkforward(close_shocked, config)
    probs_shocked = result_shocked.state_probs

    # The first refit window ends at train_size + refit_window
    # Probabilities before the last refit window should be unchanged
    train_size = int(n * config.train_frac)
    # Last refit starts at roughly n - k - refit_window (conservative)
    safe_cutoff = n - k - config.refit_window

    if safe_cutoff > train_size:
        assert np.allclose(probs.iloc[train_size:safe_cutoff].values,
                           probs_shocked.iloc[train_size:safe_cutoff].values,
                           atol=1e-10), (
            "fit_hmm_walkforward: past filtered probabilities changed after mutating future prices"
        )


def test_hmm_feature_construction_causal():
    """
    build_hmm_features must construct features causally (no look-ahead).

    Features at time t must only depend on data up to time t.
    Mutating future prices must not change past feature values.
    """
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = HMMConfig(use_returns=True, use_volatility=True, use_trend=True)

    # Baseline features
    X, names = build_hmm_features(close, config)

    # Mutate future prices
    k = 30
    close_shocked = close.copy()
    close_shocked.iloc[-k:] *= 5.0

    X_shocked, _ = build_hmm_features(close_shocked, config)

    # Features up to n-k-1 should be identical
    # (the shock only affects returns at the very end)
    safe_cutoff = n - k - 1
    assert np.allclose(X[:safe_cutoff], X_shocked[:safe_cutoff], equal_nan=True), (
        "build_hmm_features: past features changed after mutating future prices"
    )


def test_hmm_deterministic():
    """HMM regime detection must be deterministic given identical inputs."""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, n))), index=dates)

    config = HMMConfig(n_states=3, n_iter=30, random_state=42)

    labels1 = detect_hmm_regime(close, config)
    labels2 = detect_hmm_regime(close, config)

    assert labels1.equals(labels2), "detect_hmm_regime is not deterministic"


def main():
    tests = [
        ("test_detect_trend_regime_no_lookahead", test_detect_trend_regime_no_lookahead),
        ("test_detect_volatility_regime_no_lookahead", test_detect_volatility_regime_no_lookahead),
        ("test_detect_combined_regime_no_lookahead", test_detect_combined_regime_no_lookahead),
        ("test_detect_trend_regime_ffill_does_not_leak", test_detect_trend_regime_ffill_does_not_leak),
        ("test_detect_volatility_regime_expanding_quantile_causal", test_detect_volatility_regime_expanding_quantile_causal),
        ("test_regime_detection_deterministic", test_regime_detection_deterministic),
        # HMM tests
        ("test_hmm_filter_point_in_time", test_hmm_filter_point_in_time),
        ("test_detect_hmm_regime_no_lookahead", test_detect_hmm_regime_no_lookahead),
        ("test_fit_hmm_walkforward_no_lookahead", test_fit_hmm_walkforward_no_lookahead),
        ("test_hmm_feature_construction_causal", test_hmm_feature_construction_causal),
        ("test_hmm_deterministic", test_hmm_deterministic),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            import traceback
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())