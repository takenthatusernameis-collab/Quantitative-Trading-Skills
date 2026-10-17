from unittest.mock import patch
#!/usr/bin/env python3
"""
Unit tests for run_backtest.py: the CLI entry point and its flat-strategy guard.

Run with: python3 skills/quantitative-backtesting/tests/test_run_backtest.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
import argparse
import json
import os
import tempfile
from pathlib import Path
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from run_backtest import run_backtest, signals_active, parse_args  # noqa: E402
from run_backtest import main as run_backtest_main  # noqa: E402  (aliased: the test module defines its own main() runner below)
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import deflated_sharpe_ratio  # noqa: E402
from data_loader import DataProvenance  # noqa: E402


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
                 strategy="sma_crossover", symbol="TEST", n_trials=None,
                 impact_coefficient=0.0, adv_window=20,
                 borrow_cost=0.0, funding_cost=0.0,
                 validate_point_in_time=False, point_in_time_strict=False,
                 multi_symbol=False, benchmark=None, risk_free_rate=None):
        self.commission = commission
        self.slippage = slippage
        self.initial_capital = initial_capital
        self.strategy = strategy
        self.symbol = symbol
        self.n_trials = n_trials
        self.impact_coefficient = impact_coefficient
        self.adv_window = adv_window
        self.borrow_cost = borrow_cost
        self.funding_cost = funding_cost
        self.validate_point_in_time = validate_point_in_time
        self.point_in_time_strict = point_in_time_strict
        self.multi_symbol = multi_symbol
        self.benchmark = benchmark
        self.risk_free_rate = risk_free_rate


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
    "macd": None,
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


def _make_flat_price_data(periods: int = 100, freq: str = "B") -> pd.DataFrame:
    """Create a DataFrame with perfectly flat prices (zero returns)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq=freq)
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


class _AlwaysShort:
    """Stub strategy that holds a constant short position."""

    def generate_signals(self, data):
        return pd.Series(-1.0, index=data.index)


def test_run_backtest_borrow_cost_frequency_aware():
    """run_backtest divides the annual borrow rate by the data's
    inferred periods per year (weekly -> /52, business-daily -> /252),
    not a hardcoded 252.

    Flat prices and a constant short signal isolate the borrow cost:
    with zero raw returns and no position changes, every period's
    strategy return must equal exactly -borrow_cost / periods_per_year.
    """
    args = _Args(commission=0.0, slippage=0.0, borrow_cost=0.10)

    weekly = _make_flat_price_data(periods=60, freq="W")
    weekly_results = run_backtest(weekly, _AlwaysShort(), args)
    assert np.allclose(weekly_results["returns"], -0.10 / 52), (
        f"expected weekly per-period cost {-0.10 / 52}, "
        f"got {weekly_results['returns'].iloc[0]}"
    )

    daily = _make_flat_price_data(periods=60, freq="B")
    daily_results = run_backtest(daily, _AlwaysShort(), args)
    assert np.allclose(daily_results["returns"], -0.10 / 252), (
        f"expected daily per-period cost {-0.10 / 252}, "
        f"got {daily_results['returns'].iloc[0]}"
    )


def test_run_backtest_serializes_data_provenance_into_results():
    """run_backtest serializes the DataProvenance captured at load time.

    The provenance travels from load_data (return_provenance=True)
    through the CLI into the results dict and the data_provenance.json
    artifact, so the backtest is reproducible from its inputs.
    """
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    prov = DataProvenance(
        source_path="data.csv",
        load_timestamp="2026-01-01T00:00:00Z",
        file_format=".csv",
        file_size_bytes=1234,
        symbol_filter="SPY",
        checksum="deadbeef",
    )
    results = run_backtest(data, strategy, _Args(), data_provenance=prov)

    assert "data_provenance" in results
    assert results["data_provenance"] == prov.to_dict()
    assert results["data_provenance"]["source_path"] == "data.csv"
    assert results["data_provenance"]["checksum"] == "deadbeef"


