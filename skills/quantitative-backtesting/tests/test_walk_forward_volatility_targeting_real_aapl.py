#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for volatility targeting on
the committed single-asset panel (AAPL).

Volatility targeting is a position-sizing overlay with no signal generator of
its own, so in standalone mode it falls back to a plain time-series momentum
base (close vs its rolling mean) that yields a tradable signal. The
walk-forward is run directly on the AAPL time series with the
``volatility_targeting`` strategy. This fills the walk-forward gap for the
volatility-targeting path on committed fixtures (CPCV coverage exists in
``test_cpcv_volatility_targeting_real_aapl.py``).

Evaluates the strategy across chronological walk-forward windows (train 12 /
test 12 months, stepping 12 months) on committed fixtures only, with a
pre-registered parameter grid (matching the CPCV guard: target_vol=0.15,
lookback=63) and the Deflated Sharpe Ratio multiple-testing correction applied
to the pooled out-of-sample record.

Verdicts are falsification outcomes, never profitability claims: the raw
out-of-sample Sharpe is negative (-0.3862) and the total return is negative
(-59.21%), and the Deflated Sharpe p-value (0.9933) is far above 0.10, so the
multiple-testing-corrected criterion fails and the honest verdict is NOT
SUPPORTED. The test does not tune to force SUPPORT.

With lookback=63 the standalone volatility-targeting and kelly-criterion
overlays produce identical walk-forward metrics on this fixture (both fall back
to the same time-series momentum base); the Kelly guard pins the same values
independently.

Offline, committed fixtures only; no live network.
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

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered narrow grid (advertised volatility-targeting defaults).
# Fixed before any result is inspected; matches the CPCV guard.
PARAM_GRID = {
    "target_vol": [0.15],
    "lookback": [63],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Falsification thresholds, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10


def _build_data():
    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("volatility_targeting", json.dumps(params))


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


def test_walk_forward_volatility_targeting_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] == 8
    assert summary["periods_with_position"] == 8
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_walk_forward_volatility_targeting_real_aapl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed AAPL
    fixture must reproduce the pinned out-of-sample metrics (net of costs) so a
    silent change to the backtest numbers is caught. Relative tolerance only,
    never exact equality.

    Honest outcome: the raw out-of-sample Sharpe is negative (-0.3862) and the
    total return is negative (-59.21%), and the Deflated Sharpe p-value (0.9933)
    is far above 0.10, so every criterion fails and the verdict is NOT
    SUPPORTED. The test does not tune to force SUPPORT.

    With lookback=63 the standalone volatility-targeting and kelly-criterion
    overlays produce identical walk-forward metrics on this fixture (same
    time-series momentum fallback).
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    summary = result["summary"]
    assert summary["n_periods"] == 8
    assert summary["periods_with_position"] == 8
    assert summary["bias_controls_engaged"] is True

    EXPECTED = {
        "oos_sharpe": -0.38617607871821996,
        "oos_volatility": 0.25847052397276044,
        "total_oos_return": -0.5921302782722866,
        "n_positive_periods": 955,
        "win_rate_periods": 0.4782173259889835,
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
    assert abs(dsr_p - 0.9932632277741321) <= 1e-6 * max(abs(0.9932632277741321), 1e-9)
    dsr_ratio = dsr.get("deflated_sharpe_ratio")
    assert dsr_ratio is not None
    assert abs(dsr_ratio - 0.006736772225867882) <= 1e-6 * max(abs(0.006736772225867882), 1e-9)

    # Honest verdict: Sharpe < 0 and return < 0 fail, and Deflated Sharpe
    # p-value >= 0.10 fails, so the hypothesis is NOT SUPPORTED.
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
    test_walk_forward_volatility_targeting_real_aapl_runs()
    test_walk_forward_volatility_targeting_real_aapl_metrics_pinned()
    print("OK")
