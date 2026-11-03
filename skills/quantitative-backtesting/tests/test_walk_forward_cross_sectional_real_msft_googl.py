#!/usr/bin/env python3
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered asymmetric quantiles (0.4/0.2) so the long and short books
# differ in size and the strategy takes a genuine directional position.
# Symmetric quantiles (e.g. 0.2/0.2) emit a "flat (zero) portfolio signal"
# warning and make the falsification structurally trivial.
PARAM_GRID = {"lookback": [60], "top_quantile": [0.4], "bottom_quantile": [0.2]}


def _build_pair_data():
    msft = pd.read_csv(SRC / "MSFT.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    msft["date"] = pd.to_datetime(msft["date"])
    googl["date"] = pd.to_datetime(googl["date"])
    msft = msft.set_index("date")
    googl = googl.set_index("date")
    return {"MSFT": msft, "GOOGL": googl}


def _factory(params):
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def _run_walk_forward():
    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            result = walk_forward_analysis(
                data=_build_pair_data(),
                strategy_factory=_factory,
                param_grid=PARAM_GRID,
                train_months=12,
                test_months=3,
                step_months=3,
                commission=COMMISSION,
                slippage=SLIPPAGE,
                panel_pricing="book",
            )
    return result, buffer.getvalue(), caught


def test_walk_forward_cross_sectional_pairs_real_msft_googl_structure():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    result, out, caught = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result
    summary = result["summary"]
    assert summary["n_periods"] == 35
    assert summary["periods_with_position"] == 32
    assert summary["bias_controls_engaged"] is True
    assert summary["panel_pricing"] == "book"
    flat_warnings = [
        str(w.message) for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


def test_walk_forward_cross_sectional_pairs_real_msft_googl_metrics_pinned():
    """Regression guard: the pair-wise walk-forward run on the committed
    MSFT/GOOGL panel must reproduce the pinned out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Honest outcome: the out-of-sample Sharpe is negative (-2.6656) and total
    return is negative (-10.15%), so both criteria fail and the verdict is NOT
    SUPPORTED. The test does not tune to force SUPPORT.
    """
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    result, out, caught = _run_walk_forward()
    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": -2.6656196270814996,
        "total_oos_return": -0.10150779729057524,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: Sharpe < 0 and return < 0 fail, so NOT SUPPORTED.
    sharpe = summary["oos_sharpe"]
    ret = summary["total_oos_return"]
    assert sharpe is not None and float(sharpe) <= 0
    assert ret is not None and float(ret) <= 0


if __name__ == "__main__":
    test_walk_forward_cross_sectional_pairs_real_msft_googl_structure()
    test_walk_forward_cross_sectional_pairs_real_msft_googl_metrics_pinned()
    print("OK")