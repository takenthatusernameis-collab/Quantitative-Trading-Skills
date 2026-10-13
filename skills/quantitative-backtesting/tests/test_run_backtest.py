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
from walk_forward import deflated_sharpe_ratio  # noqa: E402


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
                 strategy="sma_crossover", symbol="TEST", n_trials=None):
        self.commission = commission
        self.slippage = slippage
        self.initial_capital = initial_capital
        self.strategy = strategy
        self.symbol = symbol
        self.n_trials = n_trials


def test_signals_active_detects_flat_and_active_series():
    """signals_active returns False for all-zero signals, True otherwise."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    flat = pd.Series(0, index=dates, dtype=int)
    assert signals_active(flat) is False

    active = pd.Series([0, 0, 1, 1, 0], index=dates)
    assert signals_active(active) is True

    empty = pd.Series(dtype=int)
    assert signals_active(empty) is False

    # NaN signals should be treated as flat (not active)
    nan_signals = pd.Series([np.nan, np.nan, np.nan], index=dates[:3])
    assert signals_active(nan_signals) is False

    # Mixed NaN and zero should be flat
    mixed_nan_zero = pd.Series([np.nan, 0, np.nan, 0], index=dates[:4])
    assert signals_active(mixed_nan_zero) is False

    # Mixed NaN and active should be active
    mixed_nan_active = pd.Series([np.nan, 0, 1, np.nan], index=dates[:4])
    assert signals_active(mixed_nan_active) is True


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


def test_run_backtest_n_trials_surfaces_deflated_sharpe():
    """--n-trials threads n_trials through config into a deflated_sharpe key.

    The Deflated Sharpe Ratio (multiple-testing correction) is computed
    from the final backtest Sharpe and the number of development trials,
    and surfaced in the metrics output.
    """
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args(n_trials=50))

    from performance import calculate_metrics

    metrics = calculate_metrics(results)

    assert "deflated_sharpe" in metrics, "expected deflated_sharpe in metrics"
    d = metrics["deflated_sharpe"]
    assert 0.0 <= d["deflated_sharpe_ratio"] <= 1.0
    assert d["n_trials"] == 50
    assert d["n_observations"] == len(results["returns"])
    assert abs(d["sharpe_ratio"] - metrics["sharpe_ratio"]) < 1e-9
    assert abs(d["p_value"] - (1.0 - d["deflated_sharpe_ratio"])) < 1e-12


def test_run_backtest_without_n_trials_omits_deflated_sharpe():
    """Without n_trials, no deflated_sharpe key is added (backward compat)."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())

    from performance import calculate_metrics

    metrics = calculate_metrics(results)

    assert "deflated_sharpe" not in metrics
    # The behavior is opt-in: the config records n_trials=None.
    assert results["config"]["n_trials"] is None


def test_run_backtest_deflated_sharpe_matches_direct_call():
    """The surfaced DSR equals a direct deflated_sharpe_ratio call.

    Guards against the metrics path and the standalone function drifting
    apart: both consume the same Sharpe and return series.
    """
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args(n_trials=25))

    from performance import calculate_metrics

    metrics = calculate_metrics(results)

    expected = deflated_sharpe_ratio(
        sharpe_ratio=metrics["sharpe_ratio"],
        returns=results["returns"],
        n_trials=25,
    )
    got = metrics["deflated_sharpe"]
    for key in ("deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
                "n_trials", "n_observations", "skewness", "kurtosis"):
        assert abs(got[key] - expected[key]) < 1e-9, f"{key} mismatch"
    assert got["n_trials"] == expected["n_trials"] == 25


def test_parse_args_accepts_n_trials():
    """parse_args accepts --n-trials and defaults it to None."""
    from unittest.mock import patch

    with patch.object(sys, "argv", ["prog", "--data", "d.csv", "--n-trials", "100"]):
        args = parse_args()
    assert args.n_trials == 100

    with patch.object(sys, "argv", ["prog", "--data", "d.csv"]):
        args = parse_args()
    assert args.n_trials is None


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