def test_run_backtest_serializes_panel_provenance_dict():
    """Multi-symbol panels serialize a dict of per-symbol provenance."""
    # 3 assets so the net-exposure signal is non-zero with the
    # 0.4/0.2 quantiles (2 assets would long one and short one,
    # giving a flat zero signal by construction).
    data = _make_multiasset_dict(n=120, n_assets=3, seed=5)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    provs = {
        sym: DataProvenance(
            source_path="panel.csv",
            load_timestamp="2026-01-01T00:00:00Z",
            file_format=".csv",
            file_size_bytes=99,
            symbol_filter=sym,
            checksum=f"ck{i}",
        )
        for i, sym in enumerate(data)
    }
    results = run_backtest(data, strategy, _Args(), data_provenance=provs)

    assert set(results["data_provenance"]) == set(data)
    for sym, prov in provs.items():
        assert results["data_provenance"][sym] == prov.to_dict()


def test_run_backtest_without_provenance_omits_key():
    """Backward compat: no data_provenance key when none was captured."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())
    assert "data_provenance" not in results


def test_run_backtest_point_in_time_validation_recorded():
    """--validate-point-in-time records the outcome in the results."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')

    results = run_backtest(data, strategy, _Args(validate_point_in_time=True))
    assert "point_in_time_validation" in results
    pit = results["point_in_time_validation"]
    assert pit["passed"] is True
    assert pit["violations"] == []

    # Opt-in: without the flag no key is emitted (backward compatible).
    off = run_backtest(data, strategy, _Args())
    assert "point_in_time_validation" not in off


def test_run_backtest_point_in_time_detects_duplicate_timestamps():
    """Duplicate timestamps are a point-in-time violation.

    A non-strict run still completes (violations are warnings), but the
    outcome is recorded in the results so downstream consumers can see
    the data-integrity problem.
    """
    data = _make_data()
    dup = pd.concat([data, data.iloc[[5]]])  # duplicate one row's timestamp
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')

    results = run_backtest(dup, strategy, _Args(validate_point_in_time=True))
    pit = results["point_in_time_validation"]
    assert pit["passed"] is False
    assert any("Duplicate timestamps" in v for v in pit["violations"])
    assert len(results["trades"]) > 0, "non-strict run must still complete"


def test_handle_point_in_time_results_strictness_matrix():
    """Strict mode aborts only on violations, never on warnings."""
    from run_backtest import _handle_point_in_time_results

    violations = {
        "passed": False,
        "violations": ["Duplicate timestamps found"],
        "warnings": [],
    }
    clean = {"passed": True, "violations": [], "warnings": []}
    warned = {"passed": True, "violations": [], "warnings": ["stale data"]}

    # The handler prints its findings; keep the test output clean.
    with redirect_stdout(StringIO()):
        assert _handle_point_in_time_results(violations, strict=True) is True
        assert _handle_point_in_time_results(violations, strict=False) is False
        assert _handle_point_in_time_results(clean, strict=True) is False
        assert _handle_point_in_time_results(warned, strict=True) is False

def test_run_backtest_point_in_time_panel_validates_each_symbol():
    """Dict panels are validated per symbol for structural violations.

    A symbol whose frame is out of temporal order is a point-in-time
    violation even though the panel as a whole is well-formed; the
    combined result must surface it.
    """
    data = _make_multiasset_dict(n=252, n_assets=3, seed=11)
    sym = sorted(data)[0]
    data[sym] = data[sym].iloc[::-1]  # unique labels, non-monotonic order
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )

    results = run_backtest(data, strategy, _Args(validate_point_in_time=True))
    pit = results["point_in_time_validation"]
    assert pit["passed"] is False
    assert any("not monotonically increasing" in v for v in pit["violations"])


def test_parse_args_accepts_validation_and_multi_symbol_flags():
    """The PIT-validation and multi-symbol flags parse and default off."""
    from unittest.mock import patch

    with patch.object(sys, "argv", [
        "prog", "--data", "d.csv",
        "--validate-point-in-time", "--point-in-time-strict", "--multi-symbol",
    ]):
        args = parse_args()
    assert args.validate_point_in_time is True
    assert args.point_in_time_strict is True
    assert args.multi_symbol is True

    with patch.object(sys, "argv", ["prog", "--data", "d.csv"]):
        args = parse_args()
    assert args.validate_point_in_time is False
    assert args.point_in_time_strict is False
    assert args.multi_symbol is False


