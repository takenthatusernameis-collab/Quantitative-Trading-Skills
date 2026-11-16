#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for time-series momentum (TSMOM) on the
committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_cross_sectional_momentum_elevated_cost_real_triple_aapl_msft_googl.py:
sweeps commission / slippage across ascending levels above the advertised
3bps (2bp comm + 1bp slip) round-trip, re-running the advertised level first
as the reference baseline, on the three-asset TSMOM walk-forward panel. Reports
per-criterion pass/fail and the verdict at each level, and flags whether the
verdict flips as costs rise. Verdict flips are the signal that the result is
not robust to elevated costs -- this test never asserts SUPPORTED as a
profitability claim.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    ELEVATED_COST_SWEEP_LEVELS,
    run_elevated_cost_sweep,
)


def test_elevated_cost_sweep_runs_on_triple_real_window_time_series_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SKILLS_DIR / "assets" / "example_data" / "real_market_data" / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_elevated_cost_sweep()

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
        assert len(r["criteria"]) == 3
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
            "deflated_sharpe_pvalue_lt_0.10",
        }
    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_triple_real_window_time_series_momentum()
    print("OK")