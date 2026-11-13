#!/usr/bin/env python3
"""Parameter sensitivity sweep for MACD (fast / slow / signal periods) on the
committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised fast=12 / slow=26 / signal=9 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
MACD crossover verdict is NOT SUPPORTED across all six pre-registered parameter
settings on this window: the advertised (12, 26, 9) setting fails both
criteria (Sharpe -1.1718, return -34.41%) and every perturbation stays
negative. The stronger benchmark-aware guard
(test_macd_benchmark_aware_real_aapl.py) records NOT SUPPORTED for the
advertised setting: MACD does not beat buy-and-hold AAPL (return 17.78%), the
benchmark alpha is not significant, and the Deflated Sharpe p-value is not
significant across 6 trials. This test records the weak-criterion
falsification outcome honestly and does not claim profitability; the uniform
failure is evidence against robustness, not of an edge.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from macd_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_macd():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (fast, slow, signal) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["fast_period"] == int(fast)
        assert r["slow_period"] == int(slow)
        assert r["signal_period"] == int(signal)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
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
        (12, 26, 9): {
            "sharpe_ratio": -1.1717750623626866,
            "total_return": -0.34413777065367634,
        },
        (8, 21, 5): {
            "sharpe_ratio": -0.8679421061142073,
            "total_return": -0.27761654627559595,
        },
        (16, 34, 12): {
            "sharpe_ratio": -1.6171267859649459,
            "total_return": -0.440134067937031,
        },
        (12, 26, 6): {
            "sharpe_ratio": -1.2162315091581002,
            "total_return": -0.35460176742718585,
        },
        (12, 26, 12): {
            "sharpe_ratio": -0.9596387359556532,
            "total_return": -0.2963507522345299,
        },
        (10, 24, 9): {
            "sharpe_ratio": -1.0558872241577555,
            "total_return": -0.3176876738408976,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["fast_period"], r["slow_period"], r["signal_period"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )

    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_real_window_macd()
    print("OK")