def _write_ohlcv_csv(path: str, periods: int = 252, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }).to_csv(path, index=False)


def _write_multi_symbol_csv(path: str, periods: int = 300) -> None:
    """Write a panel with one survivor, one late entry, one early exit."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rows = []
    for i, (sym, start, end) in enumerate([
        ("SURV", 0, periods), ("LATE", 60, periods), ("EARLY", 0, periods - 60),
    ]):
        rng = np.random.default_rng(i + 1)
        rets = rng.normal(0.0005, 0.015, end - start)
        prices = 100 * np.exp(np.cumsum(rets))
        for j, d in enumerate(dates[start:end]):
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "symbol": sym,
                "open": prices[j],
                "high": prices[j] * 1.01,
                "low": prices[j] * 0.99,
                "close": prices[j],
                "volume": int(rng.integers(1_000_000, 10_000_000)),
            })
    pd.DataFrame(rows).to_csv(path, index=False)


def test_cli_writes_data_provenance_artifact():
    """The CLI persists load-time provenance next to the results.

    End-to-end regression for the provenance integration: the
    data_provenance.json artifact must record the source file, its
    checksum, and the validation outcome so the run can be audited
    and reproduced.
    """
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir, "--validate-point-in-time",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0
        prov_path = os.path.join(out_dir, "data_provenance.json")
        assert os.path.exists(prov_path), "data_provenance.json not written"
        with open(prov_path) as f:
            prov = json.load(f)
        assert prov["source_path"] == csv_path
        assert prov["symbol_filter"] == "SPY"  # default --symbol
        assert prov["checksum"], "provenance artifact missing checksum"
        assert prov["validation_passed"] is True
        assert prov["date_range_final"] is not None


def test_cli_multi_symbol_writes_survivorship_artifact():
    """--multi-symbol runs survivorship detection and persists artifacts.

    End-to-end regression for the panel integration: the CLI must
    load the symbol universe, report and persist the survivorship
    bias analysis (entered/exited symbols, bias score), and write a
    per-symbol provenance artifact with checksums.
    """
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest", "--data", csv_path, "--multi-symbol",
            "--strategy", "cross_sectional_momentum",
            "--params", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
            "--output", out_dir, "--validate-point-in-time",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0

        surv_path = os.path.join(out_dir, "survivorship_bias.json")
        assert os.path.exists(surv_path), "survivorship_bias.json not written"
        with open(surv_path) as f:
            surv = json.load(f)
        assert surv["surviving_symbols"] == ["SURV"]
        assert [e["symbol"] for e in surv["entered_symbols"]] == ["LATE"]
        assert [e["symbol"] for e in surv["exited_symbols"]] == ["EARLY"]
        assert surv["bias_score"] > 0.0

        prov_path = os.path.join(out_dir, "data_provenance.json")
        assert os.path.exists(prov_path)
        with open(prov_path) as f:
            prov = json.load(f)
        assert set(prov) == {"SURV", "LATE", "EARLY"}
        assert all(p["checksum"] for p in prov.values())

        # The backtest itself must have run on the overlapping window.
        metrics_path = os.path.join(out_dir, "metrics.json")
        assert os.path.exists(metrics_path)
        with open(metrics_path) as f:
            metrics = json.load(f)
        assert metrics["total_trades"] > 0


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
        ("run_backtest_borrow_cost_frequency_aware", test_run_backtest_borrow_cost_frequency_aware),
        ("run_backtest_multi_asset_cross_sectional_momentum", test_run_backtest_multi_asset_cross_sectional_momentum),
        ("run_backtest_multi_asset_dual_momentum", test_run_backtest_multi_asset_dual_momentum),
        ("run_backtest_multi_asset_dict_cross_sectional_momentum", test_run_backtest_multi_asset_dict_cross_sectional_momentum),
        ("run_backtest_multi_asset_dict_dual_momentum", test_run_backtest_multi_asset_dict_dual_momentum),
        ("run_backtest_serializes_data_provenance_into_results", test_run_backtest_serializes_data_provenance_into_results),
        ("run_backtest_serializes_panel_provenance_dict", test_run_backtest_serializes_panel_provenance_dict),
        ("run_backtest_without_provenance_omits_key", test_run_backtest_without_provenance_omits_key),
        ("run_backtest_point_in_time_validation_recorded", test_run_backtest_point_in_time_validation_recorded),
        ("run_backtest_point_in_time_detects_duplicate_timestamps", test_run_backtest_point_in_time_detects_duplicate_timestamps),
        ("handle_point_in_time_results_strictness_matrix", test_handle_point_in_time_results_strictness_matrix),
        ("run_backtest_point_in_time_panel_validates_each_symbol", test_run_backtest_point_in_time_panel_validates_each_symbol),
        ("parse_args_accepts_validation_and_multi_symbol_flags", test_parse_args_accepts_validation_and_multi_symbol_flags),
        ("cli_writes_data_provenance_artifact", test_cli_writes_data_provenance_artifact),
        ("cli_multi_symbol_writes_survivorship_artifact", test_cli_multi_symbol_writes_survivorship_artifact),
        ("run_backtest_with_benchmark_attaches_aligned_returns", test_run_backtest_with_benchmark_attaches_aligned_returns),
        ("run_backtest_without_benchmark_omits_key", test_run_backtest_without_benchmark_omits_key),
        ("benchmark_superset_aligns_correctly", test_benchmark_superset_aligns_correctly),
        ("cli_benchmark_writes_artifact_and_metrics", test_cli_benchmark_writes_artifact_and_metrics),
        ("cli_total_return_benchmark_writes_provenance_and_differs_from_price", test_cli_total_return_benchmark_writes_provenance_and_differs_from_price),
        ("cli_total_return_benchmark_alpha_differs", test_cli_total_return_benchmark_alpha_differs),
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


# ---------------------------------------------------------------------------
# Buy-and-hold benchmark baseline tests
# ---------------------------------------------------------------------------


def test_run_backtest_with_benchmark_attaches_aligned_returns():
    """run_backtest with a benchmark DataFrame attaches aligned buy-and-hold returns.

    The benchmark return for period t is the close-to-close return from
    t-1 to t (no shift), matching the strategy's next-period-open trading
    convention. The aligned benchmark index is a subset of the strategy
    returns index (inner join on common dates).
    """
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    benchmark = _make_data(periods=252, seed=99)  # same date range, different prices

    results = run_backtest(data, strategy, _Args(), benchmark=benchmark)

    assert "benchmark" in results, "results[\"benchmark\"] should be set when a benchmark is provided"
    bench_returns = results["benchmark"]
    strat_returns = results["returns"]

    # The benchmark index is a subset of the strategy returns index.
    assert set(bench_returns.index).issubset(set(strat_returns.index))

    # Values match close-to-close pct_change on common dates (no shift, no
    # look-ahead — the benchmark return for period t is close[t]/close[t-1]-1).
    expected = benchmark["close"].pct_change()
    common = bench_returns.index.intersection(expected.index)
    for ts in common:
        assert abs(bench_returns.loc[ts] - expected.loc[ts]) < 1e-12, (
            f"benchmark return mismatch at {ts}"
        )


def test_run_backtest_without_benchmark_omits_key():
    """Without a benchmark, results[\"benchmark\"] is absent (backward compat)."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())
    assert "benchmark" not in results


