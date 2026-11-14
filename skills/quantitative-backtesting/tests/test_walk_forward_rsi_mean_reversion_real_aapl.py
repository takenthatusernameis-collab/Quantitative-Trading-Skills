#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for RSI mean reversion on
the committed single-asset panel (AAPL).

RSI mean reversion is a single-asset strategy (one symbol, long/short), so
the walk-forward is run directly on the AAPL time series with the
``rsi_mean_reversion`` strategy from ``strategy_builder``. This extends
walk-forward coverage to the RSI variant of the mean-reversion family on
committed fixtures, matching the bollinger_bands / macd / ema_cross /
donchian_breakout single-asset walk-forward guards.

Evaluates the strategy across chronological walk-forward windows (train 12 /
test 12 months, stepping 12 months) on committed fixtures only, with a
pre-registered parameter grid and the Deflated Sharpe Ratio multiple-testing
correction applied to the pooled out-of-sample record.

Verdicts are falsification outcomes, never profitability claims: metrics are
pinned and the Deflated Sharpe p-value is above 0.10, so the
multiple-testing-corrected criterion fails and the honest verdict is NOT
SUPPORTED. The test does not tune to force SUPPORTED.

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

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered narrow grid at the advertised RSI mean reversion settings
# (period=14, oversold=30, overbought=70, neutral=50), drawn from the default
# parameters in strategy_builder.py. Fixed before any result is inspected;
# small enough to stay fast in CI.
PARAM_GRID = {
    "period": [14],
    "oversold": [30],
    "overbought": [70],
    "neutral": [50],
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
    return build_strategy("rsi_mean_reversion", json.dumps(params))


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


def test_walk_forward_rsi_mean_reversion_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
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


def test_walk_forward_rsi_mean_reversion_real_aapl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    AAPL fixture must reproduce the pinned out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    The test enforces the honest falsification discipline (do not tune to
    force SUPPORT).
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": -0.5059443652790976,
        "total_oos_return": -0.3509183208815161,
        "deflated_sharpe_ratio": 0.07031989714672066,
        "deflated_sharpe_pvalue": 0.9296801028532793,
        "win_rate_periods": 0.29989969909729186,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        if key == "deflated_sharpe_ratio":
            got = summary["deflated_sharpe"]["deflated_sharpe_ratio"]
        elif key == "deflated_sharpe_pvalue":
            got = summary["deflated_sharpe"]["p_value"]
        else:
            got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: negative Sharpe and return; Deflated Sharpe p-value
    # >= 0.10 fails; verdict NOT SUPPORTED.
    sharpe = summary["oos_sharpe"]
    ret = summary["total_oos_return"]
    dsr_pvalue = summary["deflated_sharpe"]["p_value"]
    passes = {
        "oos_sharpe_gt_zero": bool(sharpe is not None and float(sharpe) > 0),
        "oos_total_return_positive": bool(ret is not None and float(ret) > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            dsr_pvalue is not None and float(dsr_pvalue) < DSR_PVALUE_THRESHOLD
        ),
    }
    assert passes["oos_sharpe_gt_zero"] is False
    assert passes["oos_total_return_positive"] is False
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False


if __name__ == "__main__":
    test_walk_forward_rsi_mean_reversion_real_aapl_runs()
    test_walk_forward_rsi_mean_reversion_real_aapl_metrics_pinned()
    print("OK")
