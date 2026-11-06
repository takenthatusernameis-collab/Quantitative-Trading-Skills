#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for z-score mean reversion
(single-pair) on the committed two-asset panel (AAPL / GOOGL).

Runs ``build_strategy('zscore_mean_reversion', ...)`` through
``walk_forward_analysis`` on the AAPL/GOOGL pair panel. Pre-registered grid
(period=20, entry_z=2.0, exit_z=0.5), train/test/step=12/12/12 months,
2bps+1bps costs, with Deflated Sharpe correction.

The pair panel is priced under the default net-exposure convention, so the
pair's net exposure is the priced quantity. Under net-exposure pricing the
single-pair z-score book is market-neutral by construction (gross book 1.0,
net exposure 0), so the scalar signal is the directional bet on the spread
rather than a long/short book return. This is a distinct validation path from
the ``multi_pair_zscore_mean_reversion`` book-priced guard
(``test_walk_forward_zscore_pair_real_aapl_googl.py``), which prices the
true per-asset book return.

Honest verdict: NOT SUPPORTED (Sharpe -0.2097, return -10.72%, DSR p=0.9525).
Offline, committed fixtures only.
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
PARAM_GRID = {"period": [20], "entry_z": [2.0], "exit_z": [0.5]}

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
    return build_strategy("zscore_mean_reversion", json.dumps(params))


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
        panel_pricing="net-exposure",
        apply_deflation=True,
        validate_pit=True,
    )


def test_walk_forward_zscore_real_aapl_googl_runs():
    for name in ("AAPL.csv", "GOOGL.csv"):
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


def test_walk_forward_zscore_real_aapl_googl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    AAPL/GOOGL pair must reproduce the pinned out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Honest outcome: the raw out-of-sample Sharpe is negative (-0.2097) and the
    total return is negative (-10.72%), and the Deflated Sharpe p-value
    (0.9525) is far above 0.10, so every criterion fails and the verdict is NOT
    SUPPORTED. The test does not tune to force SUPPORT.
    """
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]
    assert summary["n_periods"] == 8
    assert summary["periods_with_position"] == 8
    assert summary["bias_controls_engaged"] is True

    EXPECTED = {
        "oos_sharpe": -0.20967479043178497,
        "oos_volatility": 0.12593587166939033,
        "total_oos_return": -0.10715648992652782,
        "n_positive_periods": 337,
        "win_rate_periods": 0.16875312969454181,
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
    assert abs(dsr_p - 0.9525007856763341) <= 1e-6 * max(abs(0.9525007856763341), 1e-9)
    dsr_ratio = dsr.get("deflated_sharpe_ratio")
    assert dsr_ratio is not None
    assert abs(dsr_ratio - 0.04749921432366594) <= 1e-6 * max(abs(0.04749921432366594), 1e-9)

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
    test_walk_forward_zscore_real_aapl_googl_runs()
    test_walk_forward_zscore_real_aapl_googl_metrics_pinned()
    print("OK")