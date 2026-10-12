#!/usr/bin/env python3
"""
Unit tests for run_backtest.py: the CLI entry point and its flat-strategy guard.

Run with: python3 skills/quantitative-backtesting/tests/test_run_backtest.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from run_backtest import run_backtest, signals_active  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402


def _make_data(periods: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        },
        index=dates,
    )


class _Args:
    def __init__(self, commission=0.0002, slippage=0.0001, initial_capital=100000,
                 strategy="sma_crossover", symbol="TEST"):
        self.commission = commission
        self.slippage = slippage
        self.initial_capital = initial_capital
        self.strategy = strategy
        self.symbol = symbol


def test_signals_active_detects_flat_and_active_series():
    """signals_active returns False for all-zero signals, True otherwise."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    flat = pd.Series(0, index=dates, dtype=int)
    assert signals_active(flat) is False

    active = pd.Series([0, 0, 1, 1, 0], index=dates)
    assert signals_active(active) is True

    empty = pd.Series(dtype=int)
    assert signals_active(empty) is False


def test_run_backtest_flat_strategy_raises():
    """A strategy that never takes a position must raise ValueError."""
    data = _make_data()
    # fast == slow produces a flat signal everywhere
    strategy = build_strategy("sma_crossover", '{"fast_period": 50, "slow_period": 50}')

    try:
        run_backtest(data, strategy, _Args())
        assert False, "Expected ValueError for flat strategy"
    except ValueError as e:
        assert "never takes a position" in str(e), f"unexpected message: {e}"


def test_run_backtest_flat_long_lookback_raises():
    """A lookback longer than the data window leaves every indicator NaN."""
    data = _make_data(periods=100)
    # slow_period far exceeds the 100-row window -> all NaN -> flat signal
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 500}')

    try:
        run_backtest(data, strategy, _Args())
        assert False, "Expected ValueError for flat strategy"
    except ValueError as e:
        assert "never takes a position" in str(e), f"unexpected message: {e}"


def test_run_backtest_active_strategy_succeeds():
    """An active strategy produces trades and a finite Sharpe ratio."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())

    assert "equity_curve" in results
    assert "returns" in results
    assert "trades" in results
    assert len(results["returns"]) > 0
    # The equity curve must not be perfectly flat (strategy actually trades)
    assert results["equity_curve"].std() > 0


def test_run_backtest_trade_analytics_populated():
    """Trade-level metrics are computed when the strategy trades."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())

    from performance import calculate_metrics

    metrics = calculate_metrics(results)
    assert metrics.get("total_trades", 0) > 0, "expected at least one trade"
    assert metrics.get("win_rate") is not None
    assert 0.0 <= metrics["win_rate"] <= 1.0
    assert metrics.get("total_return") is not None


def main() -> int:
    tests = [
        ("signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
        ("run_backtest_flat_strategy_raises", test_run_backtest_flat_strategy_raises),
        ("run_backtest_flat_long_lookback_raises", test_run_backtest_flat_long_lookback_raises),
        ("run_backtest_active_strategy_succeeds", test_run_backtest_active_strategy_succeeds),
        ("run_backtest_trade_analytics_populated", test_run_backtest_trade_analytics_populated),
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