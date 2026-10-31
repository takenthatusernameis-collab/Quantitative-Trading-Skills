#!/usr/bin/env python3
"""Falsifiable hypothesis test on the committed real-market MSFT/GOOGL pair (SMA).

Mirrors `test_simple_momentum_hypothesis_example_runs_successfully` but on
committed real fixtures instead of the synthetic sample: MSFT.csv is the
strategy asset and GOOGL.csv is the alternative benchmark, so the run exercises
a real 10-year window with the Deflated Alpha Ratio live (two benchmarks =>
multiple-testing correction engaged) and the capacity control live. Asserts
structural invariants only -- verdict in {"SUPPORTED","NOT SUPPORTED"},
criteria/`all_pass` consistency, chronological + disjoint split, point-in-time
validation, and the presence of the VERDICT banner. The verdict is recorded as
falsification evidence and is never asserted SUPPORTED as a profitability
claim. Offline, committed fixtures only; no live network.
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
    "root_simple_momentum_hypothesis_hyp", ROOT_DIR / "simple_momentum_hypothesis.py"
)
assert _spec is not None and _spec.loader is not None
smh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smh)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

EXPECTED_CRITERION_NAMES = {c[0] for c in smh.CRITERIA}


def test_hypothesis_runs_on_msft_googl_real_window():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = smh.run_hypothesis_test(d / "sample_ohlcv.csv")

    assert isinstance(result, dict)
    assert result["hypothesis"] == smh.HYPOTHESIS
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] == all(
        c["passed"] for c in result["criteria"]
    ), "all_pass must equal the conjunction of per-criterion pass flags"
    assert result["verdict"] == (
        "SUPPORTED" if result["all_pass"] else "NOT SUPPORTED"
    ), "verdict must be the derived consequence of all_pass"
    assert len(result["criteria"]) == len(smh.CRITERIA)
    assert {c["name"] for c in result["criteria"]} == EXPECTED_CRITERION_NAMES
    for c in result["criteria"]:
        assert isinstance(c["passed"], bool)
        assert c["description"]

    out = buffer.getvalue()
    assert "FALSIFIABLE HYPOTHESIS TEST" in out
    assert "VERDICT:" in out
    assert "SUPPORTED" in out or "NOT SUPPORTED" in out
    # Methodology controls reported on the real run.
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out


if __name__ == "__main__":
    test_hypothesis_runs_on_msft_googl_real_window()
    print("OK")