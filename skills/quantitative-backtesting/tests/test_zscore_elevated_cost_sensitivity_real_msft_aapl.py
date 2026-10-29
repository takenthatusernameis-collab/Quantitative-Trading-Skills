#!/usr/bin/env python3
"""Elevated-cost confirmation on the committed real-market MSFT/AAPL pair.

Extends the cost-sensitivity evidence with a sweep at cost levels higher than
the advertised 3bps (2bp comm + 1bp slip) round-trip, re-running the
advertised level first as the reference baseline. Reports per-criterion
pass/fail and the verdict at each level, and flags whether the verdict flips
as costs rise. Verdict flips are the signal that the result is not robust to
elevated costs -- this test never asserts SUPPORTED as a profitability claim.

Offline, committed fixtures only (assets/example_data/real_market_data/
{MSFT,AAPL}.csv). No live network.
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


def _build_pair_csv(dest: Path) -> Path:
    msft = pd.read_csv(SRC / "MSFT.csv")
    aapl = pd.read_csv(SRC / "AAPL.csv")
    msft["symbol"] = "MSFT"
    aapl["symbol"] = "AAPL"
    combined = pd.concat([msft, aapl], ignore_index=True)
    out = dest / "msft_aapl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_elevated_cost_sweep_runs_on_msft_aapl_real_window():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "AAPL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(data_path)

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
    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_msft_aapl_real_window()
    print("OK")
