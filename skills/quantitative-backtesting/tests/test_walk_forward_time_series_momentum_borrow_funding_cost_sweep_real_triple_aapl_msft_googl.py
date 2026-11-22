#!/usr/bin/env python3
"""Borrow / funding cost sensitivity on the committed real-market three-asset
panel (AAPL / MSFT / GOOGL) for time-series momentum (TSMOM).

Mirrors test_walk_forward_time_series_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py:
sweeps annualized borrow_cost and funding_cost across ascending levels from
frictionless to 5%/yr + 5%/yr, reporting per-criterion pass/fail and the
verdict at each level on the three-asset TSMOM panel.

Cost mechanics:
  - borrow cost applies to short exposure; the long/flat TSMOM path never
    shorts, so borrow is inert for it.
  - funding cost applies to gross exposure above 1x leverage; on the triple
    panel several assets can be long concurrently, so funding can bite and
    must never improve net performance as it rises.

The directional claim is that higher borrow/funding cost must not improve net
out-of-sample performance; no profitability claim is made.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    BORROW_FUNDING_COST_SWEEP_LEVELS,
    run_borrow_funding_cost_sweep,
)


def test_borrow_funding_cost_sensitivity_runs_on_triple_real_panel_time_series_momentum():
    rows = run_borrow_funding_cost_sweep()

    assert isinstance(rows, list) and len(rows) == len(BORROW_FUNDING_COST_SWEEP_LEVELS)
    # Frictionless first level, ascending borrow and funding thereafter.
    assert rows[0]["borrow_cost"] == 0.0
    assert rows[0]["funding_cost"] == 0.0
    for prev, curr in zip(rows, rows[1:]):
        assert curr["borrow_cost"] >= prev["borrow_cost"]
        assert curr["funding_cost"] >= prev["funding_cost"]
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
    # Non-vacuity guard: every level must report real (non-NaN) OOS metrics.
    # The walk-forward must produce tradable positions; if it ever produced
    # all-NaN results the directional assertions below would pass vacuously.
    for r in rows:
        assert r["sharpe_ratio"] is not None, (
            f"vacuous NaN Sharpe at borrow={r['borrow_cost']}/funding={r['funding_cost']}: "
            "the walk-forward produced no tradable positions"
        )
        assert r["total_return"] is not None, (
            f"vacuous NaN total_return at borrow={r['borrow_cost']}/funding={r['funding_cost']}"
        )
        assert r["deflated_sharpe_pvalue"] is not None, (
            f"vacuous NaN deflated_sharpe_pvalue at borrow={r['borrow_cost']}/funding={r['funding_cost']}"
        )
    # Directional claim: net out-of-sample performance must not improve as
    # borrow/funding cost rises (borrow/funding are real costs).
    for prev, curr in zip(rows, rows[1:]):
        assert curr["sharpe_ratio"] <= prev["sharpe_ratio"] + 1e-12, (
            "Sharpe improves with borrow/funding cost: "
            f"{prev['sharpe_ratio']} -> {curr['sharpe_ratio']}"
        )
        assert curr["total_return"] <= prev["total_return"] + 1e-12, (
            "total return improves with borrow/funding cost: "
            f"{prev['total_return']} -> {curr['total_return']}"
        )


if __name__ == "__main__":
    test_borrow_funding_cost_sensitivity_runs_on_triple_real_panel_time_series_momentum()
    print("OK")
