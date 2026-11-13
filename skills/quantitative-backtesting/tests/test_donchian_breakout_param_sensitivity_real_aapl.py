#!/usr/bin/env python3
"""Parameter sensitivity sweep for Donchian breakout (period / exit_period)
on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised period=20, exit_period=10 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
Donchian breakout verdict is mixed across the six pre-registered parameter
settings on this window: the advertised (20, 10) setting is SUPPORTED but the
shorter (10, 5) setting is NOT SUPPORTED, so the verdict flips across the
grid. The stronger benchmark-aware guard
(test_donchian_breakout_benchmark_aware_real_aapl.py) records NOT SUPPORTED
for the advertised setting when comparing against buy-and-hold AAPL with
Deflated Sharpe correction. This test records the weak-criterion outcome
honestly and does not claim profitability; benchmark-aware comparison is
required and robustness must be evaluated across both criteria.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from donchian_breakout_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_donchian_breakout():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (period, exit_period) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["period"] == int(period)
        assert r["exit_period"] == int(exit_period)
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
        (20, 10): {
            "sharpe_ratio": 0.07917778255250124,
            "total_return": 0.009550335581158587,
        },
        (10, 5): {
            "sharpe_ratio": -0.14735336599507975,
            "total_return": -0.06269088693984548,
        },
        (40, 20): {
            "sharpe_ratio": 0.2305379991985617,
            "total_return": 0.05495943938550618,
        },
        (20, 5): {
            "sharpe_ratio": 0.32054250160631814,
            "total_return": 0.08253259168555527,
        },
        (20, 20): {
            "sharpe_ratio": 0.12791022169955138,
            "total_return": 0.016401781131697213,
        },
        (14, 7): {
            "sharpe_ratio": 0.07661670852633332,
            "total_return": 0.008276276021433882,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["period"], r["exit_period"])
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
    test_param_sensitivity_runs_on_aapl_real_window_donchian_breakout()
    print("OK")
