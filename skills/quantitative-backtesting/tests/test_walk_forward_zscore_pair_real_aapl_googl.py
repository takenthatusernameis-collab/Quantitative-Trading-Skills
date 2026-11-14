#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for multi-pair z-score mean
reversion on the committed two-asset panel (AAPL / GOOGL).

Uses ``multi_pair_zscore_mean_reversion`` on a two-asset panel (trades the
single pair and aggregates into a book). Evaluates across chronological
walk-forward windows (train 12 / test 12 months, stepping 12 months) on
committed fixtures only, with pre-registered parameters and the Deflated
Sharpe Ratio multiple-testing correction applied to the pooled
out-of-sample record.

This replaces the previous structural-only guard (which asserted only that
metrics were *reported*). The pinned-metrics regression below reproduces the
advertised walk-forward run on the committed AAPL/GOOGL pair so a silent
change to the backtest numbers is caught. Relative tolerance only, never
exact equality.

Verdicts are falsification outcomes, never profitability claims: the raw
out-of-sample Sharpe is negative (-0.5888) and the total return is negative
(-21.59%), and the Deflated Sharpe p-value (0.9946) is far above 0.10, so
the multiple-testing-corrected evidence fails and the honest verdict is NOT
SUPPORTED. The test does not tune to force SUPPORT.

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

# Pre-registered grid (fixed before inspecting results).
PARAM_GRID = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Falsification thresholds, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10
RAW_SHARPE_THRESHOLD = 0.0
TOTAL_RETURN_THRESHOLD = 0.0


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("multi_pair_zscore_mean_reversion", json.dumps(params))


def _run_walk_forward():
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def test_walk_forward_zscore_pair_real_aapl_googl_runs():
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

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


def test_walk_forward_zscore_pair_real_aapl_googl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    AAPL/GOOGL pair must reproduce the pinned out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Enforces the honest falsification discipline (do not tune to force
    SUPPORT): raw OOS Sharpe and total return are negative, and the Deflated
    Sharpe p-value (0.9946) is far above 0.10, so every criterion fails and
    the verdict is NOT SUPPORTED.
    """
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

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
        "oos_sharpe": -0.28894378705362195,
        "oos_volatility": 0.08364046460240565,
        "total_oos_return": -0.029813005194749165,
        "n_positive_periods": 192.0,
        "win_rate_periods": 0.19257773319959878,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        assert key in summary, f"missing {key}"
        got = summary[key]
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    dsr = summary.get("deflated_sharpe") or {}
    assert dsr.get("n_trials") == 8
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None
    assert abs(dsr_p - 0.9945669877489902) <= 1e-3 * max(abs(0.9945669877489902), 1e-9)

    bd = summary.get("book_diagnostic") or {}
    assert bd.get("n_periods_with_book") == 726
    assert abs(bd.get("charged_turnover", 0) - 0.06309464196294441) <= 1e-3

    raw_ok = summary["oos_sharpe"] > RAW_SHARPE_THRESHOLD
    ret_ok = summary["total_oos_return"] > TOTAL_RETURN_THRESHOLD
    dsr_ok = dsr_p < DSR_PVALUE_THRESHOLD
    verdict = "SUPPORTED" if (raw_ok and ret_ok and dsr_ok) else "NOT SUPPORTED"
    assert verdict == "NOT SUPPORTED"
    assert raw_ok is False
    assert ret_ok is False
    assert dsr_ok is False

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_walk_forward_zscore_pair_real_aapl_googl_runs()
    test_walk_forward_zscore_pair_real_aapl_googl_metrics_pinned()
    print("OK")