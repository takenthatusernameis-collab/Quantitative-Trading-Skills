#!/usr/bin/env python3
"""Unit tests for the execution warmup metadata.

The framework warms up differently in its two entry points, on purpose:

  * ``walk_forward.py`` (walk-forward, CPCV, out-of-sample, Monte Carlo)
    drops the first ``latency + 2`` bars of every window: the lagged
    position is undefined for ``1 + latency`` bars and the turnover on the
    bar after that is undefined too.
  * ``run_backtest.py`` opens the position on the first executable bar and
    drops only the single bar whose turnover is undefined.

The two conventions therefore differ by exactly one bar. The difference is
intentional and is pinned by the cross-path parity tests in
``test_run_backtest.py``.

These tests check two things:

  1. every result artifact *records* the convention it applied
     (``warmup_convention`` and ``execution_warmup_bars``), so a consumer
     never has to infer it from the shape of the return series; and
  2. the recorded number of bars is the number of bars that are actually
     missing from the reported return series -- so the metadata cannot
     drift away from the behaviour it describes.

Run with: python3 skills/quantitative-backtesting/tests/test_execution_warmup.py
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from run_backtest import run_backtest  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import (  # noqa: E402
    execution_warmup_metadata,
    EXECUTION_WARMUP_BARS,
    RUN_BACKTEST_WARMUP_BARS,
    WARMUP_CONVENTION_RUN_BACKTEST,
    WARMUP_CONVENTION_WALK_FORWARD,
)
from walk_forward import (  # noqa: E402
    cpcv_analysis,
    out_of_sample_validation,
    walk_forward_analysis,
)


# The observed behaviour of the two conventions, written as literals on
# purpose: the tests must pin what the framework *does*, not re-derive it
# from the framework's own constants. A change to the constant alone is
# therefore caught here instead of being silently mirrored by the
# assertions.
WALK_FORWARD_WARMUP_BARS = 2
RUN_BACKTEST_DROPPED_BARS = 1


class _Args:
    """Minimal stand-in for the CLI namespace used by run_backtest()."""

    def __init__(self, **overrides):
        self.commission = 0.0002
        self.slippage = 0.0001
        self.initial_capital = 100000
        self.strategy = "cross_sectional_momentum"
        self.symbol = "TEST"
        self.n_trials = None
        self.impact_coefficient = 0.0
        self.adv_window = 20
        self.borrow_cost = 0.0
        self.funding_cost = 0.0
        self.validate_point_in_time = False
        self.point_in_time_strict = False
        self.multi_symbol = False
        self.benchmark = None
        self.risk_free_rate = None
        self.fill_rate = 1.0
        self.latency = 0
        self.panel_pricing = "net-exposure"
        self.impact_aggregation = "panel"
        for key, value in overrides.items():
            setattr(self, key, value)


def _make_panel(n=600, n_assets=4, seed=42):
    """A MultiIndex OHLCV panel with a deterministic, reproducible path."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    columns = pd.MultiIndex.from_product(
        [["open", "high", "low", "close", "volume"], symbols]
    )
    frame = pd.DataFrame(0.0, index=dates, columns=columns)
    rng = np.random.default_rng(seed)
    for i, symbol in enumerate(symbols):
        rets = rng.normal(0.0005 * (i + 1), 0.01, n)
        prices = 100 * np.exp(np.cumsum(rets))
        frame[("open", symbol)] = prices * rng.uniform(0.995, 1.005, n)
        frame[("high", symbol)] = prices * rng.uniform(1.005, 1.02, n)
        frame[("low", symbol)] = prices * rng.uniform(0.98, 0.995, n)
        frame[("close", symbol)] = prices
        frame[("volume", symbol)] = rng.integers(1_000_000, 10_000_000, n)
    return frame


def _strategy_factory(strategy_type="cross_sectional_momentum"):
    def factory(params):
        return build_strategy(strategy_type, str(params).replace("'", '"'))

    return factory


