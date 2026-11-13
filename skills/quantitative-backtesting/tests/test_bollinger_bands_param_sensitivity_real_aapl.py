#!/usr/bin/env python3
"""Parameter sensitivity sweep for Bollinger Bands (period / std_dev) on the
committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised period=20, std_dev=2.0 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
Bollinger Bands mean-reversion verdict is NOT SUPPORTED at the advertised
setting (period=20, std_dev=2.0) and at three of the six pre-registered
parameter settings, but SUPPORTED at two settings (period=10/std_dev=2.0 and
period=20/std_dev=2.5) -- so the verdict is parameter-dependent on this window,
which is evidence against robustness, not of an edge. The stronger
benchmark-aware guard (test_bollinger_bands_benchmark_aware_real_aapl.py)
records NOT SUPPORTED for the advertised setting. This test records the
weak-criterion falsification outcome honestly and does not claim
profitability; a verdict that flips across the grid is a sensitivity finding.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from bollinger_bands_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_bollinger_bands():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (period, std_dev) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["period"] == int(period)
        assert r["std_dev"] == float(std_dev)
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
        (20, 2.0): {
            "sharpe_ratio": -0.1439393233148262,
            "total_return": -0.050513414733230566,
        },
        (10, 2.0): {
            "sharpe_ratio": 0.4576538694132583,
            "total_return": 0.11822568790165988,
        },
        (50, 2.0): {
            "sharpe_ratio": -0.5245531240621486,
            "total_return": -0.16182536426809813,
        },
        (20, 1.5): {
            "sharpe_ratio": -0.27345219615268906,
            "total_return": -0.0915043652530747,
        },
        (20, 2.5): {
            "sharpe_ratio": 0.783565051417456,
            "total_return": 0.20905811448071132,
        },
        (10, 1.5): {
            "sharpe_ratio": 0.030610359017053345,
            "total_return": -0.004220971098055082,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["period"], r["std_dev"])
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
    test_param_sensitivity_runs_on_aapl_real_window_bollinger_bands()
    print("OK")
