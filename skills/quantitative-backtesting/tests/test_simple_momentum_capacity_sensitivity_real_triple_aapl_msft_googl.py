#!/usr/bin/env python3
"""Market-impact capacity sensitivity for simple momentum (SMA crossover) on the
committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_cross_sectional_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py:
sweeps the market-impact coefficient across ascending levels at the advertised
3bps (2bp comm + 1bp slip) round-trip costs, with impact disabled first
(capacity unmeasurable / None), and reports how estimated strategy capacity
(notional) behaves. Capacity scales inversely with impact_coefficient, so as
market impact rises estimated capacity must fall -- never increase. The
impact-disabled level must report capacity=None. No profitability or capacity
claim is made; capacity is an execution-side control.

Simple momentum is implemented as a panel-aware SMA crossover: each asset
generates its own SMA crossover signal (fast/slow), and the portfolio signal is
the equal-weighted mean of per-asset signals. The per-asset positions are
exposed as a target book for --panel-pricing book capacity estimation.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from strategy_builder import StrategyBase, StrategyConfig  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Market-impact coefficients exercised by the capacity sensitivity sweep,
# ascending; the first level disables impact (capacity unmeasurable / None).
CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

# Pre-registered grid matching the advertised simple momentum setting
# (fast=10, slow=30) from examples/simple_momentum_hypothesis.py.
# Fixed before any result is inspected; small enough to stay fast in CI.
PARAM_GRID = {
    "fast_period": [10],
    "slow_period": [30],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12


class PanelSMACrossoverStrategy(StrategyBase):
    """Panel-aware SMA Crossover Strategy.

    Computes SMA crossover independently for each asset in a multi-asset panel.
    The portfolio signal is the equal-weighted mean of per-asset signals.
    Exposes per-asset target weights for book pricing.
    """

    def generate_signals(self, data: pd.DataFrame | dict) -> pd.Series:
        fast_period = self.parameters.get("fast_period", 10)
        slow_period = self.parameters.get("slow_period", 30)

        # Handle multi-asset panel data (dict or MultiIndex columns)
        if isinstance(data, dict):
            return self._generate_multi_asset_signals_dict(data, fast_period, slow_period)
        elif isinstance(data.columns, pd.MultiIndex):
            return self._generate_multi_asset_signals_multiindex(data, fast_period, slow_period)
        else:
            # Single-asset fallback (backward compatible)
            return self._generate_single_asset_signals(data, fast_period, slow_period)

    def _generate_single_asset_signals(
        self, data: pd.DataFrame, fast_period: int, slow_period: int
    ) -> pd.Series:
        fast_sma = data["close"].rolling(fast_period).mean()
        slow_sma = data["close"].rolling(slow_period).mean()

        signals = pd.Series(0, index=data.index, dtype=float)
        signals[fast_sma > slow_sma] = 1
        signals[fast_sma <= slow_sma] = 0

        return signals

    def _generate_multi_asset_signals_dict(
        self, data_dict: dict, fast_period: int, slow_period: int
    ) -> pd.Series:
        if not data_dict:
            return pd.Series(dtype=float)

        # Align all symbols to common date index
        common_index = None
        for df in data_dict.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        if common_index is None or len(common_index) == 0:
            return pd.Series(dtype=float)

        common_index = common_index.sort_values()

        # Compute per-asset signals
        signals_per_asset = pd.DataFrame(
            0.0, index=common_index, columns=list(data_dict.keys()), dtype=float
        )
        for symbol, df in data_dict.items():
            df_aligned = df.reindex(common_index)
            close = df_aligned["close"]
            fast_sma = close.rolling(fast_period).mean()
            slow_sma = close.rolling(slow_period).mean()
            asset_signal = pd.Series(0.0, index=common_index, dtype=float)
            asset_signal[fast_sma > slow_sma] = 1
            asset_signal[fast_sma <= slow_sma] = 0
            signals_per_asset[symbol] = asset_signal

        # Portfolio signal: equal-weighted mean of per-asset signals
        return signals_per_asset.mean(axis=1)

    def _generate_multi_asset_signals_multiindex(
        self, data: pd.DataFrame, fast_period: int, slow_period: int
    ) -> pd.Series:
        if "close" not in data.columns.get_level_values(0):
            raise ValueError("MultiIndex data must have 'close' as first level column")

        close_data = data["close"]  # DataFrame with symbols as columns

        signals_per_asset = pd.DataFrame(
            0.0, index=data.index, columns=close_data.columns, dtype=float
        )
        for symbol in close_data.columns:
            close = close_data[symbol]
            fast_sma = close.rolling(fast_period).mean()
            slow_sma = close.rolling(slow_period).mean()
            asset_signal = pd.Series(0.0, index=data.index, dtype=float)
            asset_signal[fast_sma > slow_sma] = 1
            asset_signal[fast_sma <= slow_sma] = 0
            signals_per_asset[symbol] = asset_signal

        # Portfolio signal: equal-weighted mean of per-asset signals
        return signals_per_asset.mean(axis=1)

    def generate_target_weights(self, data) -> pd.DataFrame | None:
        """Per-asset target book implied by the SMA crossover signals.

        Each asset carries its own position (1 long, 0 flat), so the book's
        net exposure is the equal-weighted mean of the per-asset signals
        (matching the scalar signal from generate_signals).

        Returns None for single-asset data.
        """
        fast_period = self.parameters.get("fast_period", 10)
        slow_period = self.parameters.get("slow_period", 30)

        if isinstance(data, dict):
            if not data:
                return None
            common_index = None
            for df in data.values():
                common_index = (
                    df.index if common_index is None else common_index.intersection(df.index)
                )
            if common_index is None or len(common_index) == 0:
                return None
            common_index = common_index.sort_values()
            weights = pd.DataFrame(
                0.0, index=common_index, columns=list(data.keys()), dtype=float
            )
            for symbol, df in data.items():
                df_aligned = df.reindex(common_index)
                close = df_aligned["close"]
                fast_sma = close.rolling(fast_period).mean()
                slow_sma = close.rolling(slow_period).mean()
                asset_signal = pd.Series(0.0, index=common_index, dtype=float)
                asset_signal[fast_sma > slow_sma] = 1
                asset_signal[fast_sma <= slow_sma] = 0
                weights[symbol] = asset_signal
            return weights

        if isinstance(data.columns, pd.MultiIndex):
            if "close" not in data.columns.get_level_values(0):
                return None
            close_data = data["close"]
            weights = pd.DataFrame(
                0.0, index=data.index, columns=close_data.columns, dtype=float
            )
            for symbol in close_data.columns:
                close = close_data[symbol]
                fast_sma = close.rolling(fast_period).mean()
                slow_sma = close.rolling(slow_period).mean()
                asset_signal = pd.Series(0.0, index=data.index, dtype=float)
                asset_signal[fast_sma > slow_sma] = 1
                asset_signal[fast_sma <= slow_sma] = 0
                weights[symbol] = asset_signal
            return weights

        return None


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    config = StrategyConfig(
        name="panel_sma_crossover",
        parameters=params,
        description="Panel SMA Crossover strategy"
    )
    return PanelSMACrossoverStrategy(config)


def _run_walk_forward(impact_coefficient):
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        impact_coefficient=impact_coefficient,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def test_simple_momentum_capacity_sensitivity_sweep_real_triple_panel():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists(), f"missing fixture {name}"

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            rows = [
                _summarize(level, _run_walk_forward(level))
                for level in CAPACITY_SENSITIVITY_LEVELS
            ]
            finite = [r for r in rows if r["capacity"] is not None]
            first = finite[0]
            last = finite[-1]
            print(
                "  Capacity falls with market impact: "
                f"${first['capacity']:,.0f} at impact_coefficient={first['impact_coefficient']} -> "
                f"${last['capacity']:,.0f} at impact_coefficient={last['impact_coefficient']}."
            )

    assert [r["impact_coefficient"] for r in rows] == list(
        CAPACITY_SENSITIVITY_LEVELS
    ), "capacity sensitivity levels are not recorded in ascending order"
    assert rows[0]["impact_coefficient"] == 0.0, (
        "first capacity sensitivity level must be impact disabled"
    )
    assert rows[0]["capacity"] is None, (
        "impact-disabled setting must report capacity=None, got "
        f"{rows[0]['capacity']}"
    )
    assert rows[0]["capacity_book"] is None, (
        "impact-disabled setting must report capacity_book=None, got "
        f"{rows[0]['capacity_book']}"
    )

    finite = [r for r in rows if r["capacity"] is not None]
    assert len(finite) >= 2, (
        "capacity sensitivity sweep must produce at least two finite readings"
    )
    for r in finite:
        assert float(r["capacity"]) > 0, (
            "capacity estimate must be positive: " f"{r['capacity']}"
        )
    # Capacity must fall monotonically as market impact rises.
    for prev, curr in zip(finite, finite[1:]):
        assert curr["capacity"] < prev["capacity"], (
            "capacity does not fall as market impact rises: "
            f"impact {prev['impact_coefficient']} -> {prev['capacity']:,.0f}, "
            f"impact {curr['impact_coefficient']} -> {curr['capacity']:,.0f}"
        )

    out = buffer.getvalue()
    assert "CAPACITY SENSITIVITY SWEEP" in out
    assert "Capacity falls with market impact" in out
    flat_warnings = [
        str(w.message) for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


def _summarize(impact_coefficient, result):
    summary = result["summary"]
    capacity = summary.get("capacity")
    if isinstance(capacity, dict):
        capacity = capacity.get("cost_adjusted_capacity")
    capacity_book = summary.get("capacity_book")
    print(
        "CAPACITY SENSITIVITY SWEEP: "
        f"impact_coefficient={impact_coefficient:.4f} "
        f"capacity={('None (impact disabled)' if capacity is None else f'${capacity:,.0f}')} "
        f"capacity_book={('N/A' if capacity_book is None else f'${capacity_book:,.0f}')}"
    )
    return {
        "impact_coefficient": impact_coefficient,
        "capacity": capacity,
        "capacity_book": capacity_book,
    }


if __name__ == "__main__":
    test_simple_momentum_capacity_sensitivity_sweep_real_triple_panel()
    print("OK")