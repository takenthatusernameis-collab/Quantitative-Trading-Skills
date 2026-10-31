#!/usr/bin/env python3
"""Capacity sensitivity on the committed real-market AAPL/GOOGL pair (SMA).

Mirrors `test_root_capacity_sensitivity_sweep_falls_with_impact` but on
committed real fixtures instead of the synthetic sample: AAPL.csv is the
strategy asset and GOOGL.csv is the alternative benchmark, so the run exercises
a real 10-year window. Sweeps the market-impact coefficient across ascending
levels and asserts the honest directional claim: as market impact rises,
estimated strategy capacity falls (capacity ~ 1/impact_coefficient). The
impact-disabled level reports capacity=None. No profitability claim is made;
capacity is an execution-side control, not a return forecast. Offline,
committed fixtures only; no live network.
"""
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = SKILLS_DIR.parent.parent

# Load the root script by path, not by name: the examples/ directory is also
# on sys.path and contains a sibling simple_momentum_hypothesis.py, so a bare
# import would pick up the thinner examples/ copy instead of the root script
# under test.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "root_simple_momentum_hypothesis_cap", ROOT_DIR / "simple_momentum_hypothesis.py"
)
assert _spec is not None and _spec.loader is not None
smh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smh)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_capacity_sensitivity_runs_on_aapl_googl_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = smh.run_capacity_sensitivity_sweep(d / "sample_ohlcv.csv")

    assert len(rows) == len(smh.CAPACITY_SENSITIVITY_LEVELS)
    assert [r["impact_coefficient"] for r in rows] == list(
        smh.CAPACITY_SENSITIVITY_LEVELS
    ), "capacity sensitivity levels are not recorded in ascending order"
    assert rows[0]["impact_coefficient"] == 0.0, (
        "first capacity sensitivity level must be impact disabled"
    )
    assert rows[0]["capacity"] is None, (
        "impact-disabled setting must report capacity=None, got "
        f"{rows[0]['capacity']}"
    )

    finite = [r for r in rows if r["capacity"] is not None]
    assert len(finite) >= 2, (
        "capacity sensitivity sweep must produce at least two finite readings"
    )
    for r in finite:
        assert float(r["capacity"]) > 0, (
            "capacity estimate must be positive: " f"{r['capacity']}"
        )
    for prev, curr in zip(finite, finite[1:]):
        assert curr["capacity"] < prev["capacity"], (
            "capacity does not fall as market impact rises: "
            f"impact {prev['impact_coefficient']} -> {prev['capacity']:,.0f}, "
            f"impact {curr['impact_coefficient']} -> {curr['capacity']:,.0f}"
        )

    out = buffer.getvalue()
    assert "CAPACITY SENSITIVITY SWEEP" in out
    assert "Capacity falls with market impact" in out


if __name__ == "__main__":
    test_capacity_sensitivity_runs_on_aapl_googl_real_window()
    print("OK")