def test_execution_warmup_metadata_reports_the_documented_counts():
    """The helper returns the counts the two conventions actually produce."""
    # The shared constants agree with the observed behaviour.
    assert EXECUTION_WARMUP_BARS == WALK_FORWARD_WARMUP_BARS
    assert RUN_BACKTEST_WARMUP_BARS == RUN_BACKTEST_DROPPED_BARS

    for latency in (0, 1, 2, 5):
        walk_forward_meta = execution_warmup_metadata(
            WARMUP_CONVENTION_WALK_FORWARD, latency
        )
        assert walk_forward_meta == {
            "warmup_convention": WARMUP_CONVENTION_WALK_FORWARD,
            "execution_warmup_bars": latency + WALK_FORWARD_WARMUP_BARS,
        }

        run_backtest_meta = execution_warmup_metadata(
            WARMUP_CONVENTION_RUN_BACKTEST, latency
        )
        assert run_backtest_meta == {
            "warmup_convention": WARMUP_CONVENTION_RUN_BACKTEST,
            "execution_warmup_bars": RUN_BACKTEST_DROPPED_BARS,
        }


def test_execution_warmup_metadata_rejects_an_unknown_convention():
    """An unknown convention is a programming error, not a silent default."""
    try:
        execution_warmup_metadata("something_else", 0)
    except ValueError as exc:
        assert "something_else" in str(exc)
    else:
        raise AssertionError("an unknown warmup convention must raise ValueError")


def test_run_backtest_records_the_warmup_convention():
    """run_backtest's results carry the convention it applied."""
    data = _make_panel()
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )

    for latency in (0, 1, 2):
        results = run_backtest(data, strategy, _Args(latency=latency))
        config = results["config"]
        assert config["warmup_convention"] == WARMUP_CONVENTION_RUN_BACKTEST
        assert config["execution_warmup_bars"] == RUN_BACKTEST_DROPPED_BARS
        # The recorded number is the number of leading bars that are
        # actually missing from the reported series.
        assert len(data) - len(results["returns"]) == RUN_BACKTEST_DROPPED_BARS


