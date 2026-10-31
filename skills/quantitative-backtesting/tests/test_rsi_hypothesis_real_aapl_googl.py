#!/usr/bin/env python3
"""Real-market falsification test for RSI mean-reversion on AAPL / GOOGL.

Mirrors `test_rsi_hypothesis_real_msft_googl.py` but on the AAPL / GOOGL pair:
AAPL.csv is the strategy asset and GOOGL.csv is the alternative benchmark, so
the run exercises a real 10-year window rather than a generated series.
Verdicts are falsification outcomes, never profitability claims. Offline,
committed fixtures only; no live network.
"""
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from rsi_mean_reversion_hypothesis import (  # noqa: E402
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_hypothesis_runs_on_aapl_googl_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(d / "sample_ohlcv.csv")

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
    assert "Split sizes (train/val/test):" in out
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out


if __name__ == "__main__":
    test_hypothesis_runs_on_aapl_googl_real_window()
    print("OK")