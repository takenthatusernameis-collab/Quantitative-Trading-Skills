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
from performance import calculate_metrics  # noqa: E402
from utils import (  # noqa: E402
    book_market_impact_cost,
    book_trade_ledger,
    build_market_model,
    held_book_weights,
)
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
                 multi_symbol=False, benchmark=None, risk_free_rate=None,
                 fill_rate=1.0, latency=0, panel_pricing="net-exposure"):
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
        self.fill_rate = fill_rate
        self.latency = latency
        self.panel_pricing = panel_pricing


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


def test_parse_args_accepts_fill_rate():
    """parse_args accepts --fill-rate and defaults it to 1.0."""
    from unittest.mock import patch

    with patch.object(sys, "argv", ["prog", "--data", "d.csv", "--fill-rate", "0.5"]):
        args = parse_args()
    assert args.fill_rate == 0.5

    with patch.object(sys, "argv", ["prog", "--data", "d.csv", "--fill-rates", "1.0", "0.5", "0.25"]):
        args = parse_args()
    assert args.fill_rates == [1.0, 0.5, 0.25]

    with patch.object(sys, "argv", ["prog", "--data", "d.csv"]):
        args = parse_args()
    assert args.fill_rate == 1.0
    assert args.fill_rates is None


def test_run_backtest_fill_rate_default_is_one():
    """fill_rate defaults to 1.0 and is recorded in the results config."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())
    assert results["config"]["fill_rate"] == 1.0


def test_run_backtest_fill_rate_one_identical_to_default():
    """fill_rate=1.0 must produce results identical to the default run."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    base = run_backtest(data, strategy, _Args())
    filled = run_backtest(data, strategy, _Args(fill_rate=1.0))
    pd.testing.assert_series_equal(base["returns"], filled["returns"])
    pd.testing.assert_series_equal(base["equity_curve"], filled["equity_curve"])
    assert base["trades"] == filled["trades"]


def test_run_backtest_fill_rate_scales_borrow_cost_with_position():
    """Partial fill scales the achieved position, so per-period borrow cost
    on a constant short position scales linearly with the fill rate."""
    args_full = _Args(commission=0.0, slippage=0.0, borrow_cost=0.10, fill_rate=1.0)
    args_half = _Args(commission=0.0, slippage=0.0, borrow_cost=0.10, fill_rate=0.5)
    daily = _make_flat_price_data(periods=60, freq="B")
    full = run_backtest(daily, _AlwaysShort(), args_full)
    half = run_backtest(daily, _AlwaysShort(), args_half)
    assert np.allclose(half["returns"], full["returns"] * 0.5)


def test_run_backtest_fill_rate_reduces_trading_costs():
    """On flat (zero-return) prices, strategy returns equal negative costs,
    so fill_rate < 1 must strictly reduce total cost and scale linearly."""
    data = _make_flat_price_data(periods=100)
    # donchian_breakout takes positions on flat data (period < len(data)),
    # producing position changes on which transaction costs are charged.
    strategy = build_strategy("donchian_breakout", '{"period": 20}')
    full = run_backtest(data, strategy, _Args(commission=0.001, slippage=0.0005,
                                              impact_coefficient=0.5, fill_rate=1.0))
    half = run_backtest(data, strategy, _Args(commission=0.001, slippage=0.0005,
                                              impact_coefficient=0.5, fill_rate=0.5))
    assert full["returns"].sum() < 0, "expected nonzero trading costs at full fill"
    assert half["returns"].sum() > full["returns"].sum(), (
        "half fill must reduce total trading cost"
    )
    assert np.isclose(half["returns"].sum(), full["returns"].sum() * 0.5, rtol=1e-6, atol=1e-12), (
        f"expected cost to halve with fill_rate=0.5: {half['returns'].sum()} vs "
        f"{full['returns'].sum() * 0.5}"
    )


def test_run_backtest_market_impact_scales_with_equity_not_price():
    """run_backtest market impact uses equity-scaled notional, not raw price.

    Regression test for a defect where the market-impact notional was computed
    as ``position_changes * close`` (the asset's unit price, ~$100) instead of
    ``position_changes * equity`` (the portfolio value, ~$100k). The impact
    coefficient was therefore understated by ~1000x and effectively a no-op,
    so the run_backtest CLI path disagreed with ``walk_forward._calculate_strategy_returns``
    (which already used the equity scaling) by a large margin.

    With identical commission/slippage/impact/borrow/funding, the two paths
    must now produce identical strategy returns.
    """
    from walk_forward import _calculate_strategy_returns

    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)

    args = _Args(commission=0.0002, slippage=0.0001, impact_coefficient=1.0)
    rb = run_backtest(data, strategy, args)

    wf = _calculate_strategy_returns(
        data, signals, 0.0002, 0.0001,
        impact_coefficient=1.0, adv_window=20,
        borrow_cost=0.0, funding_cost=0.0,
        initial_capital=100000.0,
    )

    diff = (rb["returns"] - wf).abs()
    assert diff.max() < 1e-12, (
        f"run_backtest market impact diverges from _calculate_strategy_returns: "
        f"max |diff| = {diff.max()}"
    )


def test_run_backtest_fill_rate_invalid_values_rejected():
    """fill_rate outside (0, 1] must raise ValueError."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    for rate in (0.0, -0.5, 1.5, 2.0):
        try:
            run_backtest(data, strategy, _Args(fill_rate=rate))
            assert False, f"expected ValueError for fill_rate={rate}"
        except ValueError:
            pass


def test_cli_run_backtest_fill_rate_sweep():
    """CLI run_backtest --fill-rates writes a sweep artifact."""
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
            "--fill-rates", "1.0", "0.5", "0.25",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0, f"CLI run_backtest fill-rate sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_fill_rate_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_fill_rate_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["fill_rates"] == [1.0, 0.5, 0.25]
        assert len(payload["results"]) == 3
        assert [r["fill_rate"] for r in payload["results"]] == [1.0, 0.5, 0.25]
        for r in payload["results"]:
            for key in ("total_return", "annualized_return", "sharpe_ratio", "max_drawdown"):
                assert key in r, f"sweep result missing {key}"


def test_parse_args_accepts_latencies():
    """parse_args accepts --latencies and defaults --latency to 0."""
    from unittest.mock import patch

    with patch.object(sys, "argv", ["prog", "--data", "d.csv", "--latencies", "0", "1", "2"]):
        args = parse_args()
    assert args.latencies == [0, 1, 2]

    with patch.object(sys, "argv", ["prog", "--data", "d.csv"]):
        args = parse_args()
    assert args.latency == 0
    assert args.latencies is None


def test_run_backtest_latency_default_is_zero():
    """latency defaults to 0 and is recorded in the results config."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())
    assert results["config"]["latency"] == 0