def test_walk_forward_summary_records_the_warmup_convention():
    """The walk-forward summary carries the convention and the bar count."""
    data = _make_panel()
    factory = _strategy_factory()

    for latency in (0, 1, 2):
        results = walk_forward_analysis(
            data=data,
            strategy_factory=factory,
            param_grid={"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]},
            train_months=12,
            test_months=3,
            step_months=3,
            latency=latency,
            validate_pit=False,
        )
        summary = results["summary"]
        assert summary["warmup_convention"] == WARMUP_CONVENTION_WALK_FORWARD
        assert summary["execution_warmup_bars"] == latency + WALK_FORWARD_WARMUP_BARS

        # Every evaluated window is missing exactly the recorded number of
        # leading bars (the cross-sectional signal has no warmup of its own).
        for period in results["periods"]:
            test_returns = period.get("test_returns")
            if test_returns is None or len(test_returns) == 0:
                continue
            window = period["test_data"]
            assert len(window) - len(test_returns) == latency + WALK_FORWARD_WARMUP_BARS


def test_cpcv_summary_records_the_warmup_convention():
    """The CPCV summary carries the convention and the bar count."""
    data = _make_panel()
    factory = _strategy_factory()

    for latency in (0, 1):
        results = cpcv_analysis(
            data=data,
            strategy_factory=factory,
            param_grid={"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]},
            n_splits=4,
            test_size=0.2,
            latency=latency,
            validate_pit=False,
        )
        summary = results["summary"]
        assert summary["warmup_convention"] == WARMUP_CONVENTION_WALK_FORWARD
        assert summary["execution_warmup_bars"] == latency + WALK_FORWARD_WARMUP_BARS

        # The recorded number is the number of leading bars that are
        # actually missing from every evaluated fold.
        for fold in results["folds"]:
            test_returns = fold.get("test_returns")
            if test_returns is None or len(test_returns) == 0:
                continue
            window = fold["test_data"]
            assert len(window) - len(test_returns) == latency + WALK_FORWARD_WARMUP_BARS


def test_out_of_sample_summary_records_the_warmup_convention():
    """The out-of-sample summary carries the convention and the bar count."""
    data = _make_panel()
    factory = _strategy_factory()

    results = out_of_sample_validation(
        data=data,
        strategy_factory=factory,
        param_grid={"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]},
        latency=1,
        validate_pit=False,
    )
    summary = results["summary"]
    assert summary["warmup_convention"] == WARMUP_CONVENTION_WALK_FORWARD
    assert summary["execution_warmup_bars"] == 1 + WALK_FORWARD_WARMUP_BARS


def test_the_two_conventions_differ_by_exactly_one_bar():
    """The recorded conventions explain the one-bar cross-path difference.

    run_backtest opens the position on the first executable bar and keeps
    it; walk_forward drops the bar whose turnover is undefined. The two
    reported series therefore differ by exactly one bar, and the recorded
    metadata accounts for that difference.
    """
    data = _make_panel()
    strategy = build_strategy(
        "cross_sectional_momentum",
        '{"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}',
    )
    results = run_backtest(data, strategy, _Args(latency=0))

    walk_forward_meta = execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, 0)
    run_backtest_meta = execution_warmup_metadata(WARMUP_CONVENTION_RUN_BACKTEST, 0)
    difference = (
        walk_forward_meta["execution_warmup_bars"]
        - run_backtest_meta["execution_warmup_bars"]
    )
    assert difference == 1

    # The walk-forward path really does report one bar fewer.
    from walk_forward import _calculate_strategy_returns

    signals = strategy.generate_signals(data)
    walk_forward_returns = _calculate_strategy_returns(
        data,
        signals,
        commission=0.0002,
        slippage=0.0001,
        impact_coefficient=0.0,
        adv_window=20,
        borrow_cost=0.0,
        funding_cost=0.0,
        latency=0,
        fill_rate=1.0,
        initial_capital=100000,
    )
    assert len(results["returns"]) - len(walk_forward_returns) == difference


def test_indicator_warmup_is_not_counted_as_execution_warmup():
    """The recorded count is the *execution* warmup, not the signal's own.

    A moving average needs `lookback - 1` bars before it produces a value,
    so a window evaluated with an SMA strategy drops more bars than the
    execution warmup alone. The metadata must describe the execution
    convention, not the strategy's indicator warmup.
    """
    data = _make_panel()
    factory = _strategy_factory("sma_crossover")

    results = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid={"fast_period": [5], "slow_period": [20]},
        train_months=12,
        test_months=3,
        step_months=3,
        latency=0,
        validate_pit=False,
    )
    summary = results["summary"]
    assert summary["warmup_convention"] == WARMUP_CONVENTION_WALK_FORWARD
    assert summary["execution_warmup_bars"] == WALK_FORWARD_WARMUP_BARS

    for period in results["periods"]:
        test_returns = period.get("test_returns")
        if test_returns is None or len(test_returns) == 0:
            continue
        window = period["test_data"]
        dropped = len(window) - len(test_returns)
        # The execution warmup is always included ...
        assert dropped >= WALK_FORWARD_WARMUP_BARS
        # ... and the indicator warmup adds to it.
        assert dropped > WALK_FORWARD_WARMUP_BARS


TEST_REGISTRY = [
    ("execution_warmup_metadata_reports_the_documented_counts",
     test_execution_warmup_metadata_reports_the_documented_counts),
    ("execution_warmup_metadata_rejects_an_unknown_convention",
     test_execution_warmup_metadata_rejects_an_unknown_convention),
    ("run_backtest_records_the_warmup_convention",
     test_run_backtest_records_the_warmup_convention),
    ("walk_forward_summary_records_the_warmup_convention",
     test_walk_forward_summary_records_the_warmup_convention),
    ("cpcv_summary_records_the_warmup_convention",
     test_cpcv_summary_records_the_warmup_convention),
    ("out_of_sample_summary_records_the_warmup_convention",
     test_out_of_sample_summary_records_the_warmup_convention),
    ("the_two_conventions_differ_by_exactly_one_bar",
     test_the_two_conventions_differ_by_exactly_one_bar),
    ("indicator_warmup_is_not_counted_as_execution_warmup",
     test_indicator_warmup_is_not_counted_as_execution_warmup),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