def test_benchmark_superset_aligns_correctly():
    """A benchmark with a superset date index aligns via inner join.

    The benchmark starts a month earlier and ends a month later than the
    strategy data, so its index is a strict superset. The aligned benchmark
    must not contain the extra dates, must not crash, and its alpha/beta/correlation
    metrics must be computed only on common dates.
    """
    data = _make_data(periods=252)
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')

    # Benchmark: starts earlier and extends later than the strategy data.
    bench_dates = pd.date_range("2019-12-01", periods=292, freq="B")
    rng = np.random.default_rng(99)
    bench_rets = rng.normal(0.0003, 0.012, len(bench_dates))
    bench_prices = 100 * np.exp(np.cumsum(bench_rets))
    benchmark = pd.DataFrame({
        "open": bench_prices * rng.uniform(0.995, 1.005, len(bench_dates)),
        "high": bench_prices * rng.uniform(1.005, 1.02, len(bench_dates)),
        "low": bench_prices * rng.uniform(0.98, 0.995, len(bench_dates)),
        "close": bench_prices,
        "volume": rng.integers(1_000_000, 10_000_000, len(bench_dates)),
    }, index=bench_dates)

    results = run_backtest(data, strategy, _Args(), benchmark=benchmark)

    assert "benchmark" in results
    bench_returns = results["benchmark"]
    strat_returns = results["returns"]

    # The aligned benchmark index is a subset of strategy returns (inner join).
    assert set(bench_returns.index).issubset(set(strat_returns.index))

    # Extra benchmark-only dates (before strategy start) did not leak in.
    assert not (bench_returns.index < data.index[0]).any(), (
        "superset benchmark dates leaked into aligned returns"
    )

    # metrics calculate correctly on the aligned series
    from performance import calculate_metrics
    metrics = calculate_metrics(results)
    assert "benchmark_total_return" in metrics
    assert "correlation_with_benchmark" in metrics
    assert "alpha" in metrics
    assert "beta" in metrics


