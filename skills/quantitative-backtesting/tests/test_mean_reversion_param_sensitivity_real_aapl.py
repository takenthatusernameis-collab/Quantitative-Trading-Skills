#!/usr/bin/env python3
"""Parameter sensitivity sweep for Bollinger Bands mean reversion (period /
std_dev) on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised period=20, std_dev=2.0 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
mean-reversion verdict is NOT SUPPORTED across all six pre-registered
parameter settings on this window. The stronger benchmark-aware guard
(test_mean_reversion_benchmark_aware_real_aapl.py) records NOT SUPPORTED.
This test records the weak-criterion falsification outcome honestly and does
not claim profitability; uniform failure is evidence against robustness.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_mean_reversion():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (period, std_dev) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["period"] == int(period)
        assert r["std_dev"] == float(std_dev)
        assert r.get("commission") == COMMISSION or "commission" not in r
        assert r.get("slippage") == SLIPPAGE or "slippage" not in r
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == (all(c["passed"] for c in r["criteria"]))
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    EXPECTED_METRICS = {
        (20, 2.0): {
            "sharpe_ratio": -1.3013699003638697,
            "total_return": -0.42546223321687104,
        },
        (10, 1.5): {
            "sharpe_ratio": -1.1263882043363285,
            "total_return": -0.37409531803110585,
        },
        (40, 2.0): {
            "sharpe_ratio": -1.231585143316415,
            "total_return": -0.41077356022792977,
        },
        (20, 2.5): {
            "sharpe_ratio": -1.2998563723231422,
            "total_return": -0.3994386699151491,
        },
        (20, 1.0): {
            "sharpe_ratio": -1.3376368160132421,
            "total_return": -0.4971427184048862,
        },
        (14, 2.0): {
            "sharpe_ratio": -1.2217129107335833,
            "total_return": -0.3759724647738052,
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
    test_param_sensitivity_runs_on_aapl_real_window_mean_reversion()
    print("OK")
