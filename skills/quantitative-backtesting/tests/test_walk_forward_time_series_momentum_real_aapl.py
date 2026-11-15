#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for standalone time-series
momentum (TSMOM) on the committed single-asset panel (AAPL).

Evaluates the registered ``time_series_momentum`` strategy across chronological
walk-forward windows (train 24 / test 12 / step 12 months) with a pre-registered
lookback grid (126, 189, 252 trading days, N=3 trials) and the Deflated Sharpe
Ratio multiple-testing correction applied to the pooled out-of-sample record.

The 252-day lookback requires windows long enough for the signal to be defined;
24m-train / 12m-test windows satisfy this (3 periods with positions), whereas a
12m-test window leaves the 252-day signal flat for the entire window.

PRE-REGISTERED FALSIFICATION CRITERIA (pinned before inspection):
1. oos_sharpe > 0 (net of costs)
2. oos_total_return > 0 (net of costs)
3. deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)

Honest outcome: pooled OOS Sharpe is negative (-0.3885), total return is
negative (-5.98%), and Deflated Sharpe p-value is 0.9746 (5 trials) -- all
three criteria fail, verdict NOT SUPPORTED. The test does not tune to force
SUPPORT.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered grid (fixed before any result is inspected).
PARAM_GRID = {"lookback": [126, 189, 252]}

TRAIN_MONTHS = 24
TEST_MONTHS = 12
STEP_MONTHS = 12

DSR_PVALUE_THRESHOLD = 0.10


def _build_data():
    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("time_series_momentum", json.dumps(params))


def _run_walk_forward():
    return walk_forward_analysis(
        data=_build_data(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        apply_deflation=True,
        validate_pit=True,
    )


def test_walk_forward_time_series_momentum_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] == 3
    assert summary["periods_with_position"] == 3
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_walk_forward_time_series_momentum_real_aapl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed AAPL
    fixture must reproduce the pinned out-of-sample metrics (net of costs).
    Relative tolerance only, never exact equality.

    Honest outcome: Sharpe < 0, total return < 0, Deflated Sharpe p-value >= 0.10
    -> all three criteria fail, verdict NOT SUPPORTED.
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]
    assert summary["n_periods"] == 3
    assert summary["periods_with_position"] == 3
    assert summary["bias_controls_engaged"] is True

    EXPECTED = {
        "oos_sharpe": -0.38851059506816554,
        "oos_volatility": 0.09366510608397208,
        "total_oos_return": -0.05984304746520375,
        "n_positive_periods": 82.0,
        "win_rate_periods": 0.10977242302543508,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    dsr = summary.get("deflated_sharpe") or {}
    assert dsr.get("n_trials") == 5
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None
    assert abs(dsr_p - 0.9745512685295135) <= 1e-6 * max(abs(0.9745512685295135), 1e-9)
    dsr_ratio = dsr.get("deflated_sharpe_ratio")
    assert dsr_ratio is not None
    assert abs(dsr_ratio - 0.025448731470486596) <= 1e-6 * max(abs(0.025448731470486596), 1e-9)

    passes = {
        "oos_sharpe_gt_zero": bool(summary["oos_sharpe"] > 0),
        "oos_total_return_positive": bool(summary["total_oos_return"] > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        ),
    }
    assert passes["oos_sharpe_gt_zero"] is False
    assert passes["oos_total_return_positive"] is False
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_walk_forward_time_series_momentum_real_aapl_runs()
    test_walk_forward_time_series_momentum_real_aapl_metrics_pinned()
    print("OK")
