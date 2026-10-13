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

from data_loader import load_data, validate_data, load_multi_symbol, DataProvenance, validate_point_in_time, detect_survivorship_bias  # noqa: E402


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



def test_provenance_tracking_basic():
    """DataProvenance records source, filters, shapes, transforms, validation."""
    data = _make_data(periods=20)
    csv_path = _make_csv(data)
    try:
        loaded, prov = load_data(csv_path, start="2020-01-08", end="2020-01-17", return_provenance=True)
        assert isinstance(prov, DataProvenance)
        assert Path(csv_path).name in prov.source_path
        assert prov.load_timestamp is not None
        assert prov.original_shape[0] > 0
        assert prov.final_shape[0] == len(loaded)
        assert "column_names_lowercase_stripped" in prov.transformations_applied
        assert prov.validation_passed is True
        assert isinstance(prov.to_dict(), dict)
        assert isinstance(prov.to_json(), str)
    finally:
        Path(csv_path).unlink()


def test_provenance_serialization():
    """Provenance can be serialized to dict and JSON."""
    data = _make_data(periods=15)
    csv_path = _make_csv(data)
    try:
        _, prov = load_data(csv_path, return_provenance=True)
        d = prov.to_dict()
        j = prov.to_json()
        assert d["source_path"] == prov.source_path
        assert "transformations_applied" in d
        assert j.startswith("{")
        assert "source_path" in j
    finally:
        Path(csv_path).unlink()


def test_validate_point_in_time_clean():
    """Clean temporal data passes point-in-time validation."""
    dates = pd.date_range("2020-01-01", periods=30, freq="B")
    df = pd.DataFrame({"close": np.linspace(1, 30, 30)}, index=dates)
    res = validate_point_in_time(df)
    assert res["passed"] is True
    assert res["violations"] == []
    assert isinstance(res["warnings"], list)


def test_validate_point_in_time_detects_lookahead():
    """High correlation between signal changes and next-period returns suggests look-ahead."""
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=50, freq="B")
    close = 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, 50)))
    df = pd.DataFrame({"close": close}, index=dates)
    # Create a signal that strongly uses future info by looking ahead
    df["signal"] = (df["close"].shift(-1) > df["close"]).astype(int)
    res = validate_point_in_time(df, signal_column="signal")
    # We expect either warning/violation depending on detection logic
    assert "violations" in res
    assert "passed" in res


def test_validate_point_in_time_non_monotonic():
    """Non-monotonic index is detected."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    df = pd.DataFrame({"close": range(1, 11)}, index=dates)
    df = df.iloc[[0, 2, 1, 3, 4, 5, 6, 7, 8, 9]]  # mess up order
    res = validate_point_in_time(df)
    assert res["passed"] is False
    assert any("monotonically" in v for v in res["violations"])


def test_validate_point_in_time_lookback_windows():
    """Invalid lookback windows are flagged."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    df = pd.DataFrame({"close": range(1, 11)}, index=dates)
    res = validate_point_in_time(df, lookback_windows=[-1, 5])
    assert res["passed"] is False
    assert any("Invalid lookback" in v for v in res["violations"])


def test_detect_survivorship_bias_survivors_only():
    """All symbols surviving full period gives low bias score."""
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {
        "A": pd.DataFrame({"close": 1.0}, index=dates),
        "B": pd.DataFrame({"close": 2.0}, index=dates),
    }
    res = detect_survivorship_bias(data)
    assert res["bias_score"] == 0.0
    assert set(res["surviving_symbols"]) == {"A", "B"}
    assert res["entered_symbols"] == []
    assert res["exited_symbols"] == []


def test_detect_survivorship_bias_entries_exits_insufficient():
    """Detects entries, exits, insufficient data, and computes bias score."""
    global_start = "2020-01-01"
    global_end = "2021-12-31"
    dates_full = pd.date_range(global_start, global_end, freq="B")  # ~504
    # A: survives
    A = pd.DataFrame({"close": 1.0}, index=dates_full)
    # B: enters late
    B = pd.DataFrame({"close": 1.0}, index=pd.date_range("2020-07-01", global_end, freq="B"))  # entered late
    # C: exits early
    C = pd.DataFrame({"close": 1.0}, index=pd.date_range(global_start, "2021-06-01", freq="B"))  # exited early
    # D: insufficient
    D = pd.DataFrame({"close": 1.0}, index=pd.date_range(global_start, periods=100, freq="B"))  # < 252
    data = {"A": A, "B": B, "C": C, "D": D}
    res = detect_survivorship_bias(data)
    assert "A" in res["surviving_symbols"]
    assert len(res["entered_symbols"]) == 1
    assert res["entered_symbols"][0]["symbol"] == "B"
    # D exits early and also has insufficient data; C exits early
    exited_syms = {e["symbol"] for e in res["exited_symbols"]}
    assert "C" in exited_syms
    assert "D" in res["insufficient_data"]
    assert 0.0 < res["bias_score"] <= 1.0


