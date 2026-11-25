#!/usr/bin/env python3
"""Market-impact capacity sensitivity for EMA crossover on the committed
three-asset panel (AAPL / MSFT / GOOGL). Mirrors the simple momentum capacity
sensitivity test, sweeping the market-impact coefficient across ascending
levels at 3bps round-trip costs.
"""
import contextlib
import io
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

COMMISSION = 0.0002
SLIPPAGE = 0.0001

CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

PARAM_GRID = {
    "fast_period": [12],
    "slow_period": [26],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12


class PanelEMACrossoverStrategy(StrategyBase):
    def generate_signals(self, data):
        fast_period = self.parameters.get("fast_period", 12)
        slow_period = self.parameters.get("slow_period", 26)

        if isinstance(data, dict):
            return self._generate_multi_asset_signals_dict(data, fast_period, slow_period)
        elif isinstance(data.columns, pd.MultiIndex):
            return self._generate_multi_asset_signals_multiindex(data, fast_period, slow_period)
        else:
            return self._generate_single_asset_signals(data, fast_period, slow_period)

    def _generate_single_asset_signals(self, data, fast_period, slow_period):
        fast_ema = data["close"].ewm(span=fast_period, adjust=False).mean()
        slow_ema = data["close"].ewm(span=slow_period, adjust=False).mean()
        signals = pd.Series(0, index=data.index, dtype=float)
        signals[fast_ema > slow_ema] = 1
        signals[fast_ema <= slow_ema] = 0
        return signals

    def _generate_multi_asset_signals_dict(self, data_dict, fast_period, slow_period):
        if not data_dict:
            return pd.Series(dtype=float)
        common_index = None
        for df in data_dict.values():
            common_index = df.index if common_index is None else common_index.intersection(df.index)
        if common_index is None or len(common_index) == 0:
            return pd.Series(dtype=float)
        common_index = common_index.sort_values()
        signals_per_asset = pd.DataFrame(0.0, index=common_index, columns=list(data_dict.keys()), dtype=float)
        for symbol, df in data_dict.items():
            df_aligned = df.reindex(common_index)
            close = df_aligned["close"]
            fast_ema = close.ewm(span=fast_period, adjust=False).mean()
            slow_ema = close.ewm(span=slow_period, adjust=False).mean()
            asset_signal = pd.Series(0.0, index=common_index, dtype=float)
            asset_signal[fast_ema > slow_ema] = 1
            asset_signal[fast_ema <= slow_ema] = 0
            signals_per_asset[symbol] = asset_signal
        return signals_per_asset.mean(axis=1)

    def _generate_multi_asset_signals_multiindex(self, data, fast_period, slow_period):
        if "close" not in data.columns.get_level_values(0):
            raise ValueError("MultiIndex data must have 'close' as first level column")
        close_data = data["close"]
        signals_per_asset = pd.DataFrame(0.0, index=data.index, columns=close_data.columns, dtype=float)
        for symbol in close_data.columns:
            close = close_data[symbol]
            fast_ema = close.ewm(span=fast_period, adjust=False).mean()
            slow_ema = close.ewm(span=slow_period, adjust=False).mean()
            asset_signal = pd.Series(0.0, index=data.index, dtype=float)
            asset_signal[fast_ema > slow_ema] = 1
            asset_signal[fast_ema <= slow_ema] = 0
            signals_per_asset[symbol] = asset_signal
        return signals_per_asset.mean(axis=1)

    def generate_target_weights(self, data):
        fast_period = self.parameters.get("fast_period", 12)
        slow_period = self.parameters.get("slow_period", 26)
        if isinstance(data, dict):
            if not data:
                return None
            common_index = None
            for df in data.values():
                common_index = df.index if common_index is None else common_index.intersection(df.index)
            if common_index is None or len(common_index) == 0:
                return None
            common_index = common_index.sort_values()
            weights = pd.DataFrame(0.0, index=common_index, columns=list(data.keys()), dtype=float)
            for symbol, df in data.items():
                df_aligned = df.reindex(common_index)
                close = df_aligned["close"]
                fast_ema = close.ewm(span=fast_period, adjust=False).mean()
                slow_ema = close.ewm(span=slow_period, adjust=False).mean()
                asset_signal = pd.Series(0.0, index=common_index, dtype=float)
                asset_signal[fast_ema > slow_ema] = 1
                asset_signal[fast_ema <= slow_ema] = 0
                weights[symbol] = asset_signal
            return weights
        if isinstance(data.columns, pd.MultiIndex):
            if "close" not in data.columns.get_level_values(0):
                return None
            close_data = data["close"]
            weights = pd.DataFrame(0.0, index=data.index, columns=close_data.columns, dtype=float)
            for symbol in close_data.columns:
                close = close_data[symbol]
                fast_ema = close.ewm(span=fast_period, adjust=False).mean()
                slow_ema = close.ewm(span=slow_period, adjust=False).mean()
                asset_signal = pd.Series(0.0, index=data.index, dtype=float)
                asset_signal[fast_ema > slow_ema] = 1
                asset_signal[fast_ema <= slow_ema] = 0
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
        name="panel_ema_crossover",
        parameters=params,
        description="Panel EMA Crossover strategy",
    )
    return PanelEMACrossoverStrategy(config)


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


def test_ema_crossover_capacity_sensitivity_sweep_real_triple_panel():
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

    assert [r["impact_coefficient"] for r in rows] == list(CAPACITY_SENSITIVITY_LEVELS)
    assert rows[0]["impact_coefficient"] == 0.0
    assert rows[0]["capacity"] is None
    assert rows[0]["capacity_book"] is None

    finite = [r for r in rows if r["capacity"] is not None]
    assert len(finite) >= 2
    for r in finite:
        assert float(r["capacity"]) > 0
    for prev, curr in zip(finite, finite[1:]):
        assert curr["capacity"] < prev["capacity"], (
            "capacity does not fall as market impact rises: "
            f"impact {prev['impact_coefficient']} -> {prev['capacity']:,.0f}, "
            f"impact {curr['impact_coefficient']} -> {curr['capacity']:,.0f}"
        )

    out = buffer.getvalue()
    assert "CAPACITY SENSITIVITY SWEEP" in out
    assert "Capacity falls with market impact" in out
    flat_warnings = [str(w.message) for w in caught if "flat (zero) portfolio signal" in str(w.message)]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


if __name__ == "__main__":
    test_ema_crossover_capacity_sensitivity_sweep_real_triple_panel()
    print("OK")
