#!/usr/bin/env python3
"""Cost sensitivity on the committed real-market three-asset panel
(AAPL / MSFT / GOOGL) for time-series momentum (TSMOM).

Mirrors test_cross_sectional_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py:
sweeps commission / slippage across ascending levels from frictionless to
10bp comm + 5bp slip, reporting per-criterion pass/fail and the verdict at
each level on the three-asset TSMOM panel. The directional claim is that
higher per-trade costs reduce net out-of-sample performance; no profitability
claim is made.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    COST_SWEEP_LEVELS,
    run_cost_sweep,
)


def test_cost_sensitivity_runs_on_triple_real_panel_time_series_momentum():
    rows = run_cost_sweep()

    assert isinstance(rows, list) and len(rows) == len(COST_SWEEP_LEVELS)
    # Frictionless first level, ascending costs thereafter.
    assert rows[0]["commission_bps"] == 0.0
    assert rows[0]["slippage_bps"] == 0.0
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


if __name__ == "__main__":
    test_cost_sensitivity_runs_on_triple_real_panel_time_series_momentum()
    print("OK")