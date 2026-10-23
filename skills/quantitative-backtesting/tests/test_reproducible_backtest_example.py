#!/usr/bin/env python3
"""Regression test: reproducible backtest example regenerates byte-identical metrics."""

import hashlib
import subprocess
import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
EXAMPLE = SKILLS_DIR / "examples" / "reproducible_backtest_example.py"
METRICS = SKILLS_DIR / "examples" / "example_reproducible_output" / "metrics.json"

TEST_REGISTRY = []

def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_reproducible_metrics_byte_identical():
    r1 = subprocess.run([sys.executable, str(EXAMPLE)], capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    h1 = _hash(METRICS)
    r2 = subprocess.run([sys.executable, str(EXAMPLE)], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    h2 = _hash(METRICS)
    assert h1 == h2, f"metrics changed between runs: {h1} vs {h2}"
    assert METRICS.exists()

TEST_REGISTRY.append(("reproducible_metrics_byte_identical", test_reproducible_metrics_byte_identical))

def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
