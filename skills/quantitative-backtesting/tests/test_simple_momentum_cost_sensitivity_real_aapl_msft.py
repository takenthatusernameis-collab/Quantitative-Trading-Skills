#!/usr/bin/env python3
"""Cost sensitivity on the committed real-market AAPL/MSFT pair (SMA crossover).

Mirrors `test_simple_momentum_cost_sensitivity_sweep` but on committed real
fixtures instead of the synthetic sample: AAPL.csv is the strategy asset and
MSFT.csv is the alternative benchmark, so the run exercises a real 10-year
window with the Deflated Alpha Ratio live (two benchmarks => multiple-testing
correction engaged). Sweeps commission / slippage across five ascending levels
from frictionless to 10bp comm + 5bp slip and asserts the honest directional
claim: as per-trade costs rise, net out-of-sample Sharpe ratio, total return,
and Deflated Alpha Ratio all degrade monotonically. No profitability claim is
made; the verdict column is structural only. Offline, committed fixtures only;
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
ROOT_DIR = SKILLS_DIR.parent.parent

# Load the root script by path, not by name: the examples/ directory is also
# on sys.path and contains a sibling simple_momentum_hypothesis.py, so a bare
# import would pick up the thinner examples/ copy instead of the root script
# under test.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "root_simple_momentum_hypothesis", ROOT_DIR / "simple_momentum_hypothesis.py"
)
assert _spec is not None and _spec.loader is not None
smh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smh)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_cost_sensitivity_runs_on_aapl_msft_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "MSFT.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = smh.run_cost_sensitivity_sweep(d / "sample_ohlcv.csv")

    assert isinstance(rows, list) and len(rows) == len(smh.COST_SWEEP_LEVELS)
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in smh.COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None for v in values), (
            f"{label} is missing at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    advertised = next(
        r for r in rows if r["commission_bps"] == smh.COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )

    out = buffer.getvalue()
    assert "COST SENSITIVITY SWEEP" in out
    assert "Directional claim verified" in out


if __name__ == "__main__":
    test_cost_sensitivity_runs_on_aapl_msft_real_window()
    print("OK")