def test_run_backtest_closes_final_open_position_at_end_of_data():
    """A position still open at the end of the data is closed at the
    last bar (mark-to-market) so the trade ledger reconciles with the
    equity curve.

    Regression test: a strategy that stays long from bar 2 to the end
    previously recorded zero trades even though the equity curve
    carried the leg's PnL, so trade-level stats (win rate, expectancy,
    profit factor) silently understated activity. The forced close is
    flagged via `closed_at_end` because it is not signal-driven.
    """
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    close = pd.Series([100, 102, 104, 106, 108, 110], index=dates, dtype=float)
    data = pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1000},
        index=dates,
    )

    class LongToEnd:
        def __init__(self, config):
            self.config = config
            self.name = config.name
            self.parameters = config.parameters

        def generate_signals(self, data):
            s = pd.Series(0, index=data.index)
            s.iloc[1:] = 1
            return s

        def get_position_sizing(self, data, signals):
            return signals.abs()

    from strategy_builder import StrategyConfig
    strategy = LongToEnd(StrategyConfig(name="long_to_end", parameters={}))
    results = run_backtest(data, strategy, _Args())

    # The leg opens at bar 2 (position = signal shifted by one bar,
    # close 104) and is marked to market at the final bar (close 110).
    assert len(results["trades"]) == 1, (
        f"expected 1 trade, got {results['trades']}"
    )
    trade = results["trades"][0]
    assert trade["entry_date"] == "2020-01-03"
    assert trade["exit_date"] == "2020-01-08"
    assert trade.get("closed_at_end") is True
    assert abs(trade["pnl"] - (110 - 104)) < 1e-9, (
        f"long leg held to end must profit from the rise, got {trade['pnl']}"
    )
    assert abs(trade["return"] - (110 - 104) / 104) < 1e-9


# Parameters that keep each registered strategy active over the
# 252-bar test window. The momentum strategies default to a 252-bar
# lookback, which leaves every rolling indicator undefined over this
# window (flat signal); a shorter lookback keeps them tradable.
_AUDIT_PARAMS = {
    "sma_crossover": None,
    "ema_crossover": None,
    "bollinger_bands": None,
    "rsi_mean_reversion": None,
    "donchian_breakout": None,
    "cross_sectional_momentum": '{"lookback": 21}',
    "dual_momentum": '{"lookback": 21}',
    "zscore_mean_reversion": None,
}