def test_run_backtest_latency_zero_identical_to_default():
    """latency=0 must produce results identical to the default run."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    base = run_backtest(data, strategy, _Args())
    delayed = run_backtest(data, strategy, _Args(latency=0))
    pd.testing.assert_series_equal(base["returns"], delayed["returns"])
    pd.testing.assert_series_equal(base["equity_curve"], delayed["equity_curve"])
    assert base["trades"] == delayed["trades"]


def test_run_backtest_latency_shifts_entry_timing():
    """Execution latency delays the first position entry by `latency` periods
    and reduces per-period borrow cost on a constant short position linearly."""
    data = _make_flat_price_data(periods=60, freq="B")
    strategy = _AlwaysShort()
    base = run_backtest(data, strategy, _Args(latency=0, borrow_cost=0.10))
    delayed = run_backtest(data, strategy, _Args(latency=2, borrow_cost=0.10))

    assert len(base["trades"]) == 1 and len(delayed["trades"]) == 1
    # First trade entry shifts by exactly `latency` periods (in index position).
    assert pd.Timestamp(base["trades"][0]["entry_date"]) == data.index[1]
    assert pd.Timestamp(delayed["trades"][0]["entry_date"]) == data.index[1 + 2]

    # Borrow cost accrues only while short; delaying entry by 2 periods removes
    # exactly two periods of borrow cost (commission/slippage/impact are zero).
    period_rate = 0.10 / 252
    base_cost = -float(base["returns"].sum())
    delayed_cost = -float(delayed["returns"].sum())
    assert np.isclose(delayed_cost, base_cost - 2 * period_rate, rtol=1e-6, atol=1e-12), (
        f"expected borrow cost to drop by 2 periods: {base_cost} -> {delayed_cost}"
    )


def test_cli_run_backtest_latency_sweep():
    """CLI run_backtest --latencies writes a sweep artifact."""
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
            "--latencies", "0", "1", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0, f"CLI run_backtest latency sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "run_backtest_latency_sweep.json")
        assert os.path.exists(sweep_path), "run_backtest_latency_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["latencies"] == [0, 1, 2]
        assert len(payload["results"]) == 3
        assert [r["latency"] for r in payload["results"]] == [0, 1, 2]
        for r in payload["results"]:
            for key in ("total_return", "annualized_return", "sharpe_ratio", "max_drawdown"):
                assert key in r, f"sweep result missing {key}"


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


def test_cli_multi_symbol_survivorship_sets_bias_controls_engaged():
    """A --multi-symbol run without --validate-point-in-time still reports
    bias_controls_engaged=True because survivorship screening ran."""
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "run_backtest", "--data", csv_path, "--multi-symbol",
            "--strategy", "cross_sectional_momentum",
            "--params", '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
            "--output", out_dir,
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()

        assert rc == 0

        summary_path = os.path.join(out_dir, "tear_sheet_summary.json")
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary.get("bias_controls_engaged") is True, \
            f"Expected bias_controls_engaged=True, got {summary.get('bias_controls_engaged')}"
        assert "survivorship_bias" in summary


def main() -> int:
    tests = TEST_REGISTRY

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
# Cross-path parity with the walk-forward / CPCV / out-of-sample paths
# ---------------------------------------------------------------------------
#
# A researcher who runs `run_backtest.py --multi-symbol` and
# `walk_forward.py cpcv --multi-symbol` on the same panel must be able to
# compare the two results. That requires a single shared market model
# (utils.build_market_model) and a single shared impact model
# (utils.market_impact_cost).
#
# The one remaining difference is the *position warmup*, not the market
# model: run_backtest.py opens the position on the first executable bar and
# charges the entry cost there, while walk_forward.py propagates the
# undefined first position as NaN and therefore drops that bar from the
# evaluation window. The two series are identical on every bar where both
# are defined.


def _panel_parity_returns(data, strategy, args):
    """Return (run_backtest returns, walk_forward returns) for the same panel."""
    from walk_forward import _calculate_strategy_returns

    results = run_backtest(data, strategy, args)
    signals = strategy.generate_signals(data)
    wf = _calculate_strategy_returns(
        data, signals,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        latency=args.latency,
        fill_rate=args.fill_rate,
        initial_capital=args.initial_capital,
    )
    return results["returns"], wf


def test_run_backtest_panel_matches_walk_forward_return_calculator():
    """The same panel, strategy and costs must produce the same return series
    through run_backtest.py and through walk_forward.py's return calculator.

    Regression guard: the two paths used different panel return conventions
    (the return of the mean price vs the mean of the per-asset returns) and
    different panel impact conventions (the whole portfolio notional against an
    aggregated pseudo-asset vs a per-asset notional against each asset's own
    ADV), so panel results were not comparable across the two CLIs.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )

    for impact in (0.0, 0.5):
        args = _Args(impact_coefficient=impact)
        rb, wf = _panel_parity_returns(data, strategy, args)

        common = rb.index.intersection(wf.index)
        assert len(common) > 0, "the two paths must share an evaluation window"
        np.testing.assert_array_equal(
            rb.reindex(common).to_numpy(),
            wf.reindex(common).to_numpy(),
            err_msg=(
                f"panel returns diverged between run_backtest.py and "
                f"walk_forward.py at impact_coefficient={impact}"
            ),
        )

        # The only difference is the warmup bar: run_backtest.py keeps the
        # bar on which the position is opened (and charges the entry cost),
        # walk_forward.py drops it.
        assert len(rb) - len(wf) == 1, (
            f"expected exactly one warmup bar of difference, got "
            f"{len(rb)} (run_backtest) vs {len(wf)} (walk_forward)"
        )
        assert rb.index[0] < wf.index[0]


def test_run_backtest_dict_panel_matches_walk_forward_return_calculator():
    """The dict panel format must reach the same cross-path parity."""
    data = _make_multiasset_dict(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )

    for impact in (0.0, 0.5):
        args = _Args(impact_coefficient=impact)
        rb, wf = _panel_parity_returns(data, strategy, args)
        common = rb.index.intersection(wf.index)
        assert len(common) > 0
        np.testing.assert_array_equal(
            rb.reindex(common).to_numpy(),
            wf.reindex(common).to_numpy(),
            err_msg=(
                f"dict panel returns diverged between run_backtest.py and "
                f"walk_forward.py at impact_coefficient={impact}"
            ),
        )


