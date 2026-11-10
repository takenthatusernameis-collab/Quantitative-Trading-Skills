#!/usr/bin/env python3
"""
Focused unit tests for ``adjustment_integrity_guard`` in data_loader.py.

The guard verifies that ``adj_close`` is point-in-time consistent with raw
prices and the recorded split/dividend factors: no future information leaks
into the adjustment, and the adjustment is fully explained by the recorded
corporate actions.

Convention (matches ``_adjust_for_splits``): a split with ratio ``r`` at date
``k`` means the close on and after ``k`` is already at the post-split level,
so prices strictly before ``k`` are divided by ``r``.

Run with: python3 skills/quantitative-backtesting/tests/test_adjustment_integrity_guard.py
or via pytest. Uses only the standard library plus numpy/pandas.
"""

import numpy as np
import pandas as pd

SKILLS_DIR = None  # placeholder; imports resolved below
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from data_loader import adjustment_integrity_guard, load_data  # noqa: E402


def _make_adj_data(periods: int = 10, split_at: int = 5, ratio: float = 2.0,
                   seed: int = 7) -> pd.DataFrame:
    """Build OHLCV with ``adj_close`` consistent with the split convention.

    Close is at the post-split level on/after ``split_at`` and pre-split
    before it; ``adj_close`` is the continuous post-split series for all dates
    (pre-split values divided by ``r``).  This is exactly what
    ``_adjust_for_splits`` reproduces, so the guard must pass.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, periods)))

    close = close.copy()
    close[split_at:] = close[split_at:] / ratio  # post-split level on/after split

    adj_close = close.copy()
    adj_close[:split_at] = adj_close[:split_at] / ratio  # continuous post-split

    splits = np.ones(periods)
    splits[split_at] = ratio

    return pd.DataFrame(
        {
            "open": close * rng.uniform(0.995, 1.005, periods),
            "high": close * rng.uniform(1.005, 1.02, periods),
            "low": close * rng.uniform(0.98, 0.995, periods),
            "close": close,
            "adj_close": adj_close,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
            "splits": splits,
        },
        index=dates,
    )


def _assert_passed(result, label=""):
    assert result["passed"] is True, f"{label}: expected passed, got violations={result['violations']}"


def test_guard_no_adj_close_column_passes():
    """Without ``adj_close`` there is nothing to guard; passes with a warning."""
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=pd.date_range("2020-01-01", periods=3, freq="B"))
    result = adjustment_integrity_guard(df)
    assert result["passed"] is True
    assert len(result["violations"]) == 0
    assert len(result["warnings"]) >= 1


def test_guard_consistent_split_adjustment_passes():
    """adj_close built under the documented convention passes."""
    df = _make_adj_data()
    result = adjustment_integrity_guard(df)
    _assert_passed(result, "consistent split adjustment")


def test_guard_multiple_splits_consistent_passes():
    """Two accumulating splits with a consistent adj_close pass."""
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    close = pd.Series([300.0, 303.0, 150.0, 151.5, 50.0, 50.5], index=dates)
    adj_close = pd.Series([50.0, 50.5, 50.0, 50.5, 50.0, 50.5], index=dates)
    splits = pd.Series([1.0, 1.0, 2.0, 1.0, 3.0, 1.0], index=dates)
    df = pd.DataFrame(
        {"close": close, "adj_close": adj_close, "splits": splits,
         "open": close, "high": close, "low": close, "volume": [1_000_000] * 6},
        index=dates,
    )
    _assert_passed(adjustment_integrity_guard(df), "multiple splits")


def test_guard_no_splits_adj_close_equals_close_passes():
    """A splits column of all 1.0 with adj_close == close passes."""
    df = _make_adj_data(ratio=1.0)
    _assert_passed(adjustment_integrity_guard(df), "no actual splits")


def test_guard_corrupted_adj_close_fails():
    """adj_close replaced with noise is not reproducible from close+splits."""
    df = _make_adj_data()
    rng = np.random.default_rng(99)
    df["adj_close"] = df["close"] * rng.uniform(0.5, 1.5, len(df))
    result = adjustment_integrity_guard(df)
    assert result["passed"] is False
    assert any("not reproducible" in v for v in result["violations"]), result["violations"]


def test_guard_phantom_future_split_fails():
    """adj_close reflects a split that is not recorded in the splits column
    (future / phantom corporate action) -> fails reproducibility."""
    df = _make_adj_data(ratio=1.0)  # splits column all 1.0: no recorded split
    # Pretend a 2-for-1 happened at index 5: pre-split prices halved, but the
    # splits column does not record it -> unrecorded future adjustment.
    df.loc[df.index[:5], "adj_close"] = df.loc[df.index[:5], "close"] / 2.0
    result = adjustment_integrity_guard(df)
    assert result["passed"] is False
    assert any("not reproducible" in v for v in result["violations"]), result["violations"]


def test_guard_negative_split_fails():
    """A negative split ratio is a validity violation."""
    df = _make_adj_data()
    df.loc[df.index[5], "splits"] = -2.0
    result = adjustment_integrity_guard(df)
    assert result["passed"] is False
    assert any("negative" in v for v in result["violations"]), result["violations"]


def test_guard_negative_dividend_fails():
    """A negative dividend is a validity violation."""
    df = _make_adj_data()
    df["dividends"] = 0.0
    df.loc[df.index[3], "dividends"] = -0.5
    result = adjustment_integrity_guard(df)
    assert result["passed"] is False
    assert any("negative" in v for v in result["violations"]), result["violations"]


def test_guard_dividends_non_negative_pass():
    """Non-negative dividends do not by themselves fail the guard."""
    df = _make_adj_data()
    df["dividends"] = 0.0
    df.loc[df.index[3], "dividends"] = 0.5
    df.loc[df.index[7], "dividends"] = 0.25
    _assert_passed(adjustment_integrity_guard(df), "non-negative dividends")


def test_guard_wires_through_load_data_provenance():
    """load_data stores the guard result on the DataProvenance object."""
    df = _make_adj_data()
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    out = df.reset_index().rename(columns={"index": "date"})
    out.to_csv(tmp.name, index=False)
    try:
        _, prov = load_data(tmp.name, return_provenance=True)
        assert prov.adjustment_integrity is not None
        assert prov.adjustment_integrity["passed"] is True, prov.adjustment_integrity["violations"]
    finally:
        Path(tmp.name).unlink()


if __name__ == "__main__":
    tests = [
        test_guard_no_adj_close_column_passes,
        test_guard_consistent_split_adjustment_passes,
        test_guard_multiple_splits_consistent_passes,
        test_guard_no_splits_adj_close_equals_close_passes,
        test_guard_corrupted_adj_close_fails,
        test_guard_phantom_future_split_fails,
        test_guard_negative_split_fails,
        test_guard_negative_dividend_fails,
        test_guard_dividends_non_negative_pass,
        test_guard_wires_through_load_data_provenance,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
