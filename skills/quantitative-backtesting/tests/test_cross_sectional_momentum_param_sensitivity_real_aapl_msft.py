#!/usr/bin/env python3
"""Parameter sensitivity on the committed real-market AAPL/MSFT pair.

Mirrors `test_cross_sectional_momentum_param_sensitivity_real_msft_googl.py`:
sweeps (lookback, top_quantile, bottom_quantile) across PARAM_SENSITIVITY_GRID
using the committed fixtures, reporting per-criterion pass/fail and the verdict
per setting. No profitability claim is made.

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

from cross_sectional_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    PARAM_SENSITIVITY_GRID,
    run_param_sensitivity_sweep,
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


def test_param_sensitivity_runs_on_aapl_msft_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (lookback, top_q, bottom_q) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["lookback"] == int(lookback)
        assert r["top_quantile"] == float(top_q)
        assert r["bottom_quantile"] == float(bottom_q)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }
    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_msft_real_window()
    print("OK")
