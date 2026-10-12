#!/usr/bin/env python3
"""
Unit tests for data_loader.py: loading, format validation, and data quality.

Run with: python3 skills/quantitative-backtesting/tests/test_data_loader.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import tempfile
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_data, validate_data  # noqa: E402


def _make_data(periods: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        },
        index=dates,
    )


def _make_csv(df: pd.DataFrame, with_date_column: bool = True) -> str:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    out = df.copy()
    if with_date_column:
        out = out.reset_index().rename(columns={"index": "date"})
    out.to_csv(tmp.name, index=not with_date_column)
    return tmp.name


def test_load_data_unsupported_format_raises():
    """Non-CSV/Parquet files must raise a descriptive ValueError."""
    try:
        load_data("data.txt")
        assert False, "Expected ValueError for unsupported format"
    except ValueError as e:
        assert "Unsupported file format" in str(e), f"unexpected message: {e}"


def test_load_data_missing_columns_raises():
    """Files without the required OHLCV columns must raise."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    pd.DataFrame({"date": dates, "close": [1.0, 2.0, 3.0, 4.0, 5.0]}).to_csv(
        tmp.name, index=False
    )
    try:
        load_data(tmp.name)
        assert False, "Expected ValueError for missing columns"
    except ValueError as e:
        assert "Missing required columns" in str(e), f"unexpected message: {e}"
    finally:
        Path(tmp.name).unlink()


def test_load_data_parses_and_sorts_csv():
    """CSV loading yields a sorted DatetimeIndex and clean columns."""
    data = _make_data(periods=10)
    shuffled = data.iloc[::-1]  # reverse row order; loader must sort
    csv_path = _make_csv(shuffled)
    try:
        loaded = load_data(csv_path)
        assert isinstance(loaded.index, pd.DatetimeIndex)
        assert loaded.index.is_monotonic_increasing, "index not sorted"
        assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]
        assert len(loaded) == 10
    finally:
        Path(csv_path).unlink()


def test_validate_data_accepts_clean_frame():
    """A clean OHLCV frame passes validation."""
    assert validate_data(_make_data()) is True


def test_validate_data_rejects_bad_frames():
    """Non-positive prices and high < low must fail validation."""
    bad_close = _make_data(periods=10)
    bad_close.loc[bad_close.index[0], "close"] = -1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert validate_data(bad_close) is False

    bad_range = _make_data(periods=10)
    bad_range.loc[bad_range.index[0], "high"] = 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert validate_data(bad_range) is False


def test_validate_data_handles_short_series():
    """Frames with too few rows to infer frequency must not crash."""
    short = _make_data(periods=2)
    assert validate_data(short) is True


def main() -> int:
    tests = [
        ("load_data_unsupported_format_raises", test_load_data_unsupported_format_raises),
        ("load_data_missing_columns_raises", test_load_data_missing_columns_raises),
        ("load_data_parses_and_sorts_csv", test_load_data_parses_and_sorts_csv),
        ("validate_data_accepts_clean_frame", test_validate_data_accepts_clean_frame),
        ("validate_data_rejects_bad_frames", test_validate_data_rejects_bad_frames),
        ("validate_data_handles_short_series", test_validate_data_handles_short_series),
    ]

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
