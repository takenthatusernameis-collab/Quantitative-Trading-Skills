#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for simple momentum (SMA crossover,
fast=10 / slow=30, long-only) on the committed single-asset panel (AAPL).

Runs the pre-registered ELEVATED_COST_SWEEP_LEVELS (ascending commission +
slippage above the advertised 3bps round-trip reference) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
simple momentum crossover verdict is SUPPORTED across all tested cost levels on
this window: Sharpe stays positive (1.50 -> 1.40) and total return stays
positive (76.2% -> 69.2%) even at the 20bp + 10bp round-trip level. The
stronger benchmark-aware guard
(test_simple_momentum_benchmark_aware_real_aapl.py) records NOT SUPPORTED for
the advertised setting: simple momentum does not beat buy-and-hold AAPL
(strategy 76.2% vs benchmark 77.4%), the benchmark alpha is not significant
(raw p = 0.12), and the Deflated Sharpe p-value is not significant (p = 0.41
across 6 trials). The two verdicts are consistent -- the weak sweep overstates
the edge and the benchmark-aware control falsifies it. This test records the
weak-criterion falsification outcome honestly and does not claim profitability.

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
    ELEVATED_COST_SWEEP_LEVELS,
    SLIPPAGE,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_elevated_cost_sweep_runs_on_aapl_real_window_simple_momentum():
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
            "sharpe_ratio": 1.501892938128653,
            "total_return": 0.7616516108796803,
        },
        (5.0, 2.5): {
            "sharpe_ratio": 1.4843430021036015,
            "total_return": 0.7498512163419406,
        },
        (10.0, 5.0): {
            "sharpe_ratio": 1.4549310185359883,
            "total_return": 0.7303476940682787,
        },
        (20.0, 10.0): {
            "sharpe_ratio": 1.3955347074425695,
            "total_return": 0.6919477947304276,
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
    test_elevated_cost_sweep_runs_on_aapl_real_window_simple_momentum()
    print("OK")
