#!/usr/bin/env python3
"""
Unit tests for performance.py: metric calculation and annualization.

Run with: python3 skills/quantitative-backtesting/tests/test_performance.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from performance import _annualization_factor, calculate_metrics  # noqa: E402


def _make_returns(periods: int = 10, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.Series(rng.normal(0.0005, 0.015, periods), index=dates)


def test_calculate_metrics_empty_returns_returns_error():
    """calculate_metrics({}) returns the standard error dict."""
    metrics = calculate_metrics({})
    assert metrics == {"error": "No returns data available for metric calculation"}


def test_total_return_matches_compound_returns():
    """total_return equals (1 + returns).prod() - 1 exactly."""
    returns = _make_returns()
    expected = float((1 + returns).prod() - 1)
    metrics = calculate_metrics({"returns": returns})
    assert abs(metrics["total_return"] - expected) < 1e-12


def test_trade_analytics_populated():
    """With a trades list, total_trades and win_rate are computed."""
    returns = _make_returns()
    metrics = calculate_metrics(
        {"returns": returns, "trades": [{"pnl": 100}, {"pnl": -50}]}
    )
    assert metrics["total_trades"] == 2
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 1
    assert metrics["win_rate"] == 0.5


def test_annualization_factors():
    """_annualization_factor maps known frequencies and defaults to 252."""
    cases = {
        "B": 252,
        "D": 365,
        "W": 52,
        "ME": 12,
        "QE-DEC": 4,
    }
    for freq, expected in cases.items():
        idx = pd.date_range("2020-01-01", periods=10, freq=freq)
        assert _annualization_factor(idx) == expected, (
            f"{freq}: expected {expected}, got {_annualization_factor(idx)}"
        )


def test_annualization_factor_non_datetime_index():
    """Non-DatetimeIndex defaults to 252 trading days."""
    assert _annualization_factor(pd.Index(range(10))) == 252


def main() -> int:
    tests = [
        ("calculate_metrics_empty_returns_returns_error", test_calculate_metrics_empty_returns_returns_error),
        ("total_return_matches_compound_returns", test_total_return_matches_compound_returns),
        ("trade_analytics_populated", test_trade_analytics_populated),
        ("annualization_factors", test_annualization_factors),
        ("annualization_factor_non_datetime_index", test_annualization_factor_non_datetime_index),
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