def test_run_backtest_panel_uses_mean_of_per_asset_returns():
    """A panel is priced as the mean of the per-asset returns, not as the
    return of the mean price series.

    The mean-price convention prices a price-weighted basket whose weights
    drift with the constituents' relative moves -- a rebalancing rule the
    position model does not represent -- while the mean-of-returns
    convention is the equal-weighted basket the impact model assumes.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    # Zero commission/slippage so the return series is exactly
    # position * market return.
    args = _Args(commission=0.0, slippage=0.0)
    rb = run_backtest(data, strategy, args)["returns"]

    positions = strategy.generate_signals(data).shift(1).fillna(0)
    expected = (positions * data["close"].pct_change().mean(axis=1)).dropna()
    np.testing.assert_allclose(
        rb.to_numpy(), expected.reindex(rb.index).to_numpy(), rtol=0, atol=1e-15
    )

    # ... and it is NOT the return of the mean price series.
    mean_price = data["close"].mean(axis=1)
    old_convention = (positions * mean_price.pct_change()).dropna()
    assert not np.allclose(
        rb.to_numpy(), old_convention.reindex(rb.index).to_numpy(), rtol=0, atol=1e-12
    ), "panel returns must differ from the return of the mean price series"


def test_run_backtest_panel_impact_splits_notional_across_assets():
    """A panel's market-impact cost must be the per-asset model: each
    constituent carries 1/n_assets of the traded notional and is measured
    against its own ADV.

    Regression guard: the whole portfolio notional was charged against an
    aggregated pseudo-asset ADV (mean close x mean volume), which overstated
    the impact of a panel by roughly n_assets.
    """
    periods = 300
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rng = np.random.default_rng(11)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, periods)))
    volume = rng.integers(1_000_000, 10_000_000, periods)

    n_assets = 4
    symbols = [f"S{i}" for i in range(n_assets)]
    cols = pd.MultiIndex.from_product(
        [["open", "high", "low", "close", "volume"], symbols]
    )
    panel = pd.DataFrame(0.0, index=dates, columns=cols)
    for sym in symbols:
        panel[("close", sym)] = prices
        panel[("open", sym)] = prices
        panel[("high", sym)] = prices
        panel[("low", sym)] = prices
        panel[("volume", sym)] = volume

    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    single = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": volume,
        },
        index=dates,
    )
    single_strategy = build_strategy(
        "sma_crossover", '{"fast_period": 5, "slow_period": 20}'
    )

    def _drag(target, strat, impact):
        base = run_backtest(
            target, strat, _Args(impact_coefficient=0.0)
        )["returns"]
        with_impact = run_backtest(
            target, strat, _Args(impact_coefficient=impact)
        )["returns"]
        return (base - with_impact).dropna()

    panel_drag = _drag(panel, strategy, 0.5)
    single_drag = _drag(single, single_strategy, 0.5)
    assert float(panel_drag.abs().sum()) > 0, "expected a non-zero impact drag"
    assert float(single_drag.abs().sum()) > 0, "expected a non-zero impact drag"

    # The panel drag must be materially smaller than charging the whole
    # notional against a single asset's ADV (the old behaviour): each
    # constituent carries 1/n_assets of the notional.
    ratio = float(panel_drag.abs().sum() / single_drag.abs().sum())
    assert ratio < 1.0 / (n_assets - 1), (
        f"panel impact drag is overstated (ratio {ratio}); expected roughly "
        f"1/{n_assets} of the single-asset drag"
    )


def test_run_backtest_panel_capacity_binds_on_least_liquid_constituent():
    """A panel's capacity estimate must use the equal-weighted basket rule
    (the least liquid constituent binds), matching walk_forward.py.

    Regression guard: the panel was collapsed into a pseudo-asset built from
    the mean close and the mean volume, which overstated the panel's
    liquidity and made the two paths report different capacities.
    """
    from walk_forward import estimate_capacity

    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    args = _Args(impact_coefficient=0.5)
    results = run_backtest(data, strategy, args)

    direct = estimate_capacity(data, 0.5, adv_window=args.adv_window)
    assert results["capacity"] is not None
    assert abs(results["capacity"] - direct["estimated_capacity"]) < 1e-9

    # Least liquid constituent binds: capacity = n_assets * max_impact *
    # min_i(ADV_notional_i) / impact_coefficient.
    n_assets = int(data["close"].shape[1])
    adv_notional = (
        data["volume"].rolling(window=args.adv_window, min_periods=1).mean()
        * data["close"]
    ).iloc[-1]
    expected = n_assets * 0.0005 * float(adv_notional.min()) / 0.5
    assert abs(results["capacity"] - expected) < 1e-6, (
        f"panel capacity {results['capacity']} does not match the "
        f"least-liquid-binds estimate {expected}"
    )


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


def test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance():
    """The run_backtest CLI tear-sheet JSON must pair each benchmark_metrics
    row with the provenance of the exact benchmark file it came from, so
    downstream consumers can trace corrected alpha/deflated alpha back to the
    file and checksum without relying on list order alone.
    """
    from unittest.mock import patch

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

        ts_path = os.path.join(out_dir, "tear_sheet_summary.json")
        with open(ts_path) as f:
            ts = json.load(f)

        bm = ts.get("benchmark_metrics")
        assert isinstance(bm, list), (
            f"tear-sheet benchmark_metrics missing or not a list. Keys: {sorted(ts.keys())}"
        )
        assert len(bm) == 2, f"expected 2 benchmark_metrics rows, got {len(bm)}"

        checksums = []
        for i, row in enumerate(bm):
            assert "benchmark_provenance" in row, (
                f"benchmark_metrics[{i}] missing benchmark_provenance"
            )
            prov = row["benchmark_provenance"]
            assert isinstance(prov, dict), (
                f"benchmark_metrics[{i}].benchmark_provenance not a dict"
            )
            assert prov.get("checksum"), (
                f"benchmark_metrics[{i}] provenance missing checksum"
            )
            assert prov["source_path"] in (b1, b2), (
                f"benchmark_metrics[{i}] provenance source_path not a benchmark file"
            )
            checksums.append(prov["checksum"])

        assert checksums[0] != checksums[1], (
            f"both benchmark rows share the same checksum {checksums[0]}"
        )

        # Top-level benchmark_provenance list matches the per-row provenances.
        prov_list = ts.get("benchmark_provenance")
        assert isinstance(prov_list, list), (
            f"top-level benchmark_provenance should be a list, got {type(prov_list)}"
        )
        assert len(prov_list) == 2
        top_checksums = [p["checksum"] for p in prov_list]
        assert top_checksums == checksums, (
            f"top-level provenance checksums {top_checksums} do not match "
            f"per-row checksums {checksums}"
        )


def test_cli_benchmark_name_propagates_to_provenance_and_tear_sheet():
    """--benchmark-name (and filename-stem fallback) must surface as
    ``name`` in the benchmark_provenance artifact, the tear-sheet summary's
    top-level benchmark_provenance, and each per-row benchmark_metrics
    benchmark_provenance, so a corrected alpha/deflated alpha can be traced
    back to an identified benchmark rather than list position alone.
    """
    from unittest.mock import patch
    import json

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
                "--output", out_dir, "--benchmark", b1, b2,
                "--benchmark-name", "AlphaBeta", "GammaDelta"]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0

        # Artifact: benchmark_provenance.json carries the supplied names in order.
        bp_path = os.path.join(out_dir, "benchmark_provenance.json")
        assert os.path.exists(bp_path), "benchmark_provenance.json not written"
        with open(bp_path) as f:
            bp = json.load(f)
        assert isinstance(bp, list) and len(bp) == 2
        assert [p["name"] for p in bp] == ["AlphaBeta", "GammaDelta"]
        assert bp[0]["checksum"] != bp[1]["checksum"], (
            "both benchmark rows share the same checksum"
        )

        # Tear-sheet JSON: top-level benchmark_provenance carries the names.
        ts_path = os.path.join(out_dir, "tear_sheet_summary.json")
        with open(ts_path) as f:
            ts = json.load(f)
        prov_list = ts.get("benchmark_provenance")
        assert isinstance(prov_list, list) and len(prov_list) == 2
        assert [p["name"] for p in prov_list] == ["AlphaBeta", "GammaDelta"]

        # Per-row: each benchmark_metrics row links to provenance with a name.
        bm = ts.get("benchmark_metrics")
        assert isinstance(bm, list) and len(bm) == 2
        row_names = [row["benchmark_provenance"]["name"] for row in bm]
        assert sorted(row_names) == ["AlphaBeta", "GammaDelta"]


def test_cli_benchmark_name_derives_from_filename_stem_when_omitted():
    """When --benchmark-name is omitted, each benchmark's provenance ``name``
    falls back to the file stem so the tear sheet remains identifiable.
    """
    from unittest.mock import patch
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        b1 = os.path.join(tmpdir, "custom_benchmark_one.csv")
        _write_ohlcv_csv(csv_path)
        _write_ohlcv_csv(b1, seed=1)
        out_dir = os.path.join(tmpdir, "out")
        argv = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                "--params", '{"fast_period": 10, "slow_period": 30}',
                "--output", out_dir, "--benchmark", b1]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = run_backtest_main()
        assert rc == 0

        bp_path = os.path.join(out_dir, "benchmark_provenance.json")
        with open(bp_path) as f:
            bp = json.load(f)
        assert isinstance(bp, dict)
        assert bp["name"] == "custom_benchmark_one"

        ts_path = os.path.join(out_dir, "tear_sheet_summary.json")
        with open(ts_path) as f:
            ts = json.load(f)
        prov = ts.get("benchmark_provenance")
        assert isinstance(prov, dict)
        assert prov["name"] == "custom_benchmark_one"

def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function.

    Regression guard for a defect where a test function was defined after
    the ``if __name__ == "__main__"`` block (and therefore unreachable at
    runtime) yet omitted from the registry, so the suite reported a lower
    count than the number of tests actually defined. A test defined but
    never registered is dead code: it cannot fail, so it provides no
    coverage of the feature it targets.

    The check is structural: every callable named ``test_*`` at module
    scope must appear in ``TEST_REGISTRY``, and every registry entry must
    be a real module-level function. No test is executed here.
    """
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}. A test outside the "
        "runner is dead code and provides no coverage."
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    # Labels must be unique so the runner cannot silently skip a test
    # (duplicate labels would overwrite each other in a name->fn map).
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )




