#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for multi-pair z-score mean reversion on
the committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_zscore_elevated_cost_sensitivity_real_msft_googl.py but on a
three-asset panel. Re-runs the pre-registered falsification criteria at
ascending cost levels above the advertised 3bps round-trip, with the
advertised level re-run first as the reference baseline. Reports per-criterion
pass/fail and the verdict at each level, and flags whether the verdict flips
as costs rise. Verdict flips are the signal that the result is not robust to
elevated costs -- this test never asserts SUPPORTED as a profitability claim.
Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from zscore_mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    ELEVATED_COST_SWEEP_LEVELS,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def test_elevated_cost_sweep_runs_on_triple_real_window_multi_pair_zscore():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(data_path, strategy="multi_pair_zscore_mean_reversion")

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

    # Regression guard: pin the observed out-of-sample metrics per cost level
    # so the falsification evidence (SUPPORTED at advertised/low cost, NOT
    # SUPPORTED at elevated cost) is reproducible and any silent change to the
    # backtest numbers is caught. Values reproduced on committed fixtures with
    # the current library build; compared with a relative tolerance (never exact
    # equality, since the last decimals depend on the numpy/pandas build).
    EXPECTED_METRICS = {
        (2, 1): (0.22928163042546806, 0.08885542249506262),
        (5, 2.5): (0.03645166937976205, 0.030174339523501903),
        (10, 5): (-0.28347173461581776, -0.060753438896405165),
        (20, 10): (-0.9118979386313808, -0.21945634456115926),
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["commission_bps"], r["slippage_bps"])
        assert key in EXPECTED_METRICS, f"unexpected cost level {key}"
        exp_sharpe, exp_ret = EXPECTED_METRICS[key]
        assert r["sharpe_ratio"] is not None, f"missing sharpe at {key}"
        assert r["total_return"] is not None, f"missing total_return at {key}"
        assert abs(r["sharpe_ratio"] - exp_sharpe) <= REL_TOL * max(
            abs(exp_sharpe), 1e-9
        ), f"sharpe regression at {key}: got {r['sharpe_ratio']}, expected {exp_sharpe}"
        assert abs(r["total_return"] - exp_ret) <= REL_TOL * max(
            abs(exp_ret), 1e-9
        ), f"total_return regression at {key}: got {r['total_return']}, expected {exp_ret}"

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_triple_real_window_multi_pair_zscore()
    print("OK")