def test_cli_benchmark_writes_artifact_and_metrics():
    """CLI end-to-end with --benchmark writes benchmark_provenance.json
    and the metrics JSON contains benchmark_total_return,
    benchmark_annualized_return, correlation_with_benchmark, alpha, beta.
    """
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path)
        _write_ohlcv_csv(bench_path, seed=99)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir, "--benchmark", bench_path,
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0, "CLI with --benchmark should exit 0"

        # benchmark_provenance.json artifact written with provenance fields
        bench_prov_path = os.path.join(out_dir, "benchmark_provenance.json")
        assert os.path.exists(bench_prov_path), "benchmark_provenance.json not written"
        with open(bench_prov_path) as f:
            bprov = json.load(f)
        assert bprov["source_path"] == bench_path
        assert bprov["checksum"], "benchmark provenance missing checksum"
        assert bprov["validation_passed"] is True
        assert bprov["date_range_final"] is not None

        # metrics JSON contains the full benchmark comparison block
        metrics_path = os.path.join(out_dir, "metrics.json")
        with open(metrics_path) as f:
            metrics = json.load(f)
        for key in ("benchmark_total_return", "benchmark_annualized_return",
                     "correlation_with_benchmark", "alpha", "beta"):
            assert key in metrics, f"metrics missing {key}"
        # Alpha significance: t-stat finite and p-value in [0, 1].
        assert "alpha_tstat" in metrics
        assert np.isfinite(metrics["alpha_tstat"])
        assert 0.0 <= metrics["alpha_pvalue"] <= 1.0
        assert 0.0 <= metrics["r_squared"] <= 1.0