def test_run_backtest_surfaces_capacity_in_results():
    """run_backtest surfaces a capacity estimate in its results summary.

    Mirrors the walk-forward/CPCV/out-of-sample paths: capacity is present
    and > 0 when impact is enabled, and None when impact is disabled (or
    ADV is not estimable).
    """
    from walk_forward import estimate_capacity

    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')

    enabled = run_backtest(data, strategy, _Args(impact_coefficient=0.5))
    assert "capacity" in enabled
    assert enabled["capacity"] is not None
    assert enabled["capacity"] > 0

    # Cross-check against a direct estimate_capacity call on the same frame.
    cap_frame = pd.DataFrame({"close": data["close"], "volume": data["volume"]})
    direct = estimate_capacity(cap_frame, 0.5, adv_window=20)
    assert abs(enabled["capacity"] - direct["estimated_capacity"]) < 1e-9

    disabled = run_backtest(data, strategy, _Args(impact_coefficient=0.0))
    assert disabled["capacity"] is None


def test_run_backtest_capacity_omits_when_volume_unavailable():
    """Capacity is None (not an exception) when the data has no volume column."""
    data = _make_data().drop(columns=["volume"])
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args(impact_coefficient=0.5))
    assert results["capacity"] is None


def test_run_backtest_surfaces_capacity_trend_in_results():
    """run_backtest also reports the capacity trend of the backtest window:
    the per-period capacity distribution, so a liquidity squeeze inside the
    window is visible instead of being hidden behind the last bar's
    point-in-time reading. None when impact is disabled."""
    from walk_forward import estimate_capacity

    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')

    enabled = run_backtest(data, strategy, _Args(impact_coefficient=0.5))
    trend = enabled.get("capacity_trend")
    assert trend is not None
    assert trend["min_capacity"] > 0
    assert trend["last_capacity"] == enabled["capacity"]

    cap_frame = pd.DataFrame({"close": data["close"], "volume": data["volume"]})
    direct = estimate_capacity(cap_frame, 0.5, adv_window=20)
    assert trend["min_capacity"] == direct["capacity_trend"]["min_capacity"]

    disabled = run_backtest(data, strategy, _Args(impact_coefficient=0.0))
    assert disabled["capacity"] is None
    assert disabled["capacity_trend"] is None

    no_volume = _make_data().drop(columns=["volume"])
    missing = run_backtest(no_volume, strategy, _Args(impact_coefficient=0.5))
    assert missing["capacity"] is None
    assert missing["capacity_trend"] is None


def test_run_backtest_surfaces_book_diagnostic_for_a_panel():
    """A panel backtest reports the book the strategy actually holds.

    The panel path prices a portfolio as `net_exposure x mean(asset
    returns)`, so the diagnostic reports the gross book, the turnover the
    cost model charges against the turnover the book really has, and the
    gap between the framework's P&L and the book P&L. The reported P&L
    itself is unchanged.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    results = run_backtest(data, strategy, _Args())

    diag = results.get("book_diagnostic")
    assert diag is not None, "a panel backtest must surface the book diagnostic"
    for key in (
        "n_periods",
        "n_periods_with_book",
        "gross_book",
        "net_exposure",
        "gross_turnover",
        "framework_turnover",
        "return_gap_bps",
        "return_gap_total",
        "book_total_return",
        "framework_total_return_after_costs",
    ):
        assert key in diag, f"missing diagnostic key: {key}"

    assert diag["n_assets"] == 5
    assert diag["n_periods_with_book"] > 0
    assert diag["gross_book"] > 0
    # The book's net exposure is the scalar signal the framework priced.
    assert abs(diag["net_exposure"] - diag["framework_net_exposure"]) < 1e-12
    # The book rotates more than the net exposure does, so the cost model
    # charges less turnover than the book actually has.
    assert diag["gross_turnover"] > diag["framework_turnover"]
    # The diagnostic is consistent with the reported P&L.
    reported = float((1 + results["returns"]).prod() - 1)
    assert abs(diag["framework_total_return_after_costs"] - reported) < 1e-12


def test_run_backtest_book_diagnostic_book_return_matches_manual_computation():
    """The book return is the weighted sum of the per-asset returns.

    Recomputed here by hand (one-period execution lag, no costs) so the
    diagnostic's arithmetic is checked against an independent computation
    rather than against itself.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=4, seed=99)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    results = run_backtest(data, strategy, _Args())
    diag = results["book_diagnostic"]
    assert diag is not None

    weights = strategy.generate_target_weights(data)
    assert weights is not None
    held = weights.shift(1)  # the book is executed with a one-period lag
    asset_returns = data["close"].pct_change()
    manual_book_return = (held * asset_returns).sum(axis=1).reindex(
        results["returns"].index
    )
    expected = float((1 + manual_book_return).prod() - 1)
    assert abs(diag["book_total_return"] - expected) < 1e-12


