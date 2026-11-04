#!/usr/bin/env python3
"""Parameter sensitivity sweep for simple momentum (SMA crossover fast / slow)
on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised fast=10 / slow=30 setting) and pins the observed out-of-sample
metrics (net of costs) with relative tolerance so any silent change to the
backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
simple momentum verdict is SUPPORTED across all six pre-registered parameter
settings on this window, but the stronger benchmark-aware guard
(test_simple_momentum_benchmark_aware_real_aapl.py) records NOT SUPPORTED
for the advertised setting when comparing against buy-and-hold AAPL with
Deflated Sharpe correction. This test records the weak-criterion outcome
honestly and does not claim profitability; benchmark-aware comparison is
required.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from simple_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_simple_momentum():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (fast, slow) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["fast_period"] == int(fast)
        assert r["slow_period"] == int(slow)
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

    EXPECTED_METRICS = {
        (10, 30): {
            "sharpe_ratio": 1.501892938128653,
            "total_return": 0.7616516108796803,
        },
        (7, 30): {
            "sharpe_ratio": 1.5655458472181898,
            "total_return": 0.776839583459745,
        },
        (15, 30): {
            "sharpe_ratio": 1.8612153451515092,
            "total_return": 0.9654769606088658,
        },
        (10, 20): {
            "sharpe_ratio": 1.48719245461529,
            "total_return": 0.7343531843248572,
        },
        (10, 40): {
            "sharpe_ratio": 1.5126489928383258,
            "total_return": 0.7350825882708802,
        },
        (5, 20): {
            "sharpe_ratio": 1.6815955431403176,
            "total_return": 0.8243383981766756,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["fast_period"], r["slow_period"])
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
    test_param_sensitivity_runs_on_aapl_real_window_simple_momentum()
    print("OK")
