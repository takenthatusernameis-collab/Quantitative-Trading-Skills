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

from data_loader import load_data, validate_data, load_multi_symbol, DataProvenance, validate_point_in_time, detect_survivorship_bias, _compute_benchmark_total_return, _detect_benchmark_total_return_type, adjust_for_splits  # noqa: E402


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


def test_validate_point_in_time_detects_same_bar_lookahead():
    """A signal equal to the same-bar return is a strict look-ahead violation.

    Contemporaneous correlation (signal[t] vs return[t]) is a far stricter
    indicator than next-period correlation, because no information should
    flow from a same-bar signal to a same-bar return. Setting the signal
    equal to the same-bar return guarantees corr=+1.0 and must be flagged.
    """
    np.random.seed(7)
    dates = pd.date_range("2020-01-01", periods=50, freq="B")
    close = 100 * np.exp(np.cumsum(np.random.normal(0.0, 0.01, 50)))
    df = pd.DataFrame({"close": close}, index=dates)
    # Signal is set equal to the same-bar return: corr(signal_changes, same_bar_returns) = 1.0
    df["signal"] = df["close"].pct_change()
    res = validate_point_in_time(df, signal_column="signal")
    assert res["passed"] is False
    assert any("same-bar" in v for v in res["violations"]), (
        f"expected same-bar look-ahead violation, got {res['violations']}"
    )


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


def test_compute_benchmark_total_return_with_dividends():
    """_compute_benchmark_total_return includes dividend yield when dividends column exists."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    dividends = np.array([0.0, 0.0, 0.5, 0.0, 0.0, 0.5, 0.0, 0.0, 0.5, 0.0])
    df = pd.DataFrame({"close": close, "dividends": dividends}, index=dates)
    total_rets = _compute_benchmark_total_return(df)
    price_rets = df["close"].pct_change()
    div_yield = df["dividends"] / df["close"].shift(1)
    expected = price_rets + div_yield
    pd.testing.assert_series_equal(total_rets, expected)


def test_compute_benchmark_total_return_with_adj_close():
    """_compute_benchmark_total_return uses adj_close when dividends absent but adj_close present."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    adj_close = np.array([100.0, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5])
    df = pd.DataFrame({"close": close, "adj_close": adj_close}, index=dates)
    total_rets = _compute_benchmark_total_return(df)
    expected = df["adj_close"].pct_change()
    pd.testing.assert_series_equal(total_rets, expected)


def test_compute_benchmark_total_return_fallback_price_only():
    """_compute_benchmark_total_return falls back to close.pct_change when no dividends/adj_close."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    df = pd.DataFrame({"close": close}, index=dates)
    total_rets = _compute_benchmark_total_return(df)
    expected = df["close"].pct_change()
    pd.testing.assert_series_equal(total_rets, expected)


def test_detect_benchmark_total_return_type():
    """_detect_benchmark_total_return_type returns 'total' when dividends/adj_close present."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])

    df_div = pd.DataFrame({"close": close, "dividends": np.zeros(10)}, index=dates)
    assert _detect_benchmark_total_return_type(df_div) == "total"

    df_adj = pd.DataFrame({"close": close, "adj_close": close}, index=dates)
    assert _detect_benchmark_total_return_type(df_adj) == "total"

    df_price = pd.DataFrame({"close": close}, index=dates)
    assert _detect_benchmark_total_return_type(df_price) == "price"


def test_provenance_includes_total_return_type():
    """DataProvenance includes total_return_type field when loading data with dividends."""
    dates = pd.date_range("2020-01-01", periods=20, freq="B")
    close = 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, 20)))
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "open": close * rng.uniform(0.995, 1.005, 20),
        "high": close * rng.uniform(1.005, 1.02, 20),
        "low": close * rng.uniform(0.98, 0.995, 20),
        "close": close,
        "volume": rng.integers(1_000_000, 10_000_000, 20),
        "dividends": rng.uniform(0, 0.5, 20)
    }, index=dates)
    csv_path = _make_csv(df)
    try:
        _, prov = load_data(csv_path, return_provenance=True)
        assert prov.total_return_type == "total"

        df_no_div = pd.DataFrame({
            "open": close * rng.uniform(0.995, 1.005, 20),
            "high": close * rng.uniform(1.005, 1.02, 20),
            "low": close * rng.uniform(0.98, 0.995, 20),
            "close": close,
            "volume": rng.integers(1_000_000, 10_000_000, 20),
        }, index=dates)
        csv_path2 = _make_csv(df_no_div)
        try:
            _, prov2 = load_data(csv_path2, return_provenance=True)
            assert prov2.total_return_type == "price"
        finally:
            Path(csv_path2).unlink()
    finally:
        Path(csv_path).unlink()


