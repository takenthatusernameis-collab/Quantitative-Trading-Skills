#!/usr/bin/env python3
"""Focused tests for the Probabilistic Sharpe Ratio (PSR).

PSR (Bailey & Lopez de Prado, 2012) estimates the probability that a
strategy's true Sharpe exceeds a benchmark Sharpe, adjusting for
non-normal returns (skew/kurtosis) and finite sample size. It does NOT
correct for multiple testing across strategy trials (that is the DSR).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import probabilistic_sharpe_ratio  # noqa: E402
from performance import calculate_metrics, generate_report  # noqa: E402


def _returns(n=252, mu=0.0006, sigma=0.01, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(mu, sigma, n), index=dates)


def test_psr_returns_required_keys_and_bounds():
    psr = probabilistic_sharpe_ratio(1.2, _returns())
    for key in (
        "probabilistic_sharpe_ratio",
        "p_value",
        "sharpe_ratio",
        "benchmark_sharpe",
        "z_score",
        "n_observations",
        "skewness",
        "kurtosis",
    ):
        assert key in psr, key
    assert 0.0 <= psr["probabilistic_sharpe_ratio"] <= 1.0
    assert 0.0 <= psr["p_value"] <= 1.0
    assert abs(psr["p_value"] - (1.0 - psr["probabilistic_sharpe_ratio"])) < 1e-12
    assert psr["n_observations"] == 252
    assert psr["benchmark_sharpe"] == 0.0


def test_psr_higher_sharpe_gives_higher_confidence():
    rets = _returns(n=504, mu=0.0005, sigma=0.01, seed=11)
    low = probabilistic_sharpe_ratio(0.3, rets)["probabilistic_sharpe_ratio"]
    high = probabilistic_sharpe_ratio(1.5, rets)["probabilistic_sharpe_ratio"]
    assert high > low


def test_psr_higher_benchmark_lowers_confidence():
    rets = _returns(n=504, mu=0.0005, sigma=0.01, seed=13)
    vs_zero = probabilistic_sharpe_ratio(1.0, rets, benchmark_sharpe=0.0)[
        "probabilistic_sharpe_ratio"
    ]
    vs_one = probabilistic_sharpe_ratio(1.0, rets, benchmark_sharpe=1.0)[
        "probabilistic_sharpe_ratio"
    ]
    vs_high = probabilistic_sharpe_ratio(1.0, rets, benchmark_sharpe=2.0)[
        "probabilistic_sharpe_ratio"
    ]
    assert vs_zero > vs_one > vs_high


def test_psr_constant_returns_are_degenerate():
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    rets = pd.Series(np.full(100, 0.001), index=dates)
    psr = probabilistic_sharpe_ratio(5.0, rets)
    # Constant returns carry no information about skill.
    assert psr["probabilistic_sharpe_ratio"] == 0.0
    assert psr["p_value"] == 1.0
    assert psr["z_score"] is None


def test_calculate_metrics_surfaces_probabilistic_sharpe():
    rets = _returns()
    metrics = calculate_metrics({"returns": rets})
    assert "probabilistic_sharpe" in metrics
    psr = metrics["probabilistic_sharpe"]
    assert 0.0 <= psr["probabilistic_sharpe_ratio"] <= 1.0
    # DSR is absent without n_trials, but PSR is still present.
    assert "deflated_sharpe" not in metrics


def test_calculate_metrics_surfaces_both_psr_and_dsr_when_trials_reported():
    rets = _returns()
    metrics = calculate_metrics({"returns": rets, "config": {"n_trials": 25}})
    assert "probabilistic_sharpe" in metrics
    assert "deflated_sharpe" in metrics


def test_generate_report_includes_probabilistic_sharpe_section(tmp_path):
    rets = _returns()
    metrics = calculate_metrics({"returns": rets})
    # generate_report writes report.txt (and metrics.json) into output_path dir.
    generate_report(metrics, str(tmp_path), symbol="TST", strategy_name="Unit")
    text = (tmp_path / "report.txt").read_text()
    assert "Probabilistic Sharpe" in text
    assert "P-Value (vs SR*)" in text or "P-Value" in text


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