def test_run_backtest_book_diagnostic_absent_for_single_asset():
    """A single-asset run has no per-asset book, so no diagnostic."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    results = run_backtest(data, strategy, _Args())
    assert results.get("book_diagnostic") is None


def test_run_backtest_book_diagnostic_absent_for_strategy_without_a_book():
    """A panel run of a strategy that exposes no book has no diagnostic."""
    data = _make_multiasset_multiindex(n=300, n_assets=2, seed=5)
    strategy = build_strategy("zscore_mean_reversion", '{"period": 20}')
    results = run_backtest(data, strategy, _Args())
    assert results.get("book_diagnostic") is None


def test_run_backtest_flat_net_exposure_panel_reports_the_book_it_holds():
    """A market-neutral book is not a flat book.

    With symmetric quantiles the cross-sectional momentum signal is flat
    (net exposure 0) and the framework refuses to backtest it. The error
    now says why: the strategy does hold a book, the net-exposure pricing
    convention just cannot see it.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}',
    )
    try:
        run_backtest(data, strategy, _Args())
        assert False, "expected ValueError for a flat net exposure"
    except ValueError as exc:
        message = str(exc)
        assert "never takes a position" in message
        assert "does hold a book" in message, message


def test_run_backtest_book_pricing_backtests_a_market_neutral_book():
    """A market-neutral book is backtestable under the book pricing mode.

    With symmetric quantiles the cross-sectional momentum signal is flat
    (net exposure 0), so the net-exposure convention refuses to price it
    ("never takes a position"). Under `--panel-pricing book` the strategy
    *does* hold a position -- a long/short book with a positive gross
    exposure -- and the run completes. The reported return is the true book
    return, recomputed here by hand from the strategy's own weights.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}',
    )
    results = run_backtest(data, strategy, _Args(panel_pricing="book"))

    assert results["panel_pricing"] == "book"
    diag = results["book_diagnostic"]
    assert diag is not None
    # The book is open (gross exposure) but flat in net exposure.
    assert diag["gross_book"] > 0
    assert abs(diag["net_exposure"]) < 1e-12
    assert diag["n_periods_with_book"] > 0

    # The reported return is the book return: sum_i w_i r_i of the held
    # book, minus the (unchanged, net-exposure-based) cost series. With
    # zero costs the two are the same number.
    zero_cost = run_backtest(
        data,
        build_strategy(
            "cross_sectional_momentum",
            '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}',
        ),
        _Args(commission=0.0, slippage=0.0, panel_pricing="book"),
    )
    weights = strategy.generate_target_weights(data)
    assert weights is not None
    held = weights.shift(1)  # the book is executed with a one-period lag
    manual = (held * data["close"].pct_change()).sum(axis=1).reindex(
        zero_cost["returns"].index
    )
    expected = float((1 + manual).prod() - 1)
    reported = float((1 + zero_cost["returns"]).prod() - 1)
    assert abs(reported - expected) < 1e-12


def test_run_backtest_book_pricing_differs_by_the_measured_return_gap():
    """The two pricing modes differ by exactly the measured return gap.

    The net-exposure mode prices `net_exposure x mean(asset returns)`; the
    book mode prices `sum_i w_i r_i`. The difference between them is the
    gap the panel book diagnostic measures -- and the sign of that gap is
    not stable, so a panel result must always state its pricing mode.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    params = '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}'

    def _run(pricing):
        return run_backtest(
            data,
            build_strategy("cross_sectional_momentum", params),
            # Zero costs so the two modes differ by the pricing convention
            # alone, with no transaction-cost difference mixed in.
            _Args(commission=0.0, slippage=0.0, panel_pricing=pricing),
        )

    net_exposure = _run("net-exposure")
    book = _run("book")
    assert net_exposure["panel_pricing"] == "net-exposure"
    assert book["panel_pricing"] == "book"

    # Same bars in both modes.
    assert net_exposure["returns"].index.equals(book["returns"].index)

    ne_total = float((1 + net_exposure["returns"]).prod() - 1)
    book_total = float((1 + book["returns"]).prod() - 1)
    diag = net_exposure["book_diagnostic"]
    assert diag is not None
    # The measured gap between the two conventions.
    assert abs((ne_total - book_total) - diag["return_gap_total"]) < 1e-12
    # The per-period difference is the framework pricing minus the book.
    difference = net_exposure["returns"] - book["returns"]
    assert abs(difference.mean() * 1e4 - diag["return_gap_bps"]) < 1e-9


def test_run_backtest_net_exposure_pricing_is_the_default_and_is_unchanged():
    """The default mode is net-exposure, and it reproduces the explicit mode
    exactly: no published number moves when the mode is not requested."""
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    default = run_backtest(data, strategy, _Args())
    explicit = run_backtest(data, strategy, _Args(panel_pricing="net-exposure"))

    assert default["panel_pricing"] == "net-exposure"
    assert explicit["panel_pricing"] == "net-exposure"
    assert default["config"]["panel_pricing"] == "net-exposure"
    assert default["config"]["panel_pricing_effective"] == "net-exposure"
    pd.testing.assert_series_equal(default["returns"], explicit["returns"])


def test_run_backtest_book_pricing_falls_back_when_no_book_is_available():
    """A strategy that exposes no book falls back to net-exposure pricing,
    and the fallback is recorded rather than silently applied."""
    data = _make_multiasset_multiindex(n=300, n_assets=2, seed=5)
    strategy = build_strategy("zscore_mean_reversion", '{"period": 20}')
    results = run_backtest(data, strategy, _Args(panel_pricing="book"))

    assert results["config"]["panel_pricing"] == "book"
    assert results["config"]["panel_pricing_effective"] == "net-exposure"
    assert results["panel_pricing"] == "net-exposure"
    assert results.get("book_diagnostic") is None


