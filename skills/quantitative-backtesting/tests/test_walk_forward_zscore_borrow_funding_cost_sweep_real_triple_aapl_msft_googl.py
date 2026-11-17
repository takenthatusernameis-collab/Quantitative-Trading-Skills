#!/usr/bin/env python3
"""Borrow / funding cost sensitivity on the committed real-market three-asset
panel (AAPL / MSFT / GOOGL) for multi-pair z-score mean reversion.

Mirrors test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py:
sweeps annualized borrow_cost and funding_cost across ascending levels from
frictionless to 5%/yr + 5%/yr, reporting per-criterion pass/fail and the
verdict at each level on the triple-panel z-score mean-reversion path.

Cost mechanics:
  - borrow cost applies to short exposure. Z-score mean reversion is long/short,
    so borrow cost actually bites on the short legs.
  - funding cost applies to gross exposure above 1x leverage; on the triple
    panel several assets can be long concurrently, so funding cost can bite and
    must never improve net performance as it rises.

The directional claim is that higher borrow/funding cost must not improve net
out-of-sample performance; no profitability claim is made.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered grid (fixed before inspecting results).
PARAM_GRID = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Falsification thresholds, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10
RAW_SHARPE_THRESHOLD = 0.0
TOTAL_RETURN_THRESHOLD = 0.0


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("multi_pair_zscore_mean_reversion", params)


def _run_walk_forward(borrow_cost, funding_cost):
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        borrow_cost=borrow_cost,
        funding_cost=funding_cost,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


# Annual borrow / funding cost levels exercised by the borrow/funding
# sensitivity sweep on the committed AAPL/MSFT/GOOGL triple panel for the
# multi-pair z-score walk-forward path. Ascending, pre-registered, starting at
# the advertised frictionless reference (borrow/funding disabled).
BORROW_FUNDING_COST_SWEEP_LEVELS = [(0.0, 0.0), (0.01, 0.01), (0.03, 0.03), (0.05, 0.05)]


def test_walk_forward_zscore_borrow_funding_cost_sweep_real_triple_aapl_msft_googl():
    """Borrow/funding-cost sensitivity sweep for the committed AAPL/MSFT/GOOGL
    triple-panel multi-pair z-score walk-forward path.

    Re-runs the pre-registered falsification criteria at ascending annual
    borrow-cost and funding-cost levels, with the advertised frictionless run
    (borrow_cost=0.0, funding_cost=0.0) re-run first as the reference baseline.
    Reports per-criterion pass/fail and the verdict at each level, and flags
    whether the verdict flips as borrow/funding costs rise. Verdict flips are
    the signal that the result is not robust to borrow/funding costs -- this
    test never asserts SUPPORTED as a profitability claim.

    Directional claim: higher borrow/funding costs must never improve net
    out-of-sample performance (monotonic degradation of Sharpe and total
    return).

    Offline, committed fixtures only; no live network.
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for borrow_cost, funding_cost in BORROW_FUNDING_COST_SWEEP_LEVELS:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result = _run_walk_forward(borrow_cost, funding_cost)
            summary = result.get("summary", {})
            dsr = summary.get("deflated_sharpe") or {}
            dsr_p = dsr.get("p_value")
            sharpe = summary.get("oos_sharpe")
            total_ret = summary.get("total_oos_return")

            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = total_ret is not None and float(total_ret) > 0
            ok3 = dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
            passes = {
                "oos_sharpe_gt_zero": bool(ok1),
                "oos_total_return_positive": bool(ok2),
                "deflated_sharpe_pvalue_lt_0.10": bool(ok3),
            }
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "borrow_cost": borrow_cost,
                "funding_cost": funding_cost,
                "borrow_cost_bps_per_year": borrow_cost * 10_000,
                "funding_cost_bps_per_year": funding_cost * 10_000,
                "sharpe_ratio": sharpe,
                "total_return": total_ret,
                "deflated_sharpe_pvalue": dsr_p,
                "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
                "verdict": verdict,
                "all_pass": all(passes.values()),
            })

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
    # Directional claim: net out-of-sample performance must not improve as
    # borrow/funding cost rises (Sharpe and total return are non-increasing).
    for prev, curr in zip(rows, rows[1:]):
        if prev["sharpe_ratio"] is not None and curr["sharpe_ratio"] is not None:
            assert curr["sharpe_ratio"] <= prev["sharpe_ratio"] + 1e-12, (
                "Sharpe improves with borrow/funding cost: "
                f"{prev['sharpe_ratio']} -> {curr['sharpe_ratio']}"
            )
        if prev["total_return"] is not None and curr["total_return"] is not None:
            assert curr["total_return"] <= prev["total_return"] + 1e-12, (
                "total return improves with borrow/funding cost: "
                f"{prev['total_return']} -> {curr['total_return']}"
            )


if __name__ == "__main__":
    test_walk_forward_zscore_borrow_funding_cost_sweep_real_triple_aapl_msft_googl()
    print("OK")