def test_run_backtest_trade_ledger_valid_for_all_registered_strategies():
    """Every registered strategy produces a valid trade ledger.

    Parameterized audit across STRATEGY_REGISTRY: each strategy must
    record at least one trade, every trade must carry a finite
    pnl/return with entry_date < exit_date, and the pnl sign must be
    consistent with the direction of the position taken at entry
    (long follows price, short moves opposite). The expected pnl is
    recomputed independently from the strategy's own shifted signals,
    so a sign error in the extractor cannot pass by coincidence.
    """
    data = _make_data()
    from strategy_builder import STRATEGY_REGISTRY

    assert set(_AUDIT_PARAMS) == set(STRATEGY_REGISTRY), (
        "audit params and strategy registry are out of sync"
    )

    for name, params_json in _AUDIT_PARAMS.items():
        strategy = build_strategy(name, params_json)
        results = run_backtest(data, strategy, _Args(strategy=name))

        assert results["trades"], f"{name}: no trades recorded"

        # Independent reconstruction of the position series to verify
        # the sign convention of every recorded trade.
        signals = strategy.generate_signals(data)
        positions = signals.shift(1).fillna(0)
        close = data["close"]

        for trade in results["trades"]:
            assert isinstance(trade["pnl"], float), f"{name}: non-float pnl"
            assert np.isfinite(trade["pnl"]), f"{name}: non-finite pnl"
            assert isinstance(trade["return"], float), f"{name}: non-float return"
            assert np.isfinite(trade["return"]), f"{name}: non-finite return"
            assert trade["entry_date"] < trade["exit_date"], (
                f"{name}: entry_date must precede exit_date, got "
                f"{trade['entry_date']} >= {trade['exit_date']}"
            )

            entry = pd.Timestamp(trade["entry_date"])
            exit_ = pd.Timestamp(trade["exit_date"])
            direction = np.sign(positions.loc[entry])
            assert direction != 0, f"{name}: zero position at entry {entry}"
            expected_pnl = (close.loc[exit_] - close.loc[entry]) * direction
            assert abs(trade["pnl"] - expected_pnl) < 1e-9, (
                f"{name}: pnl {trade['pnl']} inconsistent with direction "
                f"{direction:+.0f} (expected {expected_pnl})"
            )
            expected_return = expected_pnl / close.loc[entry]
            assert abs(trade["return"] - expected_return) < 1e-9, (
                f"{name}: return {trade['return']} inconsistent with "
                f"pnl/entry-price (expected {expected_return})"
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


def _make_flat_price_data(periods: int = 100) -> pd.DataFrame:
    """Create a DataFrame with perfectly flat prices (zero returns)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    prices = np.full(periods, 100.0)
    return pd.DataFrame({
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [1000000] * periods,
    }, index=dates)


def test_run_backtest_constant_returns_deflated_sharpe():
    """A strategy with active signals but constant returns (zero variance)
    produces DSR = 0 with z_score = None when n_trials is provided.

    This guards the degenerate edge case where a strategy trades (e.g.
    donchian_breakout on a flat price series) but the return series has
    zero variance. The Deflated Sharpe Ratio must handle this conservatively
    (DSR = 0, p-value = 1) rather than raising or producing NaN.
    """
    data = _make_flat_price_data()
    # donchian_breakout takes positions on flat data (period < len(data))
    strategy = build_strategy("donchian_breakout", '{"period": 20}')
    # Zero commission/slippage so returns are exactly zero (no cost noise)
    args = _Args(commission=0.0, slippage=0.0, n_trials=10)
    results = run_backtest(data, strategy, args)

    assert results["returns"].std() == 0.0, "expected zero-variance returns"
    assert len(results["returns"]) >= 2, "need at least 2 observations for DSR"

    from performance import calculate_metrics
    metrics = calculate_metrics(results)

    assert "deflated_sharpe" in metrics, "expected deflated_sharpe in metrics"
    d = metrics["deflated_sharpe"]
    assert d["deflated_sharpe_ratio"] == 0.0
    assert d["p_value"] == 1.0
    assert d["z_score"] is None
    assert d["n_trials"] == 10
    assert d["n_observations"] == len(results["returns"])
    assert d["skewness"] == 0.0
    assert d["kurtosis"] == 3.0
    assert d["sharpe_ratio"] == 0.0


def main() -> int:
    tests = [
        ("signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
        ("run_backtest_flat_strategy_raises", test_run_backtest_flat_strategy_raises),
        ("run_backtest_flat_long_lookback_raises", test_run_backtest_flat_long_lookback_raises),
        ("run_backtest_active_strategy_succeeds", test_run_backtest_active_strategy_succeeds),
        ("run_backtest_trade_analytics_populated", test_run_backtest_trade_analytics_populated),
        ("run_backtest_n_trials_surfaces_deflated_sharpe", test_run_backtest_n_trials_surfaces_deflated_sharpe),
        ("run_backtest_without_n_trials_omits_deflated_sharpe", test_run_backtest_without_n_trials_omits_deflated_sharpe),
        ("run_backtest_deflated_sharpe_matches_direct_call", test_run_backtest_deflated_sharpe_matches_direct_call),
        ("parse_args_accepts_n_trials", test_parse_args_accepts_n_trials),
        ("run_backtest_records_both_legs_of_direct_long_short_flip", test_run_backtest_records_both_legs_of_direct_long_short_flip),
        ("run_backtest_short_leg_pnl_moves_opposite_to_price", test_run_backtest_short_leg_pnl_moves_opposite_to_price),
        ("run_backtest_long_leg_pnl_moves_with_price", test_run_backtest_long_leg_pnl_moves_with_price),
        ("run_backtest_closes_final_open_position_at_end_of_data", test_run_backtest_closes_final_open_position_at_end_of_data),
        ("run_backtest_trade_ledger_valid_for_all_registered_strategies", test_run_backtest_trade_ledger_valid_for_all_registered_strategies),
        ("parse_args_requires_data_argument", test_parse_args_requires_data_argument),
        ("parse_args_accepts_valid_arguments", test_parse_args_accepts_valid_arguments),
        ("parse_args_custom_values", test_parse_args_custom_values),
        ("parse_args_invalid_commission_type", test_parse_args_invalid_commission_type),
        ("parse_args_invalid_initial_capital_type", test_parse_args_invalid_initial_capital_type),
        ("run_backtest_constant_returns_deflated_sharpe", test_run_backtest_constant_returns_deflated_sharpe),
        ("run_backtest_multi_asset_cross_sectional_momentum", test_run_backtest_multi_asset_cross_sectional_momentum),
        ("run_backtest_multi_asset_dual_momentum", test_run_backtest_multi_asset_dual_momentum),
        ("run_backtest_multi_asset_dict_cross_sectional_momentum", test_run_backtest_multi_asset_dict_cross_sectional_momentum),
        ("run_backtest_multi_asset_dict_dual_momentum", test_run_backtest_multi_asset_dict_dual_momentum),
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


def _make_multiasset_multiindex(n=300, n_assets=4, seed=42):
    """Create MultiIndex panel data for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0, index=dates, columns=cols)
    rng = np.random.default_rng(seed)
    for i, sym in enumerate(symbols):
        drift = 0.001 * (i + 1)
        rets = rng.normal(drift, 0.015, n)
        prices = 100 * np.exp(np.cumsum(rets))
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, n)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, n)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, n)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, n)
    return df


