#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for RSI mean reversion (period=14,
oversold=30, overbought=70, neutral=50) on the committed single-asset panel
(AAPL).

Runs the pre-registered ELEVATED_COST_SWEEP_LEVELS (ascending commission +
slippage above the advertised 3bps round-trip reference) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
RSI mean reversion verdict is NOT SUPPORTED at every tested cost level on this
window: Sharpe degrades from -0.83 to -1.04 and total return from -29.7% to
-35.7% as costs rise to 20bp/10bp. The stronger benchmark-aware guard would be
required to compare against buy-and-hold; this test records the weak-criterion
falsification outcome honestly and does not claim profitability.

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
    ELEVATED_COST_SWEEP_LEVELS,
    SLIPPAGE,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_elevated_cost_sweep_runs_on_aapl_real_window_rsi_mean_reversion():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_elevated_cost_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    # Regression guard: pin strategy metrics (net of costs) per cost level.
    EXPECTED_METRICS = {
        (2.0, 1.0): {
            "sharpe_ratio": -0.8292982062961232,
            "total_return": -0.29712322113455303,
        },
        (5.0, 2.5): {
            "sharpe_ratio": -0.864747873132777,
            "total_return": -0.3074887983771166,
        },
        (10.0, 5.0): {
            "sharpe_ratio": -0.9236946704902164,
            "total_return": -0.32443622582028564,
        },
        (20.0, 10.0): {
            "sharpe_ratio": -1.0409538432301322,
            "total_return": -0.3571329274538704,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["commission_bps"], r["slippage_bps"])
        assert key in EXPECTED_METRICS, f"unexpected cost level {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_real_window_rsi_mean_reversion()
    print("OK")
