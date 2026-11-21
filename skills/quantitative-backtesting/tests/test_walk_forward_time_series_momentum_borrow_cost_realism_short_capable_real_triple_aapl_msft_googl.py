#!/usr/bin/env python3
"""Borrow cost realism on the committed real-market three-asset panel
(AAPL / MSFT / GOOGL) for time-series momentum (TSMOM) with
``allow_short=True``.

Unlike the long/flat default path (where borrow is structurally inert because
the strategy never shorts), this variant can carry short exposure, so borrow
cost is a real cost that applies to short exposure and must never improve net
out-of-sample performance as it rises.

Mirrors test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py:
sweeps annualized borrow_cost across ascending levels from frictionless to
5%/yr, reporting per-criterion pass/fail and the verdict at each level on the
short-capable TSMOM triple panel.

The directional claim is that higher borrow cost must not improve net
out-of-sample performance; no profitability claim is made.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    BORROW_COST_SWEEP_SHORT_CAPABLE_LEVELS,
    run_borrow_cost_sweep_short_capable,
)


def test_borrow_cost_realism_short_capable_runs_on_triple_real_panel_time_series_momentum():
    rows = run_borrow_cost_sweep_short_capable()

    assert isinstance(rows, list) and len(rows) == len(BORROW_COST_SWEEP_SHORT_CAPABLE_LEVELS)
    # Frictionless first level, strictly ascending borrow cost thereafter.
    assert rows[0]["borrow_cost"] == 0.0
    for prev, curr in zip(rows, rows[1:]):
        assert curr["borrow_cost"] > prev["borrow_cost"], "borrow cost levels not strictly ascending"
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
    # A prior fixed lookback=252 made all metrics None and the directional
    # assertions below passed vacuously; the sweep now uses the full grid.
    for r in rows:
        assert r["sharpe_ratio"] is not None, (
            f"vacuous NaN Sharpe at borrow_cost={r['borrow_cost']}: the "
            "walk-forward produced no tradable positions"
        )
        assert r["total_return"] is not None, (
            f"vacuous NaN total_return at borrow_cost={r['borrow_cost']}"
        )
        assert r["deflated_sharpe_pvalue"] is not None, (
            f"vacuous NaN deflated_sharpe_pvalue at borrow_cost={r['borrow_cost']}"
        )
    # Directional claim: net out-of-sample performance must not improve as
    # borrow cost rises (borrow is a cost applied to short exposure).
    for prev, curr in zip(rows, rows[1:]):
        assert curr["sharpe_ratio"] <= prev["sharpe_ratio"] + 1e-12, (
            "Sharpe improves with borrow cost on short-capable variant: "
            f"{prev['sharpe_ratio']} -> {curr['sharpe_ratio']}"
        )
        assert curr["total_return"] <= prev["total_return"] + 1e-12, (
            "total return improves with borrow cost on short-capable variant: "
            f"{prev['total_return']} -> {curr['total_return']}"
        )


if __name__ == "__main__":
    test_borrow_cost_realism_short_capable_runs_on_triple_real_panel_time_series_momentum()
    print("OK")
