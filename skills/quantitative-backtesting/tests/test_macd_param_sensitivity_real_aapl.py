#!/usr/bin/env python3
"""Parameter sensitivity sweep for MACD (fast / slow / signal periods) on the
committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised fast=12 / slow=26 / signal=9 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
MACD crossover verdict is mixed across the six pre-registered parameter
settings on this window: the advertised (12, 26, 9) setting fails the
total-return criterion (return -0.13% vs the zero baseline), as do the shorter
(8, 21, 5) and (12, 26, 6) and (10, 24, 9) settings, while the longer
(16, 34, 12) and (12, 26, 12) settings pass both weak criteria. The stronger
benchmark-aware guard (test_macd_benchmark_aware_real_aapl.py) records NOT
SUPPORTED for the advertised setting: MACD does not beat buy-and-hold AAPL
(return 77.4%), the benchmark alpha is not significant (raw p = 0.60), and the
Deflated Sharpe p-value is not significant (p = 0.96 across 6 trials). This
test records the weak-criterion falsification outcome honestly and does not
claim profitability; the mixed sweep result is itself evidence of parameter
sensitivity, not of a robust edge.

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
            "sharpe_ratio": 0.055681981432280425,
            "total_return": -0.0013037799286792495,
        },
        (8, 21, 5): {
            "sharpe_ratio": 0.022000277047474096,
            "total_return": -0.01577077221885015,
        },
        (16, 34, 12): {
            "sharpe_ratio": 0.8553674517432268,
            "total_return": 0.5082147950728451,
        },
        (12, 26, 6): {
            "sharpe_ratio": -0.17340380820185772,
            "total_return": -0.11091505654743661,
        },
        (12, 26, 12): {
            "sharpe_ratio": 0.13445876717754857,
            "total_return": 0.042214921147721185,
        },
        (10, 24, 9): {
            "sharpe_ratio": -0.055766056887497896,
            "total_return": -0.05632129853788492,
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