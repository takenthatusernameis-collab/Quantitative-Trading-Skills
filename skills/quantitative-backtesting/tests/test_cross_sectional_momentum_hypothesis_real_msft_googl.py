#!/usr/bin/env python3
"""Real-market falsification test for cross-sectional momentum on MSFT / GOOGL.

Mirrors test_zscore_hypothesis_real_msft_googl.py but exercises a different
strategy family (cross-sectional momentum vs z-score mean-reversion pairs) on
the same committed real-market fixtures. Verdicts are falsification outcomes,
never profitability claims. Offline, committed fixtures only; no live network.
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
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    msft = pd.read_csv(SRC / "MSFT.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    msft["symbol"] = "MSFT"
    googl["symbol"] = "GOOGL"
    combined = pd.concat([msft, googl], ignore_index=True)
    out = dest / "msft_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_hypothesis_runs_on_msft_googl_real_window():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(data_path, "msft_googl cross-sectional momentum real window")

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 2
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    out = buffer.getvalue()
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out


if __name__ == "__main__":
    test_hypothesis_runs_on_msft_googl_real_window()
    print("OK")
