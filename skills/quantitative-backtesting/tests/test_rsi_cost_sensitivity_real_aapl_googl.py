#!/usr/bin/env python3
"""Cost sensitivity on the committed real-market AAPL/GOOGL pair (RSI).

Mirrors `test_rsi_cost_sensitivity_real_msft_googl.py` but on the AAPL / GOOGL
pair: AAPL.csv is the strategy asset and GOOGL.csv is the alternative
benchmark, so the run exercises a real 10-year window. Sweeps commission /
slippage across ascending levels from frictionless to 10bp comm + 5bp slip,
reporting per-criterion pass/fail and the verdict at each level. The
directional claim is that higher per-trade costs reduce net out-of-sample
performance; no profitability claim is made. Offline, committed fixtures only;
no live network.
"""
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from rsi_mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    COST_SWEEP_LEVELS,
    run_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_cost_sensitivity_runs_on_aapl_googl_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_cost_sweep(d / "sample_ohlcv.csv")

    assert isinstance(rows, list) and len(rows) == len(COST_SWEEP_LEVELS)
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    advertised = next(
        r for r in rows if r["commission_bps"] == COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )


if __name__ == "__main__":
    test_cost_sensitivity_runs_on_aapl_googl_real_window()
    print("OK")