def test_run_backtest_book_pricing_on_a_single_asset_is_net_exposure_pricing():
    """A single asset has no per-asset book: the book mode is a no-op and the
    numbers are the net-exposure ones."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    net_exposure = run_backtest(data, strategy, _Args())
    book = run_backtest(data, strategy, _Args(panel_pricing="book"))

    assert book["panel_pricing"] == "net-exposure"
    pd.testing.assert_series_equal(net_exposure["returns"], book["returns"])


# ---------------------------------------------------------------------------
# Book cost basis (Phase 2b): the costs are charged on the book, not on the
# net exposure.
# ---------------------------------------------------------------------------


def _held_book_of(strategy, data, lag=1, fill_rate=1.0):
    """The book the engine actually holds, rebuilt from the strategy's own
    weights (an independent path from the engine's internals)."""
    market = build_market_model(data)
    weights = strategy.generate_target_weights(data)
    assert weights is not None
    return market, held_book_weights(
        weights, market, lag=lag, fill_rate=fill_rate
    )


def test_run_backtest_book_pricing_charges_the_gross_turnover_of_the_book():
    """The transaction cost of a book is charged on its gross turnover.

    The net-exposure convention can only see ``|d net exposure|``, which is
    zero for a market-neutral book: the book rotates (it changes which names
    it holds) while its net exposure stays flat, so the net-exposure cost
    model charges it nothing. The book cost basis charges the rotation it
    actually pays for: ``sum_i |dw_i| x (commission + slippage)``.

    The charged amount is recomputed here by hand from the strategy's own
    weights, so the test does not compare the engine against itself.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    params = '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}'
    commission, slippage = 0.0002, 0.0001

    results = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(commission=commission, slippage=slippage, panel_pricing="book"),
    )

    market, held = _held_book_of(
        build_strategy("cross_sectional_momentum", params), data
    )
    gross_turnover = held.diff().abs().sum(axis=1, min_count=1)
    expected_cost = gross_turnover * (commission + slippage)

    # The market-neutral book's net exposure never changes, so the
    # net-exposure cost model would charge it (almost) nothing.
    diag = results["book_diagnostic"]
    assert diag["framework_turnover"] < 1e-12
    assert diag["gross_turnover"] > 0.0
    # ... while the book cost basis charges its own gross turnover.
    assert diag["charged_turnover"] == diag["gross_turnover"]
    assert diag["cost_basis"] == "book"

    # The charged cost is exactly the hand-computed gross-turnover cost:
    # the reported return is the book return minus that cost.
    book_return = (held * data["close"].pct_change()).sum(axis=1, min_count=1)
    manual = (book_return - expected_cost).dropna()
    assert manual.index.equals(results["returns"].index)
    expected_total = float((1 + manual).prod() - 1)
    reported_total = float((1 + results["returns"]).prod() - 1)
    assert abs(reported_total - expected_total) < 1e-12

    # The book is charged strictly more than the flat net exposure would be.
    assert expected_cost.sum() > 0.0


def test_run_backtest_book_pricing_charges_borrow_on_the_short_leg():
    """A book's borrow cost is charged on its short legs.

    The net-exposure convention charges borrow on the *net* short exposure:
    a long net position pays nothing (and a day when the net exposure turns
    negative it pays on the whole net short). A book holds explicit short
    legs, so it pays for them on every day it holds them, even when the
    net exposure is long.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    # Asymmetric quantiles -> a long net exposure, but a real short book.
    params = '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}'
    borrow = 0.03
    ann_factor = 252

    net_exposure = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(commission=0.0, slippage=0.0, borrow_cost=borrow),
    )
    book = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(commission=0.0, slippage=0.0, borrow_cost=borrow,
              panel_pricing="book"),
    )

    # The net-exposure position is long on average: it pays borrow only on
    # the days its net exposure turns negative.
    strategy = build_strategy("cross_sectional_momentum", params)
    signals = strategy.generate_signals(data)
    positions = signals.shift(1).fillna(0)
    net_short = positions.clip(upper=0).abs()
    assert net_short.mean() < positions.mean()

    _, held = _held_book_of(strategy, data)
    short_legs = held.clip(upper=0).abs().sum(axis=1, min_count=1)
    assert short_legs.mean() > 0
    # The book holds short legs on (almost) every day it is invested, so it
    # pays more borrow than the net exposure does.
    assert short_legs.mean() > net_short.mean()

    # Both modes are charged exactly the borrow their own basis implies
    # (recomputed here by hand, with zero commission, slippage and impact).
    market = build_market_model(data)
    raw_returns = market["raw_returns"]
    expected_net = (positions * raw_returns - net_short * (borrow / ann_factor)).dropna()
    assert expected_net.index.equals(net_exposure["returns"].index)
    assert abs(
        float((1 + expected_net).prod() - 1)
        - float((1 + net_exposure["returns"]).prod() - 1)
    ) < 1e-12

    book_return = (held * data["close"].pct_change()).sum(axis=1, min_count=1)
    expected_book = (book_return - short_legs * (borrow / ann_factor)).dropna()
    assert expected_book.index.equals(book["returns"].index)
    assert abs(
        float((1 + expected_book).prod() - 1)
        - float((1 + book["returns"]).prod() - 1)
    ) < 1e-12


def test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate():
    """The book's market impact is charged per asset, against that asset's
    own ADV, and scales with the fill rate.

    The net-exposure impact model splits the portfolio notional equally over
    the constituents; the book model charges each asset the notional it
    actually trades (``|dw_i| x equity``) against that asset's own ADV.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    params = '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}'

    market, held = _held_book_of(
        build_strategy("cross_sectional_momentum", params), data
    )
    full = book_market_impact_cost(
        held_book=held,
        raw_returns=market["raw_returns"],
        close=market["close"],
        volume=market["volume"],
        impact_coefficient=0.5,
        adv_window=20,
        initial_capital=100000,
    )
    assert full is not None
    assert full.mean() > 0

    # Impact is disabled with a zero coefficient (a no-op, not a silent
    # charge).
    assert book_market_impact_cost(
        held_book=held,
        raw_returns=market["raw_returns"],
        close=market["close"],
        volume=market["volume"],
        impact_coefficient=0.0,
    ) is None

    # The impact scales with the fill rate: the notional traded per asset
    # is proportional to the weight change, which is scaled by the fill.
    _, held_half = _held_book_of(
        build_strategy("cross_sectional_momentum", params), data, fill_rate=0.5
    )
    half = book_market_impact_cost(
        held_book=held_half,
        raw_returns=market["raw_returns"],
        close=market["close"],
        volume=market["volume"],
        impact_coefficient=0.5,
        adv_window=20,
        initial_capital=100000,
    )
    assert half is not None
    ratio = (half.dropna() / full.dropna()).replace([np.inf, -np.inf], np.nan).dropna()
    assert len(ratio) > 0
    assert np.allclose(ratio.to_numpy(), 0.5, rtol=1e-9, atol=1e-12)

    # A market-neutral book is charged impact even though its net exposure
    # never changes (the net-exposure model charges it nothing).
    charged = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(commission=0.0, slippage=0.0, impact_coefficient=0.5,
              panel_pricing="book"),
    )
    zero_cost = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(commission=0.0, slippage=0.0, impact_coefficient=0.0,
              panel_pricing="book"),
    )
    assert charged["book_diagnostic"]["framework_turnover"] < 1e-12
    assert float((1 + charged["returns"]).prod() - 1) < float(
        (1 + zero_cost["returns"]).prod() - 1
    )


def test_run_backtest_book_pricing_builds_a_trade_ledger():
    """A market-neutral book produces trade records.

    The net-exposure ledger is built from the scalar net exposure, so a
    market-neutral book produced no trade record at all and the trade-level
    statistics (win rate, profit factor, expectancy) were empty. The book
    ledger is built from the book: one round trip per asset and direction.
    """
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    params = '{"lookback": 20, "top_quantile": 0.2, "bottom_quantile": 0.2}'
    results = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(panel_pricing="book"),
    )

    trades = results["trades"]
    assert len(trades) > 0
    symbols = {t["symbol"] for t in trades}
    assert len(symbols) > 1
    for trade in trades:
        assert "pnl" in trade and "return" in trade
        assert "entry_date" in trade and "exit_date" in trade
        assert trade["entry_date"] <= trade["exit_date"]

    # The trade-level statistics are now available.
    metrics = calculate_metrics(results)
    assert metrics["total_trades"] == len(trades)
    assert 0.0 <= metrics["win_rate"] <= 1.0
    assert "profit_factor" in metrics


def test_book_trade_ledger_prices_each_leg_at_its_own_close():
    """The book ledger: one round trip per asset and direction, priced at the
    asset's own close, with the sign carried by the weight."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    close = pd.DataFrame(
        {
            "A": [10.0, 11.0, 12.0, 11.0, 10.0],
            "B": [20.0, 19.0, 18.0, 19.0, 20.0],
        },
        index=dates,
    )
    held = pd.DataFrame(
        {
            # A: long for two bars, then flat.
            "A": [0.5, 0.5, 0.0, 0.0, 0.0],
            # B: short from bar 2 to the end of the sample.
            "B": [0.0, 0.0, -0.5, -0.5, -0.5],
        },
        index=dates,
    )

    trades = book_trade_ledger(held, close)
    assert len(trades) == 2

    long_leg = [t for t in trades if t["symbol"] == "A"][0]
    assert long_leg["entry_date"] == "2020-01-01"
    assert long_leg["exit_date"] == "2020-01-03"
    # +0.5 weight over a 10 -> 12 move: +1.0 of P&L, +10% on the entry.
    assert abs(long_leg["pnl"] - 1.0) < 1e-12
    assert abs(long_leg["return"] - 0.1) < 1e-12

    short_leg = [t for t in trades if t["symbol"] == "B"][0]
    assert short_leg["entry_date"] == "2020-01-03"
    assert short_leg.get("closed_at_end") is True
    # -0.5 weight over an 18 -> 20 move: -1.0 of P&L (the sign is carried
    # by the weight, so a losing short records a negative P&L).
    assert abs(short_leg["pnl"] + 1.0) < 1e-12
    assert short_leg["pnl"] < 0


