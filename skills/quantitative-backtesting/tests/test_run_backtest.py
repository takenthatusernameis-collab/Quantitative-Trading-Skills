#!/usr/bin/env python3
"""
Unit tests for run_backtest.py: the CLI entry point and its flat-strategy guard.

Run with: python3 skills/quantitative-backtesting/tests/test_run_backtest.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
import argparse
from pathlib import Path
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from run_backtest import run_backtest, signals_active, parse_args  # noqa: E402
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


class _FlipStrategy:
    """Minimal strategy that flips directly between long and short.

    Long for the first bars, short for the next, then flat. No bar ever
    carries a zero position between the legs, so a naive exit-only trade
    extractor would miss the round turn entirely.
    """

    def __init__(self, config):
        self.config = config
        self.name = config.name
        self.parameters = config.parameters

    def generate_signals(self, data):
        s = pd.Series(0, index=data.index)
        n = len(data)
        s.iloc[: n // 3] = 1
        s.iloc[n // 3 : 2 * n // 3] = -1
        s.iloc[2 * n // 3 :] = 0
        return s

    def get_position_sizing(self, data, signals):
        return signals.abs()


def _flip_strategy():
    from strategy_builder import StrategyConfig
    return _FlipStrategy(StrategyConfig(name="flip", parameters={}))


def test_run_backtest_records_both_legs_of_direct_long_short_flip():
    """A direct +1 -> -1 flip must record two trades (long close + short open).

    Regression test for a defect where the trade extractor only fired when the
    position returned to zero, so a long/short flip produced a single phantom
    trade (or none at all) and the short leg was never accounted for.
    """
    data = _make_data()
    strategy = _flip_strategy()
    results = run_backtest(data, strategy, _Args())

    # At least one long leg and one short leg must have been traded.
    assert len(results["trades"]) >= 2, (
        f"expected >= 2 trades for a long/short flip, got {len(results['trades'])}"
    )

    # Every trade must carry a finite pnl/return, and the sign of pnl must be
    # consistent with the direction the trade was taken (long: pnl follows
    # price; short: pnl moves opposite to price).
    for trade in results["trades"]:
        assert isinstance(trade["pnl"], float)
        assert isinstance(trade["return"], float)
        assert trade["entry_date"] < trade["exit_date"]


def test_run_backtest_short_leg_pnl_moves_opposite_to_price():
    """A short position profits when price falls and loses when price rises.

    Verifies the PnL sign convention after the flip fix: the old
    (exit_price - entry_price) * sign formula treated shorts as longs.
    """
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    close = pd.Series([100, 102, 104, 106, 108, 110], index=dates, dtype=float)
    data = pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1000},
        index=dates,
    )

    # Short for the first two bars, then flat. The position is opened at bar 1
    # (close 102) and closed at bar 3 (close 106), so the trade is fully
    # recorded and the short must lose money on the rising price.
    class ShortThenFlat:
        def __init__(self, config):
            self.config = config
            self.name = config.name
            self.parameters = config.parameters

        def generate_signals(self, data):
            s = pd.Series(0, index=data.index)
            s.iloc[1:3] = -1
            return s

        def get_position_sizing(self, data, signals):
            return signals.abs()

    from strategy_builder import StrategyConfig
    strategy = ShortThenFlat(StrategyConfig(name="short", parameters={}))
    results = run_backtest(data, strategy, _Args())

    assert len(results["trades"]) == 1, f"expected exactly 1 trade, got {results['trades']}"
    trade = results["trades"][0]
    assert trade["pnl"] < 0, (
        f"short on a rising market must lose money, got pnl={trade['pnl']}"
    )
    assert abs(trade["pnl"] - (102 - 106)) < 1e-9, (
        f"short pnl should be entry - exit = -4, got {trade['pnl']}"
    )


def test_run_backtest_long_leg_pnl_moves_with_price():
    """A long position profits when price rises and loses when price falls."""
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    close = pd.Series([100, 102, 104, 106, 108, 110], index=dates, dtype=float)
    data = pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1000},
        index=dates,
    )

    # Long for the first two bars, then flat. Opened at bar 1 (close 102),
    # closed at bar 3 (close 106): the long must profit from the rise.
    class LongThenFlat:
        def __init__(self, config):
            self.config = config
            self.name = config.name
            self.parameters = config.parameters

        def generate_signals(self, data):
            s = pd.Series(0, index=data.index)
            s.iloc[1:3] = 1
            return s

        def get_position_sizing(self, data, signals):
            return signals.abs()

    from strategy_builder import StrategyConfig
    strategy = LongThenFlat(StrategyConfig(name="long", parameters={}))
    results = run_backtest(data, strategy, _Args())

    assert len(results["trades"]) == 1, f"expected exactly 1 trade, got {results['trades']}"
    trade = results["trades"][0]
    assert trade["pnl"] > 0, (
        f"long on a rising market must make money, got pnl={trade['pnl']}"
    )
    assert abs(trade["pnl"] - (106 - 102)) < 1e-9, (
        f"long pnl should be exit - entry = 4, got {trade['pnl']}"
    )


def test_parse_args_requires_data_argument():
    """parse_args must error when --data is missing."""
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    # Recreate the argument parser from run_backtest.parse_args
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")

    # Capture stderr to avoid polluting test output
    stderr_capture = StringIO()
    try:
        with redirect_stderr(stderr_capture):
            parser.parse_args([])
        assert False, "Expected SystemExit for missing required --data argument"
    except SystemExit as e:
        assert e.code != 0, "Expected non-zero exit code"
        stderr_output = stderr_capture.getvalue()
        assert "--data" in stderr_output or "required" in stderr_output.lower()


def test_parse_args_accepts_valid_arguments():
    """parse_args accepts valid arguments and sets defaults correctly."""
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")

    args = parser.parse_args(["--data", "/path/to/data.csv"])
    assert args.data == "/path/to/data.csv"
    assert args.strategy == "sma_crossover"
    assert args.symbol == "SPY"
    assert args.commission == 0.0002
    assert args.slippage == 0.0001
    assert args.initial_capital == 100000
    assert args.output == "results"
    assert args.params is None


def test_parse_args_custom_values():
    """parse_args correctly parses custom argument values."""
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--params", type=str, help="Strategy parameters as JSON string")

    args = parser.parse_args([
        "--data", "/custom/data.parquet",
        "--strategy", "mean_reversion",
        "--symbol", "AAPL",
        "--commission", "0.001",
        "--slippage", "0.0005",
        "--initial-capital", "50000",
        "--output", "/custom/output",
        "--params", '{"period": 20}',
    ])
    assert args.data == "/custom/data.parquet"
    assert args.strategy == "mean_reversion"
    assert args.symbol == "AAPL"
    assert args.commission == 0.001
    assert args.slippage == 0.0005
    assert args.initial_capital == 50000
    assert args.output == "/custom/output"
    assert args.params == '{"period": 20}'


def test_parse_args_invalid_commission_type():
    """parse_args rejects non-numeric commission values."""
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")

    stderr_capture = StringIO()
    try:
        with redirect_stderr(stderr_capture):
            parser.parse_args(["--data", "test.csv", "--commission", "not_a_number"])
        assert False, "Expected SystemExit for invalid commission type"
    except SystemExit as e:
        assert e.code != 0, "Expected non-zero exit code"


def test_parse_args_invalid_initial_capital_type():
    """parse_args rejects non-numeric initial-capital values."""
    parser = argparse.ArgumentParser(description="Run quantitative backtest")
    parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")

    stderr_capture = StringIO()
    try:
        with redirect_stderr(stderr_capture):
            parser.parse_args(["--data", "test.csv", "--initial-capital", "not_a_number"])
        assert False, "Expected SystemExit for invalid initial-capital type"
    except SystemExit as e:
        assert e.code != 0, "Expected non-zero exit code"


def main() -> int:
    tests = [
        ("signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
        ("run_backtest_flat_strategy_raises", test_run_backtest_flat_strategy_raises),
        ("run_backtest_flat_long_lookback_raises", test_run_backtest_flat_long_lookback_raises),
        ("run_backtest_active_strategy_succeeds", test_run_backtest_active_strategy_succeeds),
        ("run_backtest_trade_analytics_populated", test_run_backtest_trade_analytics_populated),
        ("run_backtest_records_both_legs_of_direct_long_short_flip", test_run_backtest_records_both_legs_of_direct_long_short_flip),
        ("run_backtest_short_leg_pnl_moves_opposite_to_price", test_run_backtest_short_leg_pnl_moves_opposite_to_price),
        ("run_backtest_long_leg_pnl_moves_with_price", test_run_backtest_long_leg_pnl_moves_with_price),
        ("parse_args_requires_data_argument", test_parse_args_requires_data_argument),
        ("parse_args_accepts_valid_arguments", test_parse_args_accepts_valid_arguments),
        ("parse_args_custom_values", test_parse_args_custom_values),
        ("parse_args_invalid_commission_type", test_parse_args_invalid_commission_type),
        ("parse_args_invalid_initial_capital_type", test_parse_args_invalid_initial_capital_type),
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