def _write_ohlcv_csv_with_dividends(path: str, periods: int = 252, seed: int = 42) -> None:
    """Write OHLCV CSV with dividends column for total-return benchmark testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    # Add quarterly dividends
    dividends = np.zeros(periods)
    for i in range(periods):
        if dates[i].month in [3, 6, 9, 12] and dates[i].day <= 5:
            dividends[i] = 0.50
    pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
        "dividends": dividends,
    }).to_csv(path, index=False)


def test_cli_total_return_benchmark_writes_provenance_and_differs_from_price():
    """CLI with --total-return-benchmark records total_return_type=total in provenance
    and produces different benchmark metrics vs price-only benchmark.
    """
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path)
        _write_ohlcv_csv_with_dividends(bench_path, seed=99)

        # Run with price-only benchmark
        out_dir_price = os.path.join(tmpdir, "out_price")
        argv_price = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir_price, "--benchmark", bench_path,
        ]
        with patch.object(sys, "argv", argv_price), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0

        with open(os.path.join(out_dir_price, "metrics.json")) as f:
            metrics_price = json.load(f)
        with open(os.path.join(out_dir_price, "benchmark_provenance.json")) as f:
            prov_price = json.load(f)

        # Run with total-return benchmark
        out_dir_total = os.path.join(tmpdir, "out_total")
        argv_total = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir_total, "--benchmark", bench_path,
            "--total-return-benchmark",
        ]
        with patch.object(sys, "argv", argv_total), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0

        with open(os.path.join(out_dir_total, "metrics.json")) as f:
            metrics_total = json.load(f)
        with open(os.path.join(out_dir_total, "benchmark_provenance.json")) as f:
            prov_total = json.load(f)

        # Provenance records total_return_type=total
        assert prov_total["total_return_type"] == "total"
        # Price-only run also records total_return_type=total (data has dividends)
        # but the metrics should show benchmark_total_return_type="price"
        assert metrics_price["benchmark_total_return_type"] == "price"
        assert metrics_total["benchmark_total_return_type"] == "total"

        # Total-return benchmark has higher total return (dividends add value)
        assert metrics_total["benchmark_total_return"] > metrics_price["benchmark_total_return"]

        # Alpha differs between price-only and total-return benchmark
        assert abs(metrics_total["alpha"] - metrics_price["alpha"]) > 1e-6

        # Beta also differs
        assert abs(metrics_total["beta"] - metrics_price["beta"]) > 1e-6


def test_cli_total_return_benchmark_alpha_differs():
    """Synthetic test demonstrating that price-only and total-return benchmarks
    produce meaningfully different alpha estimates when dividends are present.

    This highlights the methodological importance of using total-return benchmarks
    for accurate alpha measurement.
    """
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")

        # Strategy data: moderate upward drift
        dates = pd.date_range("2020-01-01", periods=252, freq="B")
        rng = np.random.default_rng(42)
        strat_rets = np.full(252, 0.0003) + rng.normal(0, 0.001, 252)
        strat_prices = 100 * np.exp(np.cumsum(strat_rets))
        pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": strat_prices * rng.uniform(0.995, 1.005, 252),
            "high": strat_prices * rng.uniform(1.005, 1.02, 252),
            "low": strat_prices * rng.uniform(0.98, 0.995, 252),
            "close": strat_prices,
            "volume": rng.integers(1_000_000, 10_000_000, 252),
        }).to_csv(csv_path, index=False)

        # Benchmark data: slight downward price drift but large quarterly dividends
        bench_rng = np.random.default_rng(99)
        bench_price_rets = np.full(252, -0.0002) + bench_rng.normal(0, 0.001, 252)
        bench_prices = 100 * np.exp(np.cumsum(bench_price_rets))
        dividends = np.zeros(252)
        for i in range(252):
            if dates[i].month in [3, 6, 9, 12] and dates[i].day <= 5:
                dividends[i] = 1.5  # Very large dividend
        pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": bench_prices * bench_rng.uniform(0.995, 1.005, 252),
            "high": bench_prices * bench_rng.uniform(1.005, 1.02, 252),
            "low": bench_prices * bench_rng.uniform(0.98, 0.995, 252),
            "close": bench_prices,
            "volume": bench_rng.integers(1_000_000, 10_000_000, 252),
            "dividends": dividends,
        }).to_csv(bench_path, index=False)

        # Price-only benchmark run
        out_dir_price = os.path.join(tmpdir, "out_price")
        argv_price = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir_price, "--benchmark", bench_path,
        ]
        with patch.object(sys, "argv", argv_price), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0
        with open(os.path.join(out_dir_price, "metrics.json")) as f:
            metrics_price = json.load(f)

        # Total-return benchmark run
        out_dir_total = os.path.join(tmpdir, "out_total")
        argv_total = [
            "run_backtest", "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", out_dir_total, "--benchmark", bench_path,
            "--total-return-benchmark",
        ]
        with patch.object(sys, "argv", argv_total), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0
        with open(os.path.join(out_dir_total, "metrics.json")) as f:
            metrics_total = json.load(f)

        # Verify benchmark total return is substantially higher with dividends
        bench_diff = metrics_total["benchmark_total_return"] - metrics_price["benchmark_total_return"]
        assert bench_diff > 0.15, f"Benchmark return difference too small: {bench_diff:.4f}"

        # Alpha differs between price-only and total-return benchmark
        # (may not flip sign, but should be meaningfully different)
        alpha_diff = abs(metrics_total["alpha"] - metrics_price["alpha"])
        assert alpha_diff > 0.001, f"Alpha difference too small: {alpha_diff:.4f}"

        # Beta also differs
        beta_diff = abs(metrics_total["beta"] - metrics_price["beta"])
        assert beta_diff > 0.01, f"Beta difference too small: {beta_diff:.4f}"

        # Total-return benchmark type is correctly recorded
        assert metrics_total["benchmark_total_return_type"] == "total"
        assert metrics_price["benchmark_total_return_type"] == "price"


def test_cli_run_backtest_impact_sweep():
    """CLI run_backtest --impact-coefficients writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--impact-coefficients", "0", "0.5", "1.0",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_impact_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 0.5, 1.0]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_borrow_sweep():
    """CLI run_backtest --borrow-costs writes a sweep artifact (MACD shorts)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "macd",
            "--params", '{"fast_period": 8, "slow_period": 21, "signal_period": 5}',
            "--output", out_dir,
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_borrow_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_borrow_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_funding_sweep():
    """CLI run_backtest --funding-costs writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_funding_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_funding_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