def test_run_backtest_net_exposure_numbers_are_unchanged_by_the_book_cost_basis():
    """The net-exposure path is bit-identical after the book cost basis was
    added: the default path must not move by a single float."""
    data = _make_multiasset_multiindex(n=300, n_assets=5, seed=42)
    params = '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}'
    results = run_backtest(
        data,
        build_strategy("cross_sectional_momentum", params),
        _Args(impact_coefficient=0.5, borrow_cost=0.03, funding_cost=0.02),
    )
    # Pinned: the net-exposure numbers (see references/cost_models.md).
    assert abs(
        float((1 + results["returns"]).prod() - 1) - 0.20058890955981612
    ) < 1e-12
    # The diagnostic still reports the net-exposure cost basis.
    diag = results["book_diagnostic"]
    assert diag["cost_basis"] == "net-exposure"
    assert diag["charged_turnover"] == diag["framework_turnover"]


def test_cli_data_provenance_reproducible_across_runs():
    """Running the CLI twice with identical inputs yields byte-identical
    data_provenance.json (load_timestamp sanitized to source mtime)."""
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path)
        out1 = os.path.join(tmpdir, "out1")
        out2 = os.path.join(tmpdir, "out2")
        argv1 = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                 "--params", '{"fast_period": 10, "slow_period": 30}',
                 "--output", out1, "--validate-point-in-time"]
        with patch.object(sys, "argv", argv1), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            assert run_backtest_main() == 0
        argv2 = ["run_backtest", "--data", csv_path, "--strategy", "sma_crossover",
                 "--params", '{"fast_period": 10, "slow_period": 30}',
                 "--output", out2, "--validate-point-in-time"]
        with patch.object(sys, "argv", argv2), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            assert run_backtest_main() == 0
        with open(os.path.join(out1, "data_provenance.json"), "rb") as f:
            a = f.read()
        with open(os.path.join(out2, "data_provenance.json"), "rb") as f:
            b = f.read()
        assert a == b, "data_provenance.json not reproducible across runs"


