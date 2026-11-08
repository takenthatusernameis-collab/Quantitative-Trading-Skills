#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for multi-pair z-score mean
reversion on the committed two-asset panel (AAPL / MSFT).

Uses ``multi_pair_zscore_mean_reversion`` on a two-asset panel (trades the
single pair and aggregates into a book). Evaluates across chronological
walk-forward windows (train 12 / test 12 months, stepping 12 months) on
committed fixtures only, with pre-registered parameters and the Deflated
Sharpe Ratio multiple-testing correction applied to the pooled
out-of-sample record. Pins the observed out-of-sample metrics (regression
guard, relative tolerance, never exact equality) so a silent change to the
backtest numbers is caught.

Verdicts are falsification outcomes, never profitability claims: the raw
out-of-sample Sharpe is positive (+0.3071) and total return is positive
(+37.17%), but the Deflated Sharpe p-value (0.6659) is far above 0.10, so the
honest verdict is NOT SUPPORTED. The test does not tune to force SUPPORT.

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


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv"):
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


def test_walk_forward_zscore_pair_real_aapl_msft_runs():
    for name in ("AAPL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
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


def test_walk_forward_zscore_pair_real_aapl_msft_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    AAPL/MSFT panel must reproduce the pinned out-of-sample metrics (net of
    costs). Relative tolerance only, never exact equality.

    Honest outcome: Sharpe > 0 and return > 0 pass, but the Deflated Sharpe
    p-value (0.6659) >= 0.10 fails, so the hypothesis is NOT SUPPORTED.
    """
    for name in ("AAPL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": 0.30714511853085896,
        "total_oos_return": 0.37165393035802174,
        "deflated_sharpe_pvalue": 0.6658756888004178,
        "deflated_sharpe_ratio": 0.33412431119958225,
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

    # Honest verdict: Sharpe > 0 and return > 0 pass, but Deflated Sharpe
    # p-value >= 0.10 fails, so the hypothesis is NOT SUPPORTED.
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
    test_walk_forward_zscore_pair_real_aapl_msft_runs()
    test_walk_forward_zscore_pair_real_aapl_msft_metrics_pinned()
    print("OK")
