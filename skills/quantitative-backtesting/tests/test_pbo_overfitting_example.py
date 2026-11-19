#!/usr/bin/env python3
"""Regression test for the PBO overfitting example.

This test asserts that:
1. The example script exits with code 0
2. Both PBO readings (n_splits=8 and n_splits=16) are printed
3. Each PBO is in [0, 1]
4. n_partitions equals C(S, S/2) for both settings
5. The script does NOT assert a "good" PBO value (diagnostic only)
"""

import subprocess
import sys
from pathlib import Path
import math

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "pbo_overfitting_example.py"


def comb(n: int, k: int) -> int:
    """Binomial coefficient C(n, k)."""
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


def test_pbo_example_runs_and_reports():
    """Run the PBO example and verify its output structure."""
    result = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Assert exit code 0
    assert result.returncode == 0, f"Example failed with code {result.returncode}:\n{result.stderr}"

    stdout = result.stdout

    # Verify both PBO readings are printed
    assert "n_splits = 8" in stdout, "Missing n_splits=8 section"
    assert "n_splits = 16" in stdout, "Missing n_splits=16 section"
    assert "PBO (probability of overfit)" in stdout, "Missing PBO output"

    # Parse PBO values and n_partitions from output
    lines = stdout.split("\n")
    pbo_values = {}
    n_partitions_values = {}

    for i, line in enumerate(lines):
        if "PBO (probability of overfit)" in line:
            # Extract value
            parts = line.split(":")
            if len(parts) == 2:
                val = float(parts[1].strip())
                # Determine which n_splits this belongs to by looking back
                for j in range(i - 1, -1, -1):
                    if "n_splits = 8" in lines[j]:
                        pbo_values[8] = val
                        break
                    elif "n_splits = 16" in lines[j]:
                        pbo_values[16] = val
                        break
        if "n_partitions (C(S, S/2))" in line:
            parts = line.split(":")
            if len(parts) == 2:
                val = int(parts[1].strip())
                for j in range(i - 1, -1, -1):
                    if "n_splits = 8" in lines[j]:
                        n_partitions_values[8] = val
                        break
                    elif "n_splits = 16" in lines[j]:
                        n_partitions_values[16] = val
                        break

    # Assert both PBO values were found
    assert 8 in pbo_values, "PBO for n_splits=8 not found"
    assert 16 in pbo_values, "PBO for n_splits=16 not found"

    # Assert PBO in [0, 1]
    for n_splits in [8, 16]:
        pbo = pbo_values[n_splits]
        assert 0.0 <= pbo <= 1.0, f"PBO for n_splits={n_splits} = {pbo} not in [0, 1]"

    # Assert n_partitions equals C(S, S/2)
    assert n_partitions_values.get(8) == comb(8, 4), f"n_partitions for S=8: expected {comb(8, 4)}, got {n_partitions_values.get(8)}"
    assert n_partitions_values.get(16) == comb(16, 8), f"n_partitions for S=16: expected {comb(16, 8)}, got {n_partitions_values.get(16)}"

    # Assert diagnostic-only note is present (not a profitability claim)
    assert "DIAGNOSTIC ONLY" in stdout or "diagnostic" in stdout.lower(), "Missing diagnostic-only disclaimer"

    print("All assertions passed:")
    print(f"  PBO (S=8)  = {pbo_values[8]:.4f}, n_partitions = {n_partitions_values[8]} (expected {comb(8, 4)})")
    print(f"  PBO (S=16) = {pbo_values[16]:.4f}, n_partitions = {n_partitions_values[16]} (expected {comb(16, 8)})")


if __name__ == "__main__":
    test_pbo_example_runs_and_reports()
    print("Test passed!")