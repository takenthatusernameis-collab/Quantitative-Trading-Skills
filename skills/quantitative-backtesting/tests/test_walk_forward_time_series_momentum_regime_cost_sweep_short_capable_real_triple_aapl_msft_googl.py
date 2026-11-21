#!/usr/bin/env python3
"""Stressed-regime cost sensitivity on the committed real-market three-asset
panel (AAPL / MSFT / GOOGL) for time-series momentum (TSMOM) with
``allow_short=True``.

A regime-conditional commission/slippage multiplier is applied to every
detected regime, sweeping from the 1.0 baseline up to 10x. With
``allow_short=True`` the strategy can carry short exposure, so borrow cost
(3%/yr) is a real cost that applies to short exposure and is never inert.

The directional claim is that net out-of-sample performance must not improve
as the stressed-regime cost load rises; no profitability claim is made. This
is sensitivity analysis (does the verdict survive stressed-regime costs),
not a strategy falsification test.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    REGIME_COST_SWEEP_SHORT_CAPABLE_BORROW_COST,
    REGIME_COST_SWEEP_SHORT_CAPABLE_LEVELS,
    run_regime_cost_sweep_short_capable,
)


def test_regime_cost_sensitivity_short_capable_runs_on_triple_real_panel_time_series_momentum():
    rows = run_regime_cost_sweep_short_capable()

    assert isinstance(rows, list) and len(rows) == len(REGIME_COST_SWEEP_SHORT_CAPABLE_LEVELS)
    # Baseline first, strictly ascending stressed-regime cost load thereafter.
    assert rows[0]["regime_multiplier"] == 1.0
    for prev, curr in zip(rows, rows[1:]):
        assert curr["regime_multiplier"] > prev["regime_multiplier"], "regime multiplier levels not strictly ascending"
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
    # Borrow is real (not inert) on the short-capable path.
    assert rows[0]["borrow_cost"] == REGIME_COST_SWEEP_SHORT_CAPABLE_BORROW_COST
    # Non-vacuity guard: every level must report real (non-NaN) OOS metrics.
    # A prior fixed lookback=252 made all metrics None and the directional
    # assertions below passed vacuously; the sweep now uses the full grid.
    for r in rows:
        assert r["sharpe_ratio"] is not None, (
            f"vacuous NaN Sharpe at regime_multiplier={r['regime_multiplier']}: "
            "the walk-forward produced no tradable positions"
        )
        assert r["total_return"] is not None, (
            f"vacuous NaN total_return at regime_multiplier={r['regime_multiplier']}"
        )
        assert r["deflated_sharpe_pvalue"] is not None, (
            f"vacuous NaN deflated_sharpe_pvalue at regime_multiplier={r['regime_multiplier']}"
        )
    # Directional claim: net out-of-sample performance must not improve as the
    # stressed-regime cost load rises (borrow is a real cost on short exposure).
    for prev, curr in zip(rows, rows[1:]):
        assert curr["sharpe_ratio"] <= prev["sharpe_ratio"] + 1e-12, (
            "Sharpe improves with stressed-regime cost load on short-capable variant: "
            f"{prev['sharpe_ratio']} -> {curr['sharpe_ratio']}"
        )
        assert curr["total_return"] <= prev["total_return"] + 1e-12, (
            "total return improves with stressed-regime cost load on short-capable variant: "
            f"{prev['total_return']} -> {curr['total_return']}"
        )


if __name__ == "__main__":
    test_regime_cost_sensitivity_short_capable_runs_on_triple_real_panel_time_series_momentum()
    print("OK")
