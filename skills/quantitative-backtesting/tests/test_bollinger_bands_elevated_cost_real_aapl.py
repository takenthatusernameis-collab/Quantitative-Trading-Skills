#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for Bollinger Bands (mean reversion,
period=20, std_dev=2.0) on the committed single-asset panel (AAPL).

Runs the pre-registered ELEVATED_COST_SWEEP_LEVELS (ascending commission +
slippage above the advertised 3bps round-trip reference) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
Bollinger Bands mean-reversion verdict is NOT SUPPORTED across all tested
cost levels on this window. The stronger benchmark-aware guard
(test_bollinger_bands_benchmark_aware_real_aapl.py) also records NOT SUPPORTED
(does not beat buy-and-hold AAPL, Deflated Sharpe p = 1.00 across 6 trials).
The two verdicts are consistent -- this test records the weak-criterion
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

from bollinger_bands_hypothesis import (  # noqa: E402
    COMMISSION,
    ELEVATED_COST_SWEEP_LEVELS,
    SLIPPAGE,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_elevated_cost_sweep_runs_on_aapl_real_window_bollinger_bands():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_elevated_cost_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    # First level is the advertised reference, re-run for baseline comparison.
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    # Ascending costs above the advertised reference.
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    # Determinate verdicts; never a profitability claim.
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
            "sharpe_ratio": -0.1439393233148262,
            "total_return": -0.050513414733230566,
        },
        (5.0, 2.5): {
            "sharpe_ratio": -0.17479064416831386,
            "total_return": -0.05912254078037327,
        },
        (10.0, 5.0): {
            "sharpe_ratio": -0.22598286707918178,
            "total_return": -0.07330651901374452,
        },
        (20.0, 10.0): {
            "sharpe_ratio": -0.32744802811584584,
            "total_return": -0.10106738375770641,
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

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_real_window_bollinger_bands()
    print("OK")
