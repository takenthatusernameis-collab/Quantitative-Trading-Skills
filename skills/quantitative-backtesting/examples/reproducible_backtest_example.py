#!/usr/bin/env python3
"""Reproducible worked example: regenerate a metrics artifact from a committed
tiny CSV fixture using the data_loader / run_backtest.py path.

Run twice; the resulting metrics.json must be byte-identical (see
tests/test_reproducible_backtest_example.py).
"""

import subprocess
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
OUTPUT = SKILLS_DIR / "examples" / "example_reproducible_output"

def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SKILLS_DIR / "scripts" / "run_backtest.py"),
        "--data", str(DATA),
        "--strategy", "sma_crossover",
        "--symbol", "SPY",
        "--output", str(OUTPUT),
        "--validate-point-in-time",
        "--point-in-time-strict",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode
    import json
    summary = json.loads((OUTPUT / "tear_sheet_summary.json").read_text())
    pit = summary.get("point_in_time_validation")
    if not pit or not pit.get("passed", False):
        print("point-in-time validation did not pass", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
