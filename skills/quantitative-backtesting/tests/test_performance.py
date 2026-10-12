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


def test_trade_metrics_use_return_for_avg_win_loss():
    """avg_win/avg_loss are return fractions, not PnL currency amounts.

    Regression test for a defect where avg_win/avg_loss were computed from
    `pnl` (currency) and then formatted as percent, producing impossible
    values like 577%. With pnl=1000 and return=0.01, avg_win must be 0.01
    (1%), not 1000 (100000%).
    """
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["avg_win"] - 0.01) < 1e-12
    assert abs(metrics["avg_loss"] - 0.005) < 1e-12
    assert metrics["avg_win"] < 1.0
    assert metrics["avg_loss"] < 1.0


def test_profit_factor_uses_pnl_gross_profit_over_gross_loss():
    """profit_factor = sum(pnl>0) / abs(sum(pnl<0)), per metrics_definitions.md."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -400, "return": -0.004, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
        {"pnl": 300, "return": 0.003, "entry_date": "2020-01-11", "exit_date": "2020-01-15"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["profit_factor"] - (1300 / 400)) < 1e-12


def test_expectancy_is_mean_pnl():
    """expectancy = mean(pnl) in currency units."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["expectancy"] - 250.0) < 1e-12


def test_avg_trade_duration_is_calendar_days():
    """avg_trade_duration is the mean of (exit_date - entry_date).days."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["avg_trade_duration"] == 4.0


def test_trade_metrics_handle_missing_return_field():
    """A trade without a `return` key must not break avg_win/avg_loss."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["total_trades"] == 2
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 1
    assert metrics["avg_win"] == 0.0  # no return on the winning trade
    assert abs(metrics["avg_loss"] - 0.005) < 1e-12


def test_trade_metrics_absent_when_no_trades():
    """With no trades, trade-level keys must be absent (not zeroed)."""
    metrics = calculate_metrics({"returns": _make_returns()})
    for key in ("total_trades", "avg_win", "avg_loss", "profit_factor", "expectancy", "avg_trade_duration"):
        assert key not in metrics


def main() -> int:
    tests = [
        ("calculate_metrics_empty_returns_returns_error", test_calculate_metrics_empty_returns_returns_error),
        ("total_return_matches_compound_returns", test_total_return_matches_compound_returns),
        ("trade_analytics_populated", test_trade_analytics_populated),
        ("annualization_factors", test_annualization_factors),
        ("annualization_factor_non_datetime_index", test_annualization_factor_non_datetime_index),
        ("trade_metrics_use_return_for_avg_win_loss", test_trade_metrics_use_return_for_avg_win_loss),
        ("profit_factor_uses_pnl_gross_profit_over_gross_loss", test_profit_factor_uses_pnl_gross_profit_over_gross_loss),
        ("expectancy_is_mean_pnl", test_expectancy_is_mean_pnl),
        ("avg_trade_duration_is_calendar_days", test_avg_trade_duration_is_calendar_days),
        ("trade_metrics_handle_missing_return_field", test_trade_metrics_handle_missing_return_field),
        ("trade_metrics_absent_when_no_trades", test_trade_metrics_absent_when_no_trades),
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