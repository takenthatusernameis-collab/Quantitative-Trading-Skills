#!/usr/bin/env python3
"""Regression guards for regime-aware volatility-targeting position sizing.

``regime_aware_position_size`` is a position-sizing overlay: it rescales an
existing signal to a per-regime annualized volatility target. These tests pin
the closed-form sizing math, the leverage clips, the unknown-regime policy, and
the point-in-time guarantee (future prices must not change past position
sizes). Offline, synthetic inputs only; no live network.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import regime_aware_position_size  # noqa: E402


def _series(values, name=None):
    index = pd.date_range("2020-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=index, dtype=float, name=name)


def _expected_multiplier(close, regimes, target_by_regime, lookback, periods_per_year=252):
    """Independent recomputation of the documented sizing formula."""
    returns = close.pct_change()
    realized_vol = returns.rolling(window=lookback, min_periods=lookback).std() * np.sqrt(
        periods_per_year
    )
    target = regimes.map(target_by_regime).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (target / realized_vol).clip(lower=0.0, upper=2.0)


def test_closed_form_matches_documented_formula():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0, 101.0, 104.0])
    regimes = _series(["calm", "calm", "storm", "storm", "calm", "storm", "calm", "storm"])
    base = _series([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    targets = {"calm": 0.10, "storm": 0.30}

    sized = regime_aware_position_size(
        base, close, regimes, targets, lookback=3, min_leverage=0.0, max_leverage=2.0
    )

    expected = base * _expected_multiplier(close, regimes, targets, lookback=3)
    assert np.allclose(sized.values, expected.values, atol=1e-12, equal_nan=True), (
        f"sizing drifted from the documented formula: got {sized.values}, "
        f"expected {expected.values}"
    )


def test_higher_target_vol_scales_position_up():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0, 101.0, 104.0])
    base = _series(np.ones(8))
    regimes = _series(["calm"] * 8)
    calm = regime_aware_position_size(
        base, close, regimes, {"calm": 0.10}, lookback=3
    )
    storm = regime_aware_position_size(
        base, close, regimes, {"calm": 0.30}, lookback=3
    )

    valid = calm.notna() & storm.notna()
    assert valid.any()
    assert (storm[valid] >= calm[valid]).all()
    assert storm[valid].max() > calm[valid].max()


def test_leverage_is_clipped_to_max():
    # Alternating returns give a small but non-zero realized vol, so the raw
    # target/vol ratio exceeds the 0.5 cap.
    close = _series([100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
    base = _series(np.ones(6))
    regimes = _series(["calm"] * 6)
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.50}, lookback=3, min_leverage=0.0, max_leverage=0.5
    )
    assert np.allclose(sized.dropna().values, 0.5)


def test_leverage_is_clipped_to_min():
    # A tiny target vol relative to realized vol would give a near-zero
    # multiplier; the 0.5 floor must bind.
    close = _series([100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
    base = _series(np.ones(6))
    regimes = _series(["calm"] * 6)
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.001}, lookback=3, min_leverage=0.5, max_leverage=2.0
    )
    assert np.allclose(sized.dropna().values, 0.5)


def test_zero_realized_vol_uses_max_leverage():
    close = _series([100.0] * 8)
    base = _series(np.ones(8))
    regimes = _series(["calm"] * 8)
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.20}, lookback=3, min_leverage=0.0, max_leverage=2.0
    )
    assert np.allclose(sized.dropna().values, 2.0)


def test_zero_target_with_zero_vol_is_flat_not_nan():
    close = _series([100.0] * 8)
    base = _series(np.ones(8))
    regimes = _series(["calm"] * 8)
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.0}, lookback=3, min_leverage=0.0, max_leverage=2.0
    )
    # Only the first lookback-1 bars are NaN (not enough history); the rest
    # must be an explicit zero position, not 0/0 NaN.
    assert sized.iloc[2:].notna().all()
    assert np.allclose(sized.iloc[2:].values, 0.0)


def test_early_bars_are_nan_until_lookback_is_available():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0])
    base = _series(np.ones(6))
    regimes = _series(["calm"] * 6)
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.20}, lookback=3
    )
    assert sized.iloc[:2].isna().all()
    assert sized.iloc[2:].notna().all()


def test_unknown_regime_raises_without_default():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0])
    base = _series(np.ones(6))
    regimes = _series(["calm", "calm", "storm", "calm", "calm", "calm"])
    with pytest.raises(ValueError, match="no volatility target"):
        regime_aware_position_size(
            base, close, regimes, {"calm": 0.20}, lookback=3
        )


def test_unknown_regime_falls_back_to_default_target():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0])
    base = _series(np.ones(6))
    regimes = _series(["calm", "calm", "storm", "calm", "calm", "calm"])
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.10}, lookback=3, default_target_vol=0.40
    )
    explicit = regime_aware_position_size(
        base,
        close,
        _series(["calm"] * 6),
        {"calm": 0.10},
        lookback=3,
    )
    # The mapped "storm" bar must use the 0.40 default, not the 0.10 calm target.
    assert sized.iloc[2] > explicit.iloc[2]


def test_point_in_time_future_prices_do_not_change_past_sizes():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0, 101.0, 104.0])
    regimes = _series(["calm", "calm", "storm", "storm", "calm", "storm", "calm", "storm"])
    base = _series([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    targets = {"calm": 0.10, "storm": 0.30}

    original = regime_aware_position_size(
        base, close, regimes, targets, lookback=3
    )

    mutated = close.copy()
    mutated.iloc[4:] = mutated.iloc[4:] * 1.5
    after = regime_aware_position_size(base, mutated, regimes, targets, lookback=3)

    # Bars up to and including the last bar before the mutation (index 3)
    # must be unchanged; the trailing window at index 4 already includes the
    # mutated return.
    cutoff = 3
    assert np.allclose(
        original.iloc[: cutoff + 1].values,
        after.iloc[: cutoff + 1].values,
        atol=1e-12,
        equal_nan=True,
    )


def test_preserves_base_direction_when_target_positive():
    close = _series([100.0, 101.0, 99.0, 102.0, 100.0, 103.0, 101.0, 104.0])
    regimes = _series(["calm"] * 8)
    base = _series([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    sized = regime_aware_position_size(
        base, close, regimes, {"calm": 0.20}, lookback=3, min_leverage=0.0
    )
    valid = sized.dropna()
    assert (np.sign(valid.values) == np.sign(base.loc[valid.index].values)).all()


def test_invalid_arguments_raise():
    close = _series([100.0, 101.0, 99.0, 102.0])
    base = _series(np.ones(4))
    regimes = _series(["calm"] * 4)
    targets = {"calm": 0.20}

    with pytest.raises(ValueError, match="lookback"):
        regime_aware_position_size(base, close, regimes, targets, lookback=0)
    with pytest.raises(ValueError, match="min_leverage"):
        regime_aware_position_size(
            base, close, regimes, targets, lookback=2, min_leverage=1.0, max_leverage=0.5
        )
    with pytest.raises(ValueError, match="must not be empty"):
        regime_aware_position_size(base, close, regimes, {}, lookback=2)
    with pytest.raises(ValueError, match="non-negative"):
        regime_aware_position_size(
            base, close, regimes, {"calm": -0.10}, lookback=2
        )
    with pytest.raises(ValueError, match="share no common index"):
        regime_aware_position_size(
            base,
            close,
            _series(["calm"] * 4).set_axis(pd.date_range("2021-01-01", periods=4, freq="B")),
            targets,
            lookback=2,
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))