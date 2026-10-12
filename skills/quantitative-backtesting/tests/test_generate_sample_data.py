#!/usr/bin/env python3
"""
Unit tests for generate_sample_data.py: sample data generation.

Run with: python3 skills/quantitative-backtesting/tests/test_generate_sample_data.py
Uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))


def test_generate_sample_data_creates_valid_file():
    """generate_sample_data writes a valid OHLCV CSV with expected shape."""
    tmpdir = tempfile.mkdtemp()
    out_path = Path(tmpdir) / "sample_ohlcv.csv"
    # execute the script logic with modified out path
    script_path = SKILLS_DIR / "scripts" / "generate_sample_data.py"
    code = script_path.read_text()
    # replace the out assignment
    code = code.replace('out = Path(__file__).parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"',
                        f'out = Path("{out_path}")')
    g = {"__name__": "__main__", "__file__": str(script_path)}
    try:
        exec(code, g)
        assert out_path.exists(), f"Expected file at {out_path}"
        df = pd.read_csv(out_path)
        assert len(df) == 504
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert (df["high"] >= df["low"]).all()
        assert (df["high"] >= df["close"]).all()
        assert (df["high"] >= df["open"]).all()
        assert (df["low"] <= df["close"]).all()
        assert (df["low"] <= df["open"]).all()
        assert (df["close"] > 0).all()
        assert (df["volume"] > 0).all()
    finally:
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass


def main() -> int:
    tests = [("generate_sample_data_creates_valid_file", test_generate_sample_data_creates_valid_file)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