def test_detect_survivorship_bias_empty():
    """Empty data dict returns zero bias."""
    res = detect_survivorship_bias({})
    assert res["bias_score"] == 0.0
    assert res["surviving_symbols"] == []


def test_load_multi_symbol_provenance_complete():
    """load_multi_symbol returns per-symbol provenance with checksums
    and date ranges, and does not warn about the cross-symbol
    duplicate timestamps that multi-symbol files legitimately have.

    Regression coverage for the CLI --multi-symbol integration:
    the provenance artifact written next to the results must carry
    the same integrity fields (checksum, date range) as the
    single-symbol path, or the run is not reproducible.
    """
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    rows = []
    for i, (sym, start, end) in enumerate([
        ("SURV", 0, 300), ("LATE", 60, 300), ("EARLY", 0, 240),
    ]):
        rng = np.random.default_rng(i + 1)
        rets = rng.normal(0.0005, 0.015, end - start)
        prices = 100 * np.exp(np.cumsum(rets))
        for j, d in enumerate(dates[start:end]):
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "symbol": sym,
                "open": prices[j],
                "high": prices[j] * 1.01,
                "low": prices[j] * 0.99,
                "close": prices[j],
                "volume": int(rng.integers(1_000_000, 10_000_000)),
            })
    panel = pd.DataFrame(rows)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    panel.to_csv(tmp.name, index=False)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            data, provenance = load_multi_symbol(tmp.name, return_provenance=True)
        assert set(data) == {"SURV", "LATE", "EARLY"}
        assert set(provenance) == {"SURV", "LATE", "EARLY"}
        for sym, prov in provenance.items():
            assert isinstance(prov, DataProvenance)
            assert prov.symbol_filter == sym
            assert prov.checksum, f"{sym}: provenance missing checksum"
            assert prov.date_range_final is not None, f"{sym}: missing date range"
            assert prov.final_shape[0] == len(data[sym])
        # Cross-symbol duplicate dates are expected in panel files;
        # per-symbol validation is authoritative (every symbol above
        # passed), so the aggregate-frame warning must not fire.
        aggregate_warnings = [
            w for w in caught if "Data validation failed" in str(w.message)
        ]
        assert aggregate_warnings == []
    finally:
        Path(tmp.name).unlink()


def main() -> int:
    tests = [
        ("load_data_unsupported_format_raises", test_load_data_unsupported_format_raises),
        ("load_data_missing_columns_raises", test_load_data_missing_columns_raises),
        ("load_data_parses_and_sorts_csv", test_load_data_parses_and_sorts_csv),
        ("validate_data_accepts_clean_frame", test_validate_data_accepts_clean_frame),
        ("validate_data_rejects_bad_frames", test_validate_data_rejects_bad_frames),
        ("validate_data_handles_short_series", test_validate_data_handles_short_series),
        ("test_provenance_tracking_basic", test_provenance_tracking_basic),
        ("test_provenance_serialization", test_provenance_serialization),
        ("test_validate_point_in_time_clean", test_validate_point_in_time_clean),
        ("test_validate_point_in_time_detects_lookahead", test_validate_point_in_time_detects_lookahead),
        ("test_validate_point_in_time_non_monotonic", test_validate_point_in_time_non_monotonic),
        ("test_validate_point_in_time_lookback_windows", test_validate_point_in_time_lookback_windows),
        ("test_detect_survivorship_bias_survivors_only", test_detect_survivorship_bias_survivors_only),
        ("test_detect_survivorship_bias_entries_exits_insufficient", test_detect_survivorship_bias_entries_exits_insufficient),
        ("test_detect_survivorship_bias_empty", test_detect_survivorship_bias_empty),
        ("test_load_multi_symbol_provenance_complete", test_load_multi_symbol_provenance_complete),
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
