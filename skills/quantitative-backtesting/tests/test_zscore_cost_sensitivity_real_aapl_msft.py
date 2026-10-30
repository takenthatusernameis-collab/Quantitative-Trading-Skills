#!/usr/bin/env python3
"""Cost sensitivity on the committed real-market AAPL/MSFT pair for z-score.

Mirrors `test_zscore_cost_sensitivity_real_msft_googl.py`: sweeps commission /
slippage across ascending levels from frictionless to 10bp comm + 5bp slip,
reporting per-criterion pass/fail and the verdict at each level. No
profitability claim is made.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,MSFT}.csv). No live network.
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
    COST_SWEEP_LEVELS,
    run_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    aapl = pd.read_csv(SRC / "AAPL.csv")
    msft = pd.read_csv(SRC / "MSFT.csv")
    aapl["symbol"] = "AAPL"
    msft["symbol"] = "MSFT"
    combined = pd.concat([aapl, msft], ignore_index=True)
    out = dest / "aapl_msft_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_cost_sensitivity_runs_on_aapl_msft_real_window_zscore():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_cost_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(COST_SWEEP_LEVELS)
    assert rows[0]["commission_bps"] == 0.0
    assert rows[0]["slippage_bps"] == 0.0
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
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
    assert "COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_cost_sensitivity_runs_on_aapl_msft_real_window_zscore()
    print("OK")