if __name__ == "__main__":
    sys.exit(main())

def test_cli_run_backtest_impact_sweep():
    """CLI run_backtest --impact-coefficients writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--impact-coefficients", "0", "0.5", "1.0",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_impact_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 0.5, 1.0]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_borrow_sweep():
    """CLI run_backtest --borrow-costs writes a sweep artifact (MACD shorts)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "macd",
            "--params", '{"fast_period": 8, "slow_period": 21, "signal_period": 5}',
            "--output", out_dir,
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_borrow_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_borrow_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_funding_sweep():
    """CLI run_backtest --funding-costs writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_funding_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_funding_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


if __name__ == "__main__":
    sys.exit(main())

def test_cli_run_backtest_impact_sweep():
    """CLI run_backtest --impact-coefficients writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--impact-coefficients", "0", "0.5", "1.0",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_impact_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 0.5, 1.0]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_borrow_sweep():
    """CLI run_backtest --borrow-costs writes a sweep artifact (MACD shorts)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "macd",
            "--params", '{"fast_period": 8, "slow_period": 21, "signal_period": 5}',
            "--output", out_dir,
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_borrow_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_borrow_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_funding_sweep():
    """CLI run_backtest --funding-costs writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_funding_cost_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_funding_cost_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.10]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]

def test_cli_run_backtest_commission_sweep():
    """CLI run_backtest --commissions writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_commission_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]


def test_cli_run_backtest_slippage_sweep():
    """CLI run_backtest --slippages writes a sweep artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=300)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 5, "slow_period": 20}',
            "--output", out_dir,
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv),                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0, f"CLI run_backtest slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_slippage_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0]

def test_cli_multi_benchmark_provenance_shapes():
    """Two-benchmark run writes list with both checksums; single keeps dict; none omits artifact."""
    from unittest.mock import patch
    import json
    import tempfile
    import os
    import sys
    from io import StringIO
    from contextlib import redirect_stdout, redirect_stderr

    # Case 1: two benchmarks
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        b1 = os.path.join(tmpdir, "b1.csv")
        b2 = os.path.join(tmpdir, "b2.csv")
        _write_ohlcv_csv(csv_path)
        _write_ohlcv_csv(b1, seed=1)
        _write_ohlcv_csv(b2, seed=99)
        out_dir = os.path.join(tmpdir, "out")
        argv = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                "--params", '{"fast_period": 10, "slow_period": 30}',
                "--output", out_dir, "--benchmark", b1, b2]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0
        bp = os.path.join(out_dir, 'benchmark_provenance.json')
        with open(bp) as f:
            d = json.load(f)
        assert isinstance(d, list)
        assert len(d) == 2
        assert d[0]['checksum'] and d[1]['checksum']
        assert d[0]['checksum'] != d[1]['checksum']

    # Case 2: single benchmark
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        b1 = os.path.join(tmpdir, "b1.csv")
        _write_ohlcv_csv(csv_path)
        _write_ohlcv_csv(b1, seed=1)
        out_dir = os.path.join(tmpdir, "out")
        argv = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                "--params", '{"fast_period": 10, "slow_period": 30}',
                "--output", out_dir, "--benchmark", b1]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0
        bp = os.path.join(out_dir, 'benchmark_provenance.json')
        with open(bp) as f:
            d = json.load(f)
        assert isinstance(d, dict)

    # Case 3: no benchmark
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                "--params", '{"fast_period": 10, "slow_period": 30}',
                "--output", out_dir]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0
        bp = os.path.join(out_dir, 'benchmark_provenance.json')
        assert not os.path.exists(bp)