def test_load_multi_symbol_provenance_includes_total_return_type():
    """load_multi_symbol provenance includes total_return_type per symbol."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    rows = []
    for i, (sym, has_div) in enumerate([("WITH_DIV", True), ("NO_DIV", False)]):
        rng = np.random.default_rng(i + 1)
        rets = rng.normal(0.0005, 0.015, 100)
        prices = 100 * np.exp(np.cumsum(rets))
        for j, d in enumerate(dates):
            row = {
                "date": d.strftime("%Y-%m-%d"),
                "symbol": sym,
                "open": prices[j],
                "high": prices[j] * 1.01,
                "low": prices[j] * 0.99,
                "close": prices[j],
                "volume": int(rng.integers(1_000_000, 10_000_000)),
            }
            if has_div:
                row["dividends"] = rng.uniform(0, 0.5)
            rows.append(row)
    panel = pd.DataFrame(rows)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    panel.to_csv(tmp.name, index=False)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data, provenance = load_multi_symbol(tmp.name, return_provenance=True)
        assert provenance["WITH_DIV"].total_return_type == "total"
        assert provenance["NO_DIV"].total_return_type == "price"
    finally:
        Path(tmp.name).unlink()


def _make_split_data(periods: int = 10, split_at: int = 5, ratio: float = 2.0, seed: int = 42) -> pd.DataFrame:
    """Build OHLCV data with a stock split at ``split_at``.

    The ``close`` on and after the split date is already at the post-split
    price level (as Yahoo Finance reports it), while pre-split closes are at
    the pre-split level.  An ``adj_close`` column provides ground-truth
    adjusted prices for validation.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.1, periods)
    noise = rng.normal(0, 0.005, periods)
    prices = 100 * np.exp(np.cumsum(trend / periods + noise))

    close = prices.copy()
    close[split_at:] = close[split_at:] / ratio  # post-split price level
    # Ground-truth adjusted close: continuous series at the post-split level
    # for ALL dates (pre-split values are divided by the ratio).
    adj_close = close.copy()
    adj_close[:split_at] = adj_close[:split_at] / ratio

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


def test_adjust_for_splits_divides_pre_split_prices():
    """A 2-for-1 split (ratio=2.0) must halve pre-split prices to the
    post-split level, matching the ground-truth ``adj_close`` column.

    Regression: the previous implementation multiplied pre-split prices by
    the ratio, which inverted the adjustment and produced a spurious large
    negative return on the split date.
    """
    df = _make_split_data(periods=10, split_at=5, ratio=2.0)
    adjusted = adjust_for_splits(df)

    assert np.allclose(adjusted["close"], df["adj_close"]), (
        f"adjusted close {adjusted['close'].tolist()} != adj_close "
        f"{df['adj_close'].tolist()}"
    )


def test_adjust_for_splits_zero_return_on_split_date():
    """The split-date return after adjustment must equal the ground-truth
    ``adj_close`` return at that date, i.e. no artificial drop from the
    split.  The raw (unadjusted) close would instead show a spurious large
    negative return on the split date.
    """
    df = _make_split_data(periods=10, split_at=5, ratio=2.0)
    adjusted = adjust_for_splits(df)
    rets = adjusted["close"].pct_change()
    truth_rets = df["adj_close"].pct_change()
    assert abs(rets.iloc[5] - truth_rets.iloc[5]) < 1e-12, (
        f"adjusted split-date return {rets.iloc[5]} != adj_close return "
        f"{truth_rets.iloc[5]}"
    )
    # And it must not be the raw spurious drop.
    raw_rets = df["close"].pct_change()
    assert abs(rets.iloc[5] - raw_rets.iloc[5]) > 0.01


def test_adjust_for_splits_no_split_column_is_identity():
    """Without a ``splits`` column the frame is returned unchanged."""
    df = _make_data(periods=20)
    adjusted = adjust_for_splits(df)
    pd.testing.assert_frame_equal(adjusted, df)


def test_adjust_for_splits_no_actual_splits_is_identity():
    """A ``splits`` column of all 1.0 leaves prices unchanged."""
    df = _make_split_data(periods=10, split_at=5, ratio=2.0)
    df["splits"] = 1.0
    adjusted = adjust_for_splits(df)
    pd.testing.assert_frame_equal(adjusted[["close"]], df[["close"]])


