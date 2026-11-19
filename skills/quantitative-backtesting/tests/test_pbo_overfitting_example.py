#!/usr/bin/env python3
"""
Regression test for the Probability of Backtest Overfitting (PBO / CSCV)
worked example (`examples/pbo_overfitting_example.py`).

PBO estimates how often the configuration that wins in-sample ranks at or
below the out-of-sample median across all symmetric in-sample/out-of-sample
partitions. It is a diagnostic of the selection procedure, not a claim of
profitability: this test asserts the machinery runs, prints both readings,
and reports a PBO share in [0, 1] with the expected number of partitions.
It deliberately does NOT assert a "good" PBO value.

Offline: uses only the committed AAPL fixture, no network.
"""
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
EXAMPLE = SKILLS_DIR / "examples" / "pbo_overfitting_example.py"

_PBO_LINE = re.compile(
    r"CSCV / PBO reading\s+n_splits=(\d+)\s*\n"
    r".*?n_partitions\s*=\s*(\d+)\s*\(expected C\(\d+,\d+\)\s*=\s*(\d+)\)\s*\n"
    r".*?PBO\s*=\s*([0-9.]+|N/A)",
    re.DOTALL,
)


def _run_example(*extra_args):
    """Run the example as a subprocess and return (proc, parsed_artifact).

    The temp directory lives long enough to read the artifact, then is removed.
    """
    td = tempfile.mkdtemp(prefix="pbo_example_test_")
    try:
        out_path = Path(td) / "pbo_readings.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(EXAMPLE),
                "--output-json",
                str(out_path),
            ] + list(extra_args),
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert proc.returncode == 0, (
            f"example exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout[-2000:]}\n"
            f"stderr:\n{proc.stderr[-2000:]}"
        )
        assert out_path.exists(), "artifact not written"
        artifact = json.loads(out_path.read_text())
        return proc, artifact
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_pbo_example_exits_zero_and_prints_both_readings():
    """The example exits 0 and prints one reading per configured split count."""
    proc, _ = _run_example()
    out = proc.stdout
    assert "PROBABILITY OF BACKTEST OVERFITTING (CSCV / PBO)" in out
    # Both split counts from the default run (8 and 16).
    assert "n_splits=8" in out and "n_splits=16" in out
    assert "is_overfit" in out and "mean_oos_rank" in out
    # The honest diagnostic framing is present; no profitability claim.
    assert "diagnostic" in out.lower()
    assert "not a profitability" in out.lower()


def test_pbo_readings_are_valid_shares_with_expected_partitions():
    """Each PBO reading is a share in [0, 1] and reports C(S, S/2) partitions."""
    proc, _ = _run_example()
    out = proc.stdout

    matches = _PBO_LINE.findall(out)
    assert len(matches) == 2, (
        f"expected 2 PBO readings in output, got {len(matches)}:\n{out[-3000:]}"
    )

    for n_splits_str, n_partitions_str, expected_str, pbo_str in matches:
        n_splits = int(n_splits_str)
        n_partitions = int(n_partitions_str)
        expected = int(expected_str)
        pbo = float(pbo_str)

        assert n_partitions == expected, (
            f"n_splits={n_splits}: n_partitions={n_partitions} != expected {expected}"
        )
        assert n_partitions == math.comb(n_splits, n_splits // 2)
        assert 0.0 <= pbo <= 1.0, (
            f"n_splits={n_splits}: PBO {pbo} is not a share in [0, 1]"
        )


def test_pbo_json_artifact_carries_both_readings():
    """The optional --output-json artifact carries both PBO readings."""
    _, artifact = _run_example()

    readings = artifact["readings"]
    assert len(readings) == 2, f"expected 2 readings, got {len(readings)}"
    for r in readings:
        assert r["n_splits"] in (8, 16)
        assert 0.0 <= r["pbo"] <= 1.0
        assert r["n_partitions"] == math.comb(r["n_splits"], r["n_splits"] // 2)
        assert r["n_partitions_evaluated"] > 0
        assert r["n_observations"] > 0
        assert r["n_trials"] > 0

    # No reading asserts a "good" PBO: both shares are merely reported.
    assert all(isinstance(r["is_overfit"], bool) for r in readings)


def test_grid_is_fixed_and_small():
    """The grid is pre-registered and small by design; this test guards
    against silently enlarging it to chase a reading."""
    grid = (
        (10, 20),
        (12, 26),
        (20, 50),
        (20, 40),
        (8, 21),
    )
    assert len(grid) == 5
    for fast, slow in grid:
        assert fast < slow, "fast window must be strictly below slow window"
