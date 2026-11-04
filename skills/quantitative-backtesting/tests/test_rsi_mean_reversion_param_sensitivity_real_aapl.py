#!/usr/bin/env python3
"""Parameter sensitivity sweep for RSI mean reversion (period / oversold /
overbought) on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised period=14 / oversold=30 / overbought=70 setting) and pins the
observed out-of-sample metrics (net of costs) with relative tolerance so any
silent change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
RSI mean reversion verdict is NOT SUPPORTED across all five pre-registered
parameter settings on this window: Sharpe ranges from -0.83 to -1.28 and total
return from -28.3% to -39.0%. The stronger benchmark-aware guard would be
required to compare against buy-and-hold; this test records the weak-criterion
falsification outcome honestly and does not claim profitability; the uniformly
negative sweep result is itself evidence of parameter sensitivity, not of a
robust edge.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from rsi_mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_rsi_mean_reversion():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (period, oversold, overbought) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["period"] == int(period)
        assert r["oversold"] == int(oversold)
        assert r["overbought"] == int(overbought)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    # Regression guard: pin the observed out-of-sample metrics per parameter
    # setting so the robustness evidence is reproducible and any silent change
    # to the backtest numbers is caught. Compared with a relative tolerance.
    EXPECTED_METRICS = {
        (14, 30, 70): {
            "sharpe_ratio": -0.8292982062961232,
            "total_return": -0.29712322113455303,
        },
        (10, 30, 70): {
            "sharpe_ratio": -1.042834568593796,
            "total_return": -0.37143915105174463,
        },
        (20, 30, 70): {
            "sharpe_ratio": -1.2762141872211425,
            "total_return": -0.38822663564266235,
        },
        (14, 25, 70): {
            "sharpe_ratio": -0.8507170866138524,
            "total_return": -0.282641401195895,
        },
        (14, 35, 70): {
            "sharpe_ratio": -1.113509939377958,
            "total_return": -0.38990483545570154,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["period"], r["oversold"], r["overbought"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_real_window_rsi_mean_reversion()
    print("OK")
