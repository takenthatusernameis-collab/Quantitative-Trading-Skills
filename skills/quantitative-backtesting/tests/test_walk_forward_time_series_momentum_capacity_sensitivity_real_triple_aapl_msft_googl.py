#!/usr/bin/env python3
"""Market-impact capacity sensitivity for time-series momentum (TSMOM) on the
committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_walk_forward_time_series_momentum_elevated_cost_real_triple_aapl_msft_googl.py:
sweeps the market-impact coefficient across ascending levels at the advertised
3bps (2bp comm + 1bp slip) round-trip costs, with impact disabled first
(capacity unmeasurable / None), and reports how estimated strategy capacity
(notional) behaves. Capacity scales inversely with impact_coefficient, so as
market impact rises estimated capacity must fall -- never increase. The
impact-disabled level must report capacity=None. No profitability or capacity
claim is made; capacity is an execution-side control.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    CAPACITY_SENSITIVITY_LEVELS,
    run_capacity_sensitivity_sweep,
)


def test_capacity_sensitivity_sweep_runs_on_triple_real_window_time_series_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SKILLS_DIR / "assets" / "example_data" / "real_market_data" / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_capacity_sensitivity_sweep()

    assert isinstance(rows, list) and len(rows) == len(CAPACITY_SENSITIVITY_LEVELS)
    # Levels recorded in ascending order; impact disabled first.
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


if __name__ == "__main__":
    test_capacity_sensitivity_sweep_runs_on_triple_real_window_time_series_momentum()
    print("OK")