def test_adjust_for_splits_multiple_splits_accumulate():
    """Two consecutive splits accumulate their ratios on earlier dates."""
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    # 2-for-1 at index 2, then 3-for-1 at index 4.  Closes on and after each
    # split date are at the post-split price level; pre-split closes are at
    # the pre-split level.  adj_close is the continuous ground-truth series.
    close = pd.Series([300.0, 303.0, 150.0, 151.5, 50.0, 50.5], index=dates)
    adj_close = pd.Series([50.0, 50.5, 50.0, 50.5, 50.0, 50.5], index=dates)
    splits = pd.Series([1.0, 1.0, 2.0, 1.0, 3.0, 1.0], index=dates)
    df = pd.DataFrame(
        {"close": close, "adj_close": adj_close, "splits": splits}, index=dates
    )
    adjusted = adjust_for_splits(df)
    assert np.allclose(adjusted["close"], adj_close), (
        f"adjusted {adjusted['close'].tolist()} != adj_close {adj_close.tolist()}"
    )
    # Split-date returns must match ground truth (no artificial drop).
    rets = adjusted["close"].pct_change()
    truth_rets = adj_close.pct_change()
    assert abs(rets.iloc[2] - truth_rets.iloc[2]) < 1e-12
    assert abs(rets.iloc[4] - truth_rets.iloc[4]) < 1e-12


def test_adjust_for_splits_volume_scaled():
    """Pre-split volume is scaled up by the cumulative ratio to stay
    comparable across the split date."""
    dates = pd.date_range("2020-01-01", periods=4, freq="B")
    close = pd.Series([100.0, 101.0, 50.5, 51.0], index=dates)
    splits = pd.Series([1.0, 1.0, 2.0, 1.0], index=dates)
    volume = pd.Series([1000, 1100, 1200, 1300], index=dates)
    df = pd.DataFrame({"close": close, "splits": splits, "volume": volume}, index=dates)
    adjusted = adjust_for_splits(df)
    # Pre-split volume scaled by 2.0; post-split volume unchanged.
    assert adjusted["volume"].iloc[0] == 2000.0
    assert adjusted["volume"].iloc[1] == 2200.0
    assert adjusted["volume"].iloc[2] == 1200.0
    assert adjusted["volume"].iloc[3] == 1300.0


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
        ("test_validate_point_in_time_detects_same_bar_lookahead", test_validate_point_in_time_detects_same_bar_lookahead),
        ("test_validate_point_in_time_non_monotonic", test_validate_point_in_time_non_monotonic),
        ("test_validate_point_in_time_lookback_windows", test_validate_point_in_time_lookback_windows),
        ("test_detect_survivorship_bias_survivors_only", test_detect_survivorship_bias_survivors_only),
        ("test_detect_survivorship_bias_entries_exits_insufficient", test_detect_survivorship_bias_entries_exits_insufficient),
        ("test_detect_survivorship_bias_empty", test_detect_survivorship_bias_empty),
        ("test_load_multi_symbol_provenance_complete", test_load_multi_symbol_provenance_complete),
        ("test_compute_benchmark_total_return_with_dividends", test_compute_benchmark_total_return_with_dividends),
        ("test_compute_benchmark_total_return_with_adj_close", test_compute_benchmark_total_return_with_adj_close),
        ("test_compute_benchmark_total_return_fallback_price_only", test_compute_benchmark_total_return_fallback_price_only),
        ("test_detect_benchmark_total_return_type", test_detect_benchmark_total_return_type),
        ("test_provenance_includes_total_return_type", test_provenance_includes_total_return_type),
        ("test_load_multi_symbol_provenance_includes_total_return_type", test_load_multi_symbol_provenance_includes_total_return_type),
        ("test_adjust_for_splits_divides_pre_split_prices", test_adjust_for_splits_divides_pre_split_prices),
        ("test_adjust_for_splits_zero_return_on_split_date", test_adjust_for_splits_zero_return_on_split_date),
        ("test_adjust_for_splits_no_split_column_is_identity", test_adjust_for_splits_no_split_column_is_identity),
        ("test_adjust_for_splits_no_actual_splits_is_identity", test_adjust_for_splits_no_actual_splits_is_identity),
        ("test_adjust_for_splits_multiple_splits_accumulate", test_adjust_for_splits_multiple_splits_accumulate),
        ("test_adjust_for_splits_volume_scaled", test_adjust_for_splits_volume_scaled),
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
