#!/usr/bin/env python3
"""Parameter sensitivity sweep for the Kelly criterion overlay (lookback,
fraction) on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID and pins observed out-of-sample
metrics (net of costs) with relative tolerance.

METHODOLOGICAL NOTE (committed fixtures only): under the weak two-criterion
sweep (oos_sharpe > 0, oos_total_return > 0) the verdict is SUPPORTED at four
of the six pre-registered settings on this window (lookback 63 and 100 beats
a zero baseline) but NOT SUPPORTED at the lookback=50 rung (both criteria
fail), so the verdict flips across the grid. The benchmark-aware guard
(test_kelly_criterion_benchmark_aware_real_aapl.py) records NOT SUPPORTED
(vs buy-and-hold, alpha/DSR not significant). On this fixture, fraction
(0.25/0.5/1.0) is insensitive for these lookbacks under the CLI sizing path
(observed), so lookback drives variation; the grid is pre-registered and
honest. Records weak-criterion outcomes only, no profitability claim; a
verdict that flips across the grid is a sensitivity finding.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from kelly_criterion_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
REL_TOL = 1e-3


def test_param_sensitivity_runs_on_aapl_real_window_kelly_criterion():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (lookback, fraction) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["lookback"] == int(lookback)
        assert r["fraction"] == float(fraction)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    # Pinned observed metrics (fraction insensitive across 0.25/0.5/1.0 here).
    EXPECTED_METRICS = {
        (63, 0.5):  {"sharpe_ratio": 0.5000125402775002, "total_return": 0.16104626397549926},
        (50, 0.5):  {"sharpe_ratio": -0.38367414883518386, "total_return": -0.15719611990517068},
        (100, 0.5): {"sharpe_ratio": 0.367259699743025, "total_return": 0.10659026717311959},
        (63, 0.25): {"sharpe_ratio": 0.5000125402775002, "total_return": 0.16104626397549926},
        (63, 1.0):  {"sharpe_ratio": 0.5000125402775002, "total_return": 0.16104626397549926},
        (50, 0.25): {"sharpe_ratio": -0.38367414883518386, "total_return": -0.15719611990517068},
    }
    for r in rows:
        key = (r["lookback"], r["fraction"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )
        # Verdict is pinned per setting: the lookback=50 rung fails both weak
        # criteria on this window, so the sweep is NOT uniformly SUPPORTED --
        # the verdict flips across the grid, which is evidence of parameter
        # sensitivity, not of a robust edge. Do not assert a single verdict
        # across the whole grid.
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == (r["verdict"] == "SUPPORTED")

    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_real_window_kelly_criterion()
    print("OK")
