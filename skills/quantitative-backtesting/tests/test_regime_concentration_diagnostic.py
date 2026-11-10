#!/usr/bin/env python3
"""Regression guards for the regime-concentration robustness diagnostic.

The diagnostic inspects ``regime_analysis`` and classifies whether a
strategy's edge is diversified across market regimes or concentrated in a
single one. A single-regime edge is regime-dependent and may not survive a
regime change. Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import regime_concentration_diagnostic  # noqa: E402


def _regime_analysis(combined, distribution=None):
    """Build a regime_analysis dict matching regime_performance_summary output."""
    return {
        "config": {"min_regime_length": 21},
        "combined_regime_performance": combined,
        "regime_distribution": distribution or {
            regime: metrics["n_observations"] for regime, metrics in combined.items()
        },
    }


def _perf(sharpe_ratio, n_observations=100):
    return {"n_observations": n_observations, "sharpe_ratio": sharpe_ratio}


def test_robust_when_multiple_positive_regimes_narrow_spread():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.2),
        "bear_high_vol": _perf(0.9),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["regime_robustness"] == "robust"
    assert result["is_regime_concentrated"] is False
    assert result["n_regimes_traded"] == 2
    assert result["n_regimes_positive"] == 2


def test_fragile_when_edge_in_single_regime():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.5),
        "bear_high_vol": _perf(-0.8),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["regime_robustness"] == "fragile"
    assert result["is_regime_concentrated"] is True
    assert result["best_regime"] == "bull_low_vol"
    assert result["worst_regime"] == "bear_high_vol"
    assert result["n_regimes_positive"] == 1
    assert result["n_regimes_negative"] == 1


def test_fragile_when_no_positive_regime():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(-0.2),
        "bear_high_vol": _perf(-0.8),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["regime_robustness"] == "fragile"
    assert result["is_regime_concentrated"] is True
    assert result["n_regimes_positive"] == 0


def test_moderate_when_multiple_positive_regimes_wide_spread():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(2.0),
        "bear_high_vol": _perf(0.1),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["regime_robustness"] == "moderate"
    assert result["is_regime_concentrated"] is False
    assert result["n_regimes_positive"] == 2


def test_insufficient_data_when_fewer_than_two_traded_regimes():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.2),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["regime_robustness"] == "insufficient_data"
    assert result["is_regime_concentrated"] is False
    assert result["n_regimes_traded"] == 1


def test_unknown_regime_excluded():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.2),
        "unknown": _perf(0.5, n_observations=200),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["n_regimes_traded"] == 1
    assert result["regime_robustness"] == "insufficient_data"


def test_short_regime_excluded_by_min_length():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.2),
        "bear_high_vol": _perf(-1.0, n_observations=5),
    })
    result = regime_concentration_diagnostic(analysis, min_regime_length=21)
    assert result["n_regimes_traded"] == 1
    assert result["regime_robustness"] == "insufficient_data"


def test_handles_none_and_empty_input():
    assert regime_concentration_diagnostic(None)["regime_robustness"] == "insufficient_data"
    assert regime_concentration_diagnostic({})["regime_robustness"] == "insufficient_data"


def test_sharpe_spread_and_extremes_recorded():
    analysis = _regime_analysis({
        "bull_low_vol": _perf(1.5),
        "bear_high_vol": _perf(-0.5),
    })
    result = regime_concentration_diagnostic(analysis)
    assert result["best_regime"] == "bull_low_vol"
    assert result["best_sharpe"] == 1.5
    assert result["worst_regime"] == "bear_high_vol"
    assert result["worst_sharpe"] == -0.5
    assert result["sharpe_spread"] == 2.0
    assert result["regime_sharpes"] == {"bull_low_vol": 1.5, "bear_high_vol": -0.5}
    assert result["dominant_regime"] in ("bull_low_vol", "bear_high_vol")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
