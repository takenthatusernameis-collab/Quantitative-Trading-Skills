#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for single-asset z-score mean
reversion on the committed AAPL fixture.

Runs ``build_strategy('zscore_mean_reversion', ...)`` through
``walk_forward_analysis`` on the AAPL time series. Pre-registered grid
(period=20, entry_z=2.0, exit_z=0.5), train/test/step=12/12/12 months,
2bps+1bps costs, with Deflated Sharpe correction.

Honest verdict: NOT SUPPORTED (Sharpe -0.5038, return -44.52%, DSR p=0.9985).
Offline, committed fixtures only.
"""
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

COMMISSION = 0.0002
SLIPPAGE = 0.0001

PARAM_GRID = {"period": [20], "entry_z": [2.0], "exit_z": [0.5]}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

DSR_PVALUE_THRESHOLD = 0.10


def _build_data():
    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("zscore_mean_reversion", json.dumps(params))


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


def test_walk_forward_zscore_mean_reversion_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] == 4
    assert summary["periods_with_position"] == 4
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_walk_forward_zscore_mean_reversion_real_aapl_metrics_pinned():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    summary = result["summary"]
    assert summary["n_periods"] == 4
    assert summary["periods_with_position"] == 4
    assert summary["bias_controls_engaged"] is True

    EXPECTED = {
        "oos_sharpe": -0.24017343713129025,
        "oos_volatility": 0.17474224818609813,
        "total_oos_return": -0.1370542321104533,
        "n_positive_periods": 215.0,
        "win_rate_periods": 0.2156469408224674,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    dsr = summary.get("deflated_sharpe") or {}
    assert dsr.get("n_trials") == 8
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None
    assert abs(dsr_p - 0.9985296036391956) <= 1e-6 * max(abs(0.9985296036391956), 1e-9)
    dsr_ratio = dsr.get("deflated_sharpe_ratio")
    assert dsr_ratio is not None
    assert abs(dsr_ratio - 0.0014703963608043713) <= 1e-6 * max(abs(0.0014703963608043713), 1e-9)

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
    test_walk_forward_zscore_mean_reversion_real_aapl_runs()
    test_walk_forward_zscore_mean_reversion_real_aapl_metrics_pinned()
    print("OK")