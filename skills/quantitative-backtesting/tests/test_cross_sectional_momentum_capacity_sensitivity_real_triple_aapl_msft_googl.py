#!/usr/bin/env python3
"""Market-impact capacity sensitivity for cross-sectional momentum on the
committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py:
sweeps the market-impact coefficient across ascending levels at the advertised
3bps (2bp comm + 1bp slip) round-trip costs, with impact disabled first
(capacity unmeasurable / None), and reports how estimated strategy capacity
(notional) behaves. Capacity scales inversely with impact_coefficient
(capacity = max_impact * ADV_notional / impact_coefficient for the linear
model), so as market impact rises estimated capacity must fall -- never
increase. The impact-disabled level must report capacity=None. No profitability
or capacity claim is made; capacity is an execution-side control.

Cross-sectional momentum is priced with --panel-pricing book (the true
per-asset book return sum_i w_i r_i), so this sweep also surfaces the
book-based capacity (summary["capacity_book"]) next to the basket-based one.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
import warnings
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import pandas as pd

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Market-impact coefficients exercised by the capacity sensitivity sweep,
# ascending; the first level disables impact (capacity unmeasurable / None).
CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

# Pre-registered narrow grid around the cross-sectional momentum settings
# (lookback=20, top_quantile=0.4, bottom_quantile=0.2). Asymmetric quantiles
# (0.4/0.2) so the long and short books differ in size and the portfolio
# signal is non-zero by construction. Fixed before any result is inspected;
# small enough to stay fast in CI.
PARAM_GRID = {
    "lookback": [10, 20],
    "top_quantile": [0.4],
    "bottom_quantile": [0.2],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("cross_sectional_momentum", __import__("json").dumps(params))


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


def test_cross_sectional_momentum_capacity_sensitivity_sweep_real_triple_panel():
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
    test_cross_sectional_momentum_capacity_sensitivity_sweep_real_triple_panel()
    print("OK")
