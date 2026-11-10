#!/usr/bin/env python3
"""Focused unit tests for the Deflated Sharpe Ratio (DSR).

The DSR (Bailey & Lopez de Prado, 2014) corrects an estimated Sharpe ratio
for multiple testing across strategy trials and for non-normal returns
(skew/kurtosis). It is the statistical heart of the
``deflated_sharpe_pvalue < 0.10`` falsification criterion used across the
hypothesis examples, so its arithmetic must be pinned directly rather than
inferred only from end-to-end presence checks.

Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import deflated_sharpe_ratio  # noqa: E402


def _returns(n=252, mu=0.0006, sigma=0.01, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(mu, sigma, n), index=dates)


def test_dsr_returns_required_keys_and_bounds():
    dsr = deflated_sharpe_ratio(1.0, _returns(), n_trials=25)
    for key in (
        "deflated_sharpe_ratio",
        "p_value",
        "sharpe_ratio",
        "expected_max_sharpe",
        "z_score",
        "n_trials",
        "n_observations",
        "skewness",
        "kurtosis",
    ):
        assert key in dsr, key
    assert 0.0 <= dsr["deflated_sharpe_ratio"] <= 1.0
    assert 0.0 <= dsr["p_value"] <= 1.0
    assert abs(dsr["p_value"] - (1.0 - dsr["deflated_sharpe_ratio"])) < 1e-12
    assert dsr["n_trials"] == 25
    assert dsr["n_observations"] == 252
    assert dsr["sharpe_ratio"] == 1.0


def test_dsr_higher_sharpe_gives_higher_confidence():
    rets = _returns(n=504, mu=0.0005, sigma=0.01, seed=11)
    low = deflated_sharpe_ratio(0.3, rets, n_trials=25)["deflated_sharpe_ratio"]
    high = deflated_sharpe_ratio(1.5, rets, n_trials=25)["deflated_sharpe_ratio"]
    assert high > low


def test_dsr_more_trials_deflates_confidence():
    # Core multiple-testing property: testing more configurations makes it
    # harder to attribute an attractive Sharpe to skill, so DSR must fall.
    rets = _returns(n=504, mu=0.0005, sigma=0.01, seed=13)
    few = deflated_sharpe_ratio(1.0, rets, n_trials=5)["deflated_sharpe_ratio"]
    many = deflated_sharpe_ratio(1.0, rets, n_trials=5000)[
        "deflated_sharpe_ratio"
    ]
    assert many < few


def test_dsr_constant_returns_are_degenerate():
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    rets = pd.Series(np.full(100, 0.001), index=dates)
    dsr = deflated_sharpe_ratio(5.0, rets, n_trials=10)
    # Constant returns carry no information about skill.
    assert dsr["deflated_sharpe_ratio"] == 0.0
    assert dsr["p_value"] == 1.0
    assert dsr["z_score"] is None


def test_dsr_trial_sharpes_path_uses_trial_dispersion():
    # When trial_sharpes is provided, SR* is estimated from the
    # cross-sectional dispersion of trial Sharpes rather than the i.i.d.
    # normal null approximation; both paths must yield valid, bounded DSR.
    rets = _returns(n=504, mu=0.0005, sigma=0.01, seed=17)
    trial_sharpes = [0.2, 0.5, 0.8, 1.1, 1.4]
    with_trials = deflated_sharpe_ratio(
        1.0, rets, n_trials=len(trial_sharpes), trial_sharpes=trial_sharpes
    )
    without_trials = deflated_sharpe_ratio(1.0, rets, n_trials=len(trial_sharpes))
    for dsr in (with_trials, without_trials):
        assert 0.0 <= dsr["deflated_sharpe_ratio"] <= 1.0
        assert dsr["expected_max_sharpe"] > 0


def test_dsr_rejects_invalid_inputs():
    rets = _returns()
    try:
        deflated_sharpe_ratio(1.0, rets, n_trials=0)
        raise AssertionError("expected ValueError for n_trials < 1")
    except ValueError:
        pass
    short = pd.Series([0.001], index=pd.date_range("2020-01-01", periods=1, freq="B"))
    try:
        deflated_sharpe_ratio(1.0, short, n_trials=5)
        raise AssertionError("expected ValueError for < 2 observations")
    except ValueError:
        pass


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
