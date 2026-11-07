#!/usr/bin/env python3
"""Borrow-cost sensitivity sweep for Bollinger Bands (short-capable) on AAPL."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"

BORROW_COSTS = [0.0, 0.01, 0.03, 0.05]


def _run():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(SRC),
            "--strategy", "bollinger_bands",
            "--params", '{"period": 20, "std_dev": 2.0}',
            "--commission", "0.0002",
            "--slippage", "0.0001",
            "--borrow-costs", *[str(c) for c in BORROW_COSTS],
            "--validate-point-in-time",
            "--output", str(tmp / "out"),
        ]
        r = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        assert r.returncode == 0, f"run_backtest failed\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
        sweep = json.loads((tmp / "out" / "run_backtest_borrow_cost_sweep.json").read_text())
        return sweep


def test_borrow_cost_sweep_runs_on_aapl_real_window_bollinger():
    sweep = _run()
    assert sorted(sweep["borrow_costs"]) == BORROW_COSTS
    assert len(sweep["results"]) == len(BORROW_COSTS)
    for r in sweep["results"]:
        assert r["borrow_cost"] in BORROW_COSTS
        assert r["funding_cost"] == 0.0
        assert r["commission"] == 0.0002
        assert r["slippage"] == 0.0001
        assert r["total_return"] is not None
        assert r["sharpe_ratio"] is not None
        assert r["max_drawdown"] is not None
        assert r["annualized_return"] is not None


def test_borrow_cost_metrics_pinned_on_aapl_real_window_bollinger():
    sweep = _run()
    rows = {r["borrow_cost"]: r for r in sweep["results"]}
    EXPECTED = {
        0.0:  {"total_return": -0.766272162609589,  "sharpe_ratio": -0.7695214181073696, "max_drawdown": -0.7663501816535281, "annualized_return": -0.13558881395060507},
        0.01: {"total_return": -0.7750250579811158, "sharpe_ratio": -0.7893725625124363, "max_drawdown": -0.7750912333107879, "annualized_return": -0.13888968226393805},
        0.03: {"total_return": -0.7915607092812144, "sharpe_ratio": -0.8290531766827137, "max_drawdown": -0.7916054863440233, "annualized_return": -0.1454540426753359},
        0.05: {"total_return": -0.8068821633943203, "sharpe_ratio": -0.8687039090622567, "max_drawdown": -0.8069083276486478, "annualized_return": -0.15196887825888983},
    }
    REL_TOL = 1e-3
    for cost, exp in EXPECTED.items():
        r = rows[cost]
        for k, expv in exp.items():
            got = r[k]
            assert abs(got - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at borrow_cost={cost}: got {got}, expected {expv}"
            )
        # Directional claim: borrow cost must degrade (never improve) a
        # short-capable strategy's net return.
        assert r["total_return"] <= rows[0.0]["total_return"] + 1e-12, (
            f"borrow cost must not improve net return at {cost}"
        )
        assert r["sharpe_ratio"] <= rows[0.0]["sharpe_ratio"] + 1e-12, (
            f"borrow cost must not improve Sharpe at {cost}"
        )


if __name__ == "__main__":
    test_borrow_cost_sweep_runs_on_aapl_real_window_bollinger()
    test_borrow_cost_metrics_pinned_on_aapl_real_window_bollinger()
    print("OK")