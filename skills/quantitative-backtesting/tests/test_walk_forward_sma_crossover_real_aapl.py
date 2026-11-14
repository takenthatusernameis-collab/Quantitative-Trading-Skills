#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for SMA crossover on the
committed single-asset panel (AAPL).

SMA crossover is a single-asset strategy (one symbol, long/flat), so the
walk-forward is run directly on the AAPL time series with the
``sma_crossover`` strategy. This fills the walk-forward gap for the
trend-following crossover family not yet covered under walk-forward
re-optimization on committed fixtures.

Evaluates the strategy across chronological walk-forward windows (train 12 /
test 12 months, stepping 12 months) on committed fixtures only, with a
pre-registered parameter grid and the Deflated Sharpe Ratio multiple-testing
correction applied to the pooled out-of-sample record.

Verdicts are falsification outcomes, never profitability claims: the raw
out-of-sample Sharpe is positive (0.2923) and the total return is positive
(0.5458), but the Deflated Sharpe p-value (0.6019) is well above 0.10, so
the multiple-testing-corrected criterion fails and the honest verdict is NOT
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

# Pre-registered narrow grid around the advertised SMA crossover
# settings (fast_period=20, slow_period=50), drawn from the default
# parameters in strategy_builder.py. Fixed before any result is inspected;
# small enough to stay fast in CI.
PARAM_GRID = {
    "fast_period": [20],
    "slow_period": [50],
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
    return build_strategy("sma_crossover", json.dumps(params))


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


def test_walk_forward_sma_crossover_real_aapl_runs():
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


def test_walk_forward_sma_crossover_real_aapl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    AAPL fixture must reproduce the pinned out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Honest outcome: the raw out-of-sample Sharpe is positive (0.2923), the
    total return is positive (0.5458), but the Deflated Sharpe p-value
    (0.6019) is well above 0.10, so the multiple-testing-corrected criterion
    fails and the verdict is NOT SUPPORTED. The test does not tune to force
    SUPPORT.
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": 0.4563654612098278,
        "total_oos_return": 0.3784080803807892,
        "deflated_sharpe_pvalue": 0.9240260446437558,
        "deflated_sharpe_ratio": 0.07597395535624413,
        "win_rate_periods": 0.2637913741223671,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        if key == "deflated_sharpe_pvalue":
            got = summary["deflated_sharpe"]["p_value"]
        elif key == "deflated_sharpe_ratio":
            got = summary["deflated_sharpe"]["deflated_sharpe_ratio"]
        else:
            got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: Sharpe > 0 passes, return > 0 passes, but
    # Deflated Sharpe p-value >= 0.10 fails. The hypothesis is NOT SUPPORTED.
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
    assert passes["oos_sharpe_gt_zero"] is True
    assert passes["oos_total_return_positive"] is True
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False


if __name__ == "__main__":
    test_walk_forward_sma_crossover_real_aapl_runs()
    test_walk_forward_sma_crossover_real_aapl_metrics_pinned()
    print("OK")