def test_run_backtest_multi_asset_cross_sectional_momentum():
    """Run backtest works with multi-asset cross-sectional momentum."""
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy("cross_sectional_momentum",
                             '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}')
    results = run_backtest(data, strategy, _Args())
    assert "equity_curve" in results
    assert "returns" in results
    assert len(results["returns"]) > 0


def test_run_backtest_multi_asset_dual_momentum():
    """Run backtest works with multi-asset dual momentum."""
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=123)
    strategy = build_strategy("dual_momentum",
                             '{"lookback": 60, "top_quantile": 0.3, "risk_free_rate": 0.0}')
    results = run_backtest(data, strategy, _Args())
    assert "equity_curve" in results
    assert "returns" in results
    assert len(results["returns"]) > 0


def _make_multiasset_dict(n=300, n_assets=5, seed=42):
    """Create dict of symbol -> OHLCV DataFrame for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    rng = np.random.default_rng(seed)
    data_dict = {}
    for i, sym in enumerate(symbols):
        drift = 0.001 * (i + 1)
        rets = rng.normal(drift, 0.015, n)
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame({
            "open": prices * rng.uniform(0.995, 1.005, n),
            "high": prices * rng.uniform(1.005, 1.02, n),
            "low": prices * rng.uniform(0.98, 0.995, n),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, n),
        }, index=dates)
    return data_dict


def test_run_backtest_multi_asset_dict_cross_sectional_momentum():
    """Run backtest works with dict panel data (cross-sectional momentum).

    Regression coverage: the trade extractor iterated range(len(data)),
    which is the number of symbols (not bars) for a dict, and read
    data.index (absent on dicts), so dict panel data crashed or
    silently recorded zero trades despite active positions.
    """
    data = _make_multiasset_dict(n=300, n_assets=5, seed=42)
    strategy = build_strategy("cross_sectional_momentum",
                              '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}')
    results = run_backtest(data, strategy, _Args())
    assert "equity_curve" in results
    assert "returns" in results
    assert len(results["returns"]) > 0
    # The strategy is active over this window, so the trade ledger
    # must be non-empty and every trade must be well-formed.
    assert len(results["trades"]) > 0, (
        "dict panel data produced an empty trade ledger"
    )
    for trade in results["trades"]:
        assert isinstance(trade["pnl"], float)
        assert isinstance(trade["return"], float)
        assert trade["entry_date"] < trade["exit_date"]


def test_run_backtest_multi_asset_dict_dual_momentum():
    """Run backtest works with dict panel data (dual momentum)."""
    data = _make_multiasset_dict(n=300, n_assets=5, seed=123)
    strategy = build_strategy("dual_momentum",
                              '{"lookback": 60, "top_quantile": 0.3, "risk_free_rate": 0.0}')
    results = run_backtest(data, strategy, _Args())
    assert "equity_curve" in results
    assert "returns" in results
    assert len(results["returns"]) > 0
    assert len(results["trades"]) > 0, (
        "dict panel data produced an empty trade ledger"
    )
    for trade in results["trades"]:
        assert isinstance(trade["pnl"], float)
        assert isinstance(trade["return"], float)
        assert trade["entry_date"] < trade["exit_date"]


if __name__ == "__main__":
    sys.exit(main())