TEST_REGISTRY = [
    ("test_signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
    ("test_run_backtest_flat_strategy_raises", test_run_backtest_flat_strategy_raises),
    ("test_run_backtest_flat_long_lookback_raises", test_run_backtest_flat_long_lookback_raises),
    ("test_run_backtest_active_strategy_succeeds", test_run_backtest_active_strategy_succeeds),
    ("test_run_backtest_trade_analytics_populated", test_run_backtest_trade_analytics_populated),
    ("test_run_backtest_n_trials_surfaces_deflated_sharpe", test_run_backtest_n_trials_surfaces_deflated_sharpe),
    ("test_run_backtest_without_n_trials_omits_deflated_sharpe", test_run_backtest_without_n_trials_omits_deflated_sharpe),
    ("test_run_backtest_deflated_sharpe_matches_direct_call", test_run_backtest_deflated_sharpe_matches_direct_call),
    ("test_parse_args_accepts_n_trials", test_parse_args_accepts_n_trials),
    ("test_run_backtest_records_both_legs_of_direct_long_short_flip", test_run_backtest_records_both_legs_of_direct_long_short_flip),
    ("test_run_backtest_short_leg_pnl_moves_opposite_to_price", test_run_backtest_short_leg_pnl_moves_opposite_to_price),
    ("test_run_backtest_long_leg_pnl_moves_with_price", test_run_backtest_long_leg_pnl_moves_with_price),
    ("test_run_backtest_closes_final_open_position_at_end_of_data", test_run_backtest_closes_final_open_position_at_end_of_data),
    ("test_run_backtest_trade_ledger_valid_for_all_registered_strategies", test_run_backtest_trade_ledger_valid_for_all_registered_strategies),
    ("test_parse_args_requires_data_argument", test_parse_args_requires_data_argument),
    ("test_parse_args_accepts_valid_arguments", test_parse_args_accepts_valid_arguments),
    ("test_parse_args_custom_values", test_parse_args_custom_values),
    ("test_parse_args_invalid_commission_type", test_parse_args_invalid_commission_type),
    ("test_parse_args_invalid_initial_capital_type", test_parse_args_invalid_initial_capital_type),
    ("test_run_backtest_constant_returns_deflated_sharpe", test_run_backtest_constant_returns_deflated_sharpe),
    ("test_run_backtest_borrow_cost_frequency_aware", test_run_backtest_borrow_cost_frequency_aware),
    ("test_run_backtest_market_impact_scales_with_equity_not_price", test_run_backtest_market_impact_scales_with_equity_not_price),
    ("test_parse_args_accepts_fill_rate", test_parse_args_accepts_fill_rate),
    ("test_run_backtest_fill_rate_default_is_one", test_run_backtest_fill_rate_default_is_one),
    ("test_run_backtest_fill_rate_one_identical_to_default", test_run_backtest_fill_rate_one_identical_to_default),
    ("test_run_backtest_fill_rate_scales_borrow_cost_with_position", test_run_backtest_fill_rate_scales_borrow_cost_with_position),
    ("test_run_backtest_fill_rate_reduces_trading_costs", test_run_backtest_fill_rate_reduces_trading_costs),
    ("test_run_backtest_fill_rate_invalid_values_rejected", test_run_backtest_fill_rate_invalid_values_rejected),
    ("test_cli_run_backtest_fill_rate_sweep", test_cli_run_backtest_fill_rate_sweep),
    ("test_parse_args_accepts_latencies", test_parse_args_accepts_latencies),
    ("test_run_backtest_latency_default_is_zero", test_run_backtest_latency_default_is_zero),
    ("test_run_backtest_latency_zero_identical_to_default", test_run_backtest_latency_zero_identical_to_default),
    ("test_run_backtest_latency_shifts_entry_timing", test_run_backtest_latency_shifts_entry_timing),
    ("test_cli_run_backtest_latency_sweep", test_cli_run_backtest_latency_sweep),
    ("test_run_backtest_serializes_data_provenance_into_results", test_run_backtest_serializes_data_provenance_into_results),
    ("test_run_backtest_serializes_panel_provenance_dict", test_run_backtest_serializes_panel_provenance_dict),
    ("test_run_backtest_without_provenance_omits_key", test_run_backtest_without_provenance_omits_key),
    ("test_run_backtest_point_in_time_validation_recorded", test_run_backtest_point_in_time_validation_recorded),
    ("test_run_backtest_point_in_time_detects_duplicate_timestamps", test_run_backtest_point_in_time_detects_duplicate_timestamps),
    ("test_handle_point_in_time_results_strictness_matrix", test_handle_point_in_time_results_strictness_matrix),
    ("test_run_backtest_point_in_time_panel_validates_each_symbol", test_run_backtest_point_in_time_panel_validates_each_symbol),
    ("test_parse_args_accepts_validation_and_multi_symbol_flags", test_parse_args_accepts_validation_and_multi_symbol_flags),
    ("test_cli_writes_data_provenance_artifact", test_cli_writes_data_provenance_artifact),
    ("test_cli_multi_symbol_writes_survivorship_artifact", test_cli_multi_symbol_writes_survivorship_artifact),
    ("test_cli_multi_symbol_survivorship_sets_bias_controls_engaged", test_cli_multi_symbol_survivorship_sets_bias_controls_engaged),
    ("test_run_backtest_multi_asset_cross_sectional_momentum", test_run_backtest_multi_asset_cross_sectional_momentum),
    ("test_run_backtest_multi_asset_dual_momentum", test_run_backtest_multi_asset_dual_momentum),
    ("test_run_backtest_multi_asset_dict_cross_sectional_momentum", test_run_backtest_multi_asset_dict_cross_sectional_momentum),
    ("test_run_backtest_multi_asset_dict_dual_momentum", test_run_backtest_multi_asset_dict_dual_momentum),
    ("test_run_backtest_panel_matches_walk_forward_return_calculator", test_run_backtest_panel_matches_walk_forward_return_calculator),
    ("test_run_backtest_dict_panel_matches_walk_forward_return_calculator", test_run_backtest_dict_panel_matches_walk_forward_return_calculator),
    ("test_run_backtest_panel_uses_mean_of_per_asset_returns", test_run_backtest_panel_uses_mean_of_per_asset_returns),
    ("test_run_backtest_panel_impact_splits_notional_across_assets", test_run_backtest_panel_impact_splits_notional_across_assets),
    ("test_run_backtest_panel_capacity_binds_on_least_liquid_constituent", test_run_backtest_panel_capacity_binds_on_least_liquid_constituent),
    ("test_run_backtest_with_benchmark_attaches_aligned_returns", test_run_backtest_with_benchmark_attaches_aligned_returns),
    ("test_run_backtest_without_benchmark_omits_key", test_run_backtest_without_benchmark_omits_key),
    ("test_benchmark_superset_aligns_correctly", test_benchmark_superset_aligns_correctly),
    ("test_cli_benchmark_writes_artifact_and_metrics", test_cli_benchmark_writes_artifact_and_metrics),
    ("test_cli_total_return_benchmark_writes_provenance_and_differs_from_price", test_cli_total_return_benchmark_writes_provenance_and_differs_from_price),
    ("test_cli_total_return_benchmark_alpha_differs", test_cli_total_return_benchmark_alpha_differs),
    ("test_cli_run_backtest_impact_sweep", test_cli_run_backtest_impact_sweep),
    ("test_cli_run_backtest_borrow_sweep", test_cli_run_backtest_borrow_sweep),
    ("test_cli_run_backtest_funding_sweep", test_cli_run_backtest_funding_sweep),
    ("test_cli_run_backtest_commission_sweep", test_cli_run_backtest_commission_sweep),
    ("test_cli_run_backtest_slippage_sweep", test_cli_run_backtest_slippage_sweep),
    ("test_cli_multi_benchmark_provenance_shapes", test_cli_multi_benchmark_provenance_shapes),
    ("test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance", test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance),
    ("test_cli_benchmark_name_propagates_to_provenance_and_tear_sheet", test_cli_benchmark_name_propagates_to_provenance_and_tear_sheet),
    ("test_cli_benchmark_name_derives_from_filename_stem_when_omitted", test_cli_benchmark_name_derives_from_filename_stem_when_omitted),
    ("test_cli_data_provenance_reproducible_across_runs", test_cli_data_provenance_reproducible_across_runs),
    ("test_main_registers_every_module_level_test", test_main_registers_every_module_level_test),
    ("test_run_backtest_surfaces_capacity_in_results", test_run_backtest_surfaces_capacity_in_results),
    ("test_run_backtest_capacity_omits_when_volume_unavailable", test_run_backtest_capacity_omits_when_volume_unavailable),
    ("test_run_backtest_surfaces_capacity_trend_in_results", test_run_backtest_surfaces_capacity_trend_in_results),
    ("test_run_backtest_surfaces_book_diagnostic_for_a_panel", test_run_backtest_surfaces_book_diagnostic_for_a_panel),
    ("test_run_backtest_book_diagnostic_book_return_matches_manual_computation", test_run_backtest_book_diagnostic_book_return_matches_manual_computation),
    ("test_run_backtest_book_diagnostic_absent_for_single_asset", test_run_backtest_book_diagnostic_absent_for_single_asset),
    ("test_run_backtest_book_diagnostic_absent_for_strategy_without_a_book", test_run_backtest_book_diagnostic_absent_for_strategy_without_a_book),
    ("test_run_backtest_flat_net_exposure_panel_reports_the_book_it_holds", test_run_backtest_flat_net_exposure_panel_reports_the_book_it_holds),
    ("test_run_backtest_book_pricing_backtests_a_market_neutral_book", test_run_backtest_book_pricing_backtests_a_market_neutral_book),
    ("test_run_backtest_book_pricing_differs_by_the_measured_return_gap", test_run_backtest_book_pricing_differs_by_the_measured_return_gap),
    ("test_run_backtest_net_exposure_pricing_is_the_default_and_is_unchanged", test_run_backtest_net_exposure_pricing_is_the_default_and_is_unchanged),
    ("test_run_backtest_book_pricing_falls_back_when_no_book_is_available", test_run_backtest_book_pricing_falls_back_when_no_book_is_available),
    ("test_run_backtest_book_pricing_on_a_single_asset_is_net_exposure_pricing", test_run_backtest_book_pricing_on_a_single_asset_is_net_exposure_pricing),
    ("test_run_backtest_book_pricing_charges_the_gross_turnover_of_the_book", test_run_backtest_book_pricing_charges_the_gross_turnover_of_the_book),
    ("test_run_backtest_book_pricing_charges_borrow_on_the_short_leg", test_run_backtest_book_pricing_charges_borrow_on_the_short_leg),
    ("test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate", test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate),
    ("test_run_backtest_book_pricing_builds_a_trade_ledger", test_run_backtest_book_pricing_builds_a_trade_ledger),
    ("test_book_trade_ledger_prices_each_leg_at_its_own_close", test_book_trade_ledger_prices_each_leg_at_its_own_close),
    ("test_run_backtest_net_exposure_numbers_are_unchanged_by_the_book_cost_basis", test_run_backtest_net_exposure_numbers_are_unchanged_by_the_book_cost_basis),
]

if __name__ == "__main__":
    import sys
    sys.exit(main())
