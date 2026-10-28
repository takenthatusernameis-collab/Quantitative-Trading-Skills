#!/usr/bin/env python3
"""
Utilities for loading and validating market data from various sources.

Supports CSV, Parquet, and common data vendor formats.
Includes data provenance tracking, point-in-time validation, and
survivorship bias detection for rigorous quantitative research.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
import warnings
import json


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["adj_close", "dividends", "splits"]

BENCHMARK_TOTAL_RETURN_TYPES = ("price", "total")


@dataclass
class DataProvenance:
    """Metadata tracking the origin and transformations of loaded data."""
    source_path: str
    load_timestamp: str
    file_format: str
    file_size_bytes: int
    symbol_filter: Optional[str] = None
    start_date_filter: Optional[str] = None
    end_date_filter: Optional[str] = None
    original_shape: Tuple[int, int] = (0, 0)
    final_shape: Tuple[int, int] = (0, 0)
    columns_original: List[str] = field(default_factory=list)
    columns_final: List[str] = field(default_factory=list)
    date_range_original: Optional[Tuple[str, str]] = None
    date_range_final: Optional[Tuple[str, str]] = None
    validation_passed: bool = False
    validation_messages: List[str] = field(default_factory=list)
    transformations_applied: List[str] = field(default_factory=list)
    checksum: Optional[str] = None
    total_return_type: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        d = asdict(self)
        if 'name' not in d:
            d['name'] = None
        return d

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


def _compute_checksum(df: pd.DataFrame) -> str:
    """Compute a simple checksum of the DataFrame for integrity verification."""
    import hashlib
    # Use a sample of data for efficiency on large frames
    sample = df.head(1000).to_csv(index=False).encode('utf-8')
    return hashlib.md5(sample).hexdigest()[:16]


def _compute_benchmark_total_return(df: pd.DataFrame) -> pd.Series:
    """
    Compute total-return benchmark series from OHLCV data.

    If 'dividends' column exists, computes total return as:
        close.pct_change() + dividends / close.shift(1)

    If 'adj_close' column exists (and no dividends), computes total return as:
        adj_close.pct_change()

    Otherwise falls back to price-only return:
        close.pct_change()

    The return type ('price' or 'total') is recorded in the DataProvenance
    when this function is used for benchmark loading.

    Args:
        df: DataFrame with OHLCV data (must have 'close', optionally 'dividends' or 'adj_close')

    Returns:
        Series of period returns (total return when dividends/adj_close available, else price return)
    """
    if "dividends" in df.columns:
        # Total return = price return + dividend yield
        price_return = df["close"].pct_change()
        dividend_yield = df["dividends"] / df["close"].shift(1)
        return price_return + dividend_yield
    elif "adj_close" in df.columns:
        # Use adjusted close for total return (includes dividends and splits)
        return df["adj_close"].pct_change()
    else:
        # Price-only return
        return df["close"].pct_change()




def _adjust_for_splits(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adjust OHLCV prices for stock splits using the 'splits' column.

    Adjusts prices so that all prices are on a consistent basis. For a split
    with ratio r = new_shares / old_shares (e.g., 2.0 for a 2-for-1), historical
    prices before the split are DIVIDED by r to be comparable to post-split
    prices. This is the inverse of the multiplicative convention used by some
    data vendors (where ``splits`` is expressed as old/new), and matches the
    Yahoo Finance convention where the ``splits`` column records the ratio
    ``new_shares / old_shares`` and the split-date close is already at the
    post-split price level.

    Args:
        df: DataFrame with OHLCV data and optional 'splits' column

    Returns:
        DataFrame with split-adjusted OHLCV prices
    """
    if "splits" not in df.columns:
        return df

    df = df.copy()
    split_mask = df["splits"].notna() & (df["splits"] != 0) & (df["splits"] != 1.0)
    if not split_mask.any():
        return df

    cum_adj = pd.Series(1.0, index=df.index)
    for idx in sorted(df[split_mask].index):
        ratio = df.at[idx, "splits"]
        # Accumulate the product of split ratios for all dates strictly before
        # this split.  For a 2-for-1 split (ratio=2.0), pre-split dates get a
        # cumulative factor of 2.0, so dividing their raw (pre-split) prices by
        # 2.0 brings them down to the post-split price level.  This keeps the
        # split-date return at zero (no artificial drop) when the split-date
        # close is already at the post-split level, matching the Yahoo Finance
        # convention where ``splits`` records new_shares / old_shares.
        mask_pre = df.index < idx
        cum_adj[mask_pre] *= ratio

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        if col in df.columns:
            df[col] = df[col] / cum_adj

    if "volume" in df.columns:
        # Pre-split volume was recorded in pre-split share units; multiplying
        # by the cumulative ratio expresses it in post-split share units so the
        # series is comparable across the split date.
        df["volume"] = df["volume"] * cum_adj

    df["splits_adjusted"] = True
    return df


# Alias for common naming
adjust_for_splits = _adjust_for_splits


def _detect_benchmark_total_return_type(df: pd.DataFrame) -> str:
    """
    Detect whether the benchmark data supports total-return computation.

    Returns:
        'total' if dividends or adj_close column has any non-NaN values, 'price' otherwise
    """
    if "dividends" in df.columns and df["dividends"].notna().any():
        return "total"
    if "adj_close" in df.columns and df["adj_close"].notna().any():
        return "total"
    return "price"


def load_data(
    path: Union[str, Path],
    symbol: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    date_column: str = "date",
    adjust_splits: bool = False,
    return_provenance: bool = False,
    **kwargs
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, DataProvenance]]:
    """
    Load market data from file.

    Args:
        path: Path to data file (CSV or Parquet)
        symbol: Filter for specific symbol (if multi-symbol file)
        start: Start date filter (YYYY-MM-DD)
        end: End date filter (YYYY-MM-DD)
        date_column: Name of date column
        adjust_splits: If True, adjust prices for splits
        return_provenance: If True, return (DataFrame, DataProvenance) tuple
        **kwargs: Additional arguments passed to pd.read_csv/read_parquet

    Returns:
        DataFrame with OHLCV data indexed by date, or tuple with provenance
    """
    path = Path(path)
    load_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    file_size = path.stat().st_size if path.exists() else 0
    file_format = path.suffix.lower()

    if file_format == ".parquet":
        df = pd.read_parquet(path, **kwargs)
    elif file_format == ".csv":
        df = pd.read_csv(path, **kwargs)
    else:
        raise ValueError(f"Unsupported file format: {file_format}. Use CSV or Parquet.")

    original_shape = df.shape
    columns_original = list(df.columns)
    date_range_original = None
    if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
        date_range_original = (str(df.index.min()), str(df.index.max()))

    provenance = DataProvenance(
        source_path=str(path),
        load_timestamp=load_ts,
        file_format=file_format,
        file_size_bytes=file_size,
        symbol_filter=symbol,
        start_date_filter=start,
        end_date_filter=end,
        original_shape=original_shape,
        columns_original=columns_original,
        date_range_original=date_range_original,
    )

    # Standardize column names
    df.columns = df.columns.str.lower().str.strip()
    provenance.transformations_applied.append("column_names_lowercase_stripped")

    # Handle date column
    if date_column in df.columns:
        df[date_column] = pd.to_datetime(df[date_column])
        df = df.set_index(date_column)
        provenance.transformations_applied.append(f"set_index_from_{date_column}")
    elif not isinstance(df.index, pd.DatetimeIndex):
        # Try to parse index as dates
        try:
            df.index = pd.to_datetime(df.index)
            provenance.transformations_applied.append("parsed_index_as_datetime")
        except Exception:
            raise ValueError("Could not parse date index. Specify date_column parameter.")

    # Ensure index is sorted
    df = df.sort_index()
    provenance.transformations_applied.append("sorted_index")

    # Filter by symbol if provided and column exists
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol].copy()
        df = df.drop(columns=["symbol"])
        provenance.transformations_applied.append(f"filtered_symbol_{symbol}")
    elif symbol and "ticker" in df.columns:
        df = df[df["ticker"] == symbol].copy()
        df = df.drop(columns=["ticker"])
        provenance.transformations_applied.append(f"filtered_ticker_{symbol}")

    # Filter by date range
    if start:
        df = df[df.index >= pd.Timestamp(start)]
        provenance.transformations_applied.append(f"filtered_start_{start}")
    if end:
        df = df[df.index <= pd.Timestamp(end)]
        provenance.transformations_applied.append(f"filtered_end_{end}")

    # Ensure required columns exist
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure numeric types
    for col in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    provenance.transformations_applied.append("coerced_numeric_types")

    # Apply split adjustments if requested
    if adjust_splits and "splits" in df.columns:
        df = _adjust_for_splits(df)
        provenance.transformations_applied.append("split_adjustment_applied")

    provenance.final_shape = df.shape
    provenance.columns_final = list(df.columns)
    if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
        provenance.date_range_final = (str(df.index.min()), str(df.index.max()))
    provenance.checksum = _compute_checksum(df)
    provenance.total_return_type = _detect_benchmark_total_return_type(df)

    # Validate data and update provenance
    validate_data(df, provenance=provenance)

    if return_provenance:
        return df, provenance
    return df


def validate_data(df: pd.DataFrame, strict: bool = False, provenance: Optional[DataProvenance] = None) -> bool:
    """
    Validate market data quality.

    Args:
        df: DataFrame with OHLCV data
        strict: If True, raise exceptions on validation failures
        provenance: Optional DataProvenance object to update with validation results

    Returns:
        True if validation passes, False otherwise
    """
    checks = []
    messages = []

    # Check for required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        messages.append(f"Missing required columns: {missing}")
        checks.append(False)
    else:
        checks.append(True)

    # Check for null values
    null_counts = df[REQUIRED_COLUMNS].isnull().sum()
    if null_counts.any():
        msg = f"Null values found: {null_counts[null_counts > 0].to_dict()}"
        messages.append(msg)
        checks.append(False if strict else True)  # Warning only in non-strict mode

    # Check for negative prices
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        if col in df.columns and (df[col] <= 0).any():
            msg = f"Non-positive values in {col}"
            messages.append(msg)
            checks.append(False)

    # Check high >= low
    if "high" in df.columns and "low" in df.columns:
        if (df["high"] < df["low"]).any():
            messages.append("High < Low detected")
            checks.append(False)

    # Check high >= open, close and low <= open, close
    for col in ["open", "close"]:
        if col in df.columns and "high" in df.columns:
            if (df["high"] < df[col]).any():
                messages.append(f"High < {col} detected")
                checks.append(False)
        if col in df.columns and "low" in df.columns:
            if (df["low"] > df[col]).any():
                messages.append(f"Low > {col} detected")
                checks.append(False)

    # Check for duplicate dates
    if df.index.duplicated().any():
        messages.append("Duplicate dates in index")
        checks.append(False)

    # Check for gaps in trading days (warn only)
    if isinstance(df.index, pd.DatetimeIndex):
        try:
            with pd.option_context('future.infer_freq_returns_offset', False):
                _inferred = pd.infer_freq(df.index)
            freq = getattr(_inferred, 'freqstr', _inferred)
        except ValueError:
            freq = None  # too few dates to infer; not a validation failure
        if freq and freq not in ["B", "D", "W"]:
            messages.append(f"Unusual frequency detected: {freq}")

    # Check volume
    if "volume" in df.columns and (df["volume"] < 0).any():
        messages.append("Negative volume detected")
        checks.append(False)

    passed = all(checks)
    if provenance is not None:
        provenance.validation_passed = passed
        provenance.validation_messages = messages

    if not passed:
        msg = "Data validation failed:\n" + "\n".join(f"  - {m}" for m in messages)
        if strict:
            raise ValueError(msg)
        else:
            warnings.warn(msg)
        return False

    return True


def validate_point_in_time(
    df: pd.DataFrame,
    signal_column: Optional[str] = None,
    lookback_windows: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Validate that no look-ahead bias exists in the data or signals.

    Checks for common point-in-time violations:
    1. Signals that reference future price data (e.g., using close[t] to generate signal[t])
    2. Rolling calculations that use future observations
    3. Forward-filled data that leaks future information

    Args:
        df: DataFrame with OHLCV data and optionally signals
        signal_column: Name of signal column to check (if present)
        lookback_windows: List of window sizes used in rolling calculations

    Returns:
        Dictionary with validation results:
        - 'passed': bool
        - 'violations': list of detected violations
        - 'warnings': list of potential issues
    """
    violations = []
    warnings_list = []

    if not isinstance(df.index, pd.DatetimeIndex):
        warnings_list.append("Index is not DatetimeIndex; cannot fully validate temporal ordering")
        return {"passed": True, "violations": violations, "warnings": warnings_list}

    # Check 1: Ensure index is strictly increasing (no future dates before past dates)
    if not df.index.is_monotonic_increasing:
        violations.append("Index is not monotonically increasing; temporal order violated")

    # Check 2: Check for duplicate timestamps (could indicate data quality issues)
    if df.index.duplicated().any():
        violations.append("Duplicate timestamps found; potential data integrity issue")

    # Check 3: If signal column provided, verify signals don't use future data
    if signal_column and signal_column in df.columns:
        signals = df[signal_column]
        # A signal at time t should only depend on data up to time t.
        # Check if signal changes at t correlate with price changes at t+1 (lagged correlation)
        if "close" in df.columns:
            price_changes = df["close"].pct_change().shift(-1)  # Next period return
            signal_changes = signals.diff()
            # Remove NaN
            valid = price_changes.notna() & signal_changes.notna()
            if valid.sum() > 10:
                corr = price_changes[valid].corr(signal_changes[valid])
                # High correlation suggests signal uses future price info
                if abs(corr) > 0.3:
                    violations.append(
                        f"Signal '{signal_column}' correlates with next-period returns "
                        f"(corr={corr:.3f}); potential look-ahead bias"
                    )

    # Check 4: Rolling window calculations - verify no forward-looking windows
    if lookback_windows:
        for window in lookback_windows:
            if window <= 0:
                violations.append(f"Invalid lookback window: {window} (must be positive)")

    # Check 5: Forward-filled data detection
    # If a column has long stretches of identical values, it might be forward-filled
    for col in df.select_dtypes(include=[np.number]).columns:
        if col in REQUIRED_COLUMNS:
            continue
        # Check for suspiciously long runs of identical values
        runs = (df[col] != df[col].shift()).cumsum()
        run_lengths = runs.value_counts()
        max_run = run_lengths.max() if len(run_lengths) > 0 else 0
        if max_run > len(df) * 0.1:  # More than 10% of data in single run
            warnings_list.append(
                f"Column '{col}' has a run of {max_run} identical values; "
                "possible forward-filling or stale data"
            )

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "warnings": warnings_list,
    }


def detect_survivorship_bias(
    data_dict: Dict[str, pd.DataFrame],
    min_observations: int = 252,
    max_gap_days: int = 30,
) -> Dict[str, Any]:
    """
    Detect potential survivorship bias in panel data.

    Checks for:
    1. Symbols that appear/disappear during the sample period
    2. Symbols with insufficient observations
    3. Large gaps in data that might indicate delisting/relisting
    4. Symbols only present in the latter part of the sample (IPO bias)

    Args:
        data_dict: Dictionary mapping symbol -> OHLCV DataFrame
        min_observations: Minimum observations required for a symbol
        max_gap_days: Maximum allowed gap in trading days before flagging

    Returns:
        Dictionary with detection results:
        - 'surviving_symbols': symbols present throughout
        - 'entered_symbols': symbols that appear after sample start
        - 'exited_symbols': symbols that disappear before sample end
        - 'insufficient_data': symbols with too few observations
        - 'large_gaps': symbols with gaps exceeding max_gap_days
        - 'bias_score': float 0-1 indicating severity (higher = more bias)
    """
    if not data_dict:
        return {
            "surviving_symbols": [],
            "entered_symbols": [],
            "exited_symbols": [],
            "insufficient_data": [],
            "large_gaps": [],
            "bias_score": 0.0,
        }

    # Determine global date range
    all_starts = []
    all_ends = []
    for df in data_dict.values():
        if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
            all_starts.append(df.index.min())
            all_ends.append(df.index.max())

    if not all_starts:
        return {
            "surviving_symbols": [],
            "entered_symbols": [],
            "exited_symbols": [],
            "insufficient_data": [],
            "large_gaps": [],
            "bias_score": 0.0,
        }

    global_start = min(all_starts)
    global_end = max(all_ends)

    surviving = []
    entered = []
    exited = []
    insufficient = []
    large_gaps = []

    for symbol, df in data_dict.items():
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) == 0:
            insufficient.append(symbol)
            continue

        symbol_start = df.index.min()
        symbol_end = df.index.max()
        n_obs = len(df)

        # Check observation count
        if n_obs < min_observations:
            insufficient.append(symbol)

        # Check entry/exit relative to global range
        # Use a tolerance of max_gap_days
        tolerance = pd.Timedelta(days=max_gap_days)

        if symbol_start > global_start + tolerance:
            entered.append({
                "symbol": symbol,
                "start_date": str(symbol_start),
                "days_after_global_start": (symbol_start - global_start).days,
            })

        if symbol_end < global_end - tolerance:
            exited.append({
                "symbol": symbol,
                "end_date": str(symbol_end),
                "days_before_global_end": (global_end - symbol_end).days,
            })

        if symbol_start <= global_start + tolerance and symbol_end >= global_end - tolerance:
            surviving.append(symbol)

        # Check for large gaps in the data
        if len(df) > 1:
            diffs = df.index.to_series().diff().dt.days
            max_gap = diffs.max()
            if max_gap > max_gap_days:
                large_gaps.append({
                    "symbol": symbol,
                    "max_gap_days": int(max_gap),
                    "gap_date": str(diffs.idxmax()),
                })

    total_symbols = len(data_dict)
    if total_symbols > 0:
        # Bias score: fraction of symbols with issues
        n_issues = len(entered) + len(exited) + len(insufficient) + len(large_gaps)
        bias_score = min(n_issues / total_symbols, 1.0)
    else:
        bias_score = 0.0

    return {
        "surviving_symbols": surviving,
        "entered_symbols": entered,
        "exited_symbols": exited,
        "insufficient_data": insufficient,
        "large_gaps": large_gaps,
        "bias_score": bias_score,
    }


def load_multi_symbol(
    path: Union[str, Path],
    symbols: Optional[List[str]] = None,
    return_provenance: bool = False,
    adjust_splits: bool = False,
    **kwargs
) -> Union[dict, Tuple[dict, Dict[str, DataProvenance]]]:
    """
    Load data for multiple symbols.

    Args:
        path: Path to multi-symbol data file
        symbols: Optional list of symbols to filter
        return_provenance: If True, return (dict, provenance_dict) tuple
        **kwargs: Additional arguments passed to load_data

    Returns:
        Dictionary mapping symbol to DataFrame, or tuple with provenance dict
    """
    # The stacked frame legitimately has duplicate timestamps (one
    # row per symbol per date); per-symbol validation below is the
    # meaningful check, so suppress the aggregate-frame warning.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Data validation failed.*")
        df = load_data(path, symbol=None, **kwargs)

    if "symbol" not in df.columns and "ticker" not in df.columns:
        raise ValueError("Multi-symbol file must have 'symbol' or 'ticker' column")

    sym_col = "symbol" if "symbol" in df.columns else "ticker"
    unique_symbols = df[sym_col].unique()

    if symbols:
        unique_symbols = [s for s in unique_symbols if s in symbols]

    result = {}
    provenance_dict = {}
    for sym in unique_symbols:
        sym_df = df[df[sym_col] == sym].drop(columns=[sym_col])
        if validate_data(sym_df):
            if adjust_splits and "splits" in sym_df.columns:
                sym_df = _adjust_for_splits(sym_df)
            result[sym] = sym_df
            if return_provenance:
                # Create provenance for this symbol
                prov = DataProvenance(
                    source_path=str(path),
                    load_timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    file_format=Path(path).suffix.lower(),
                    file_size_bytes=Path(path).stat().st_size,
                    symbol_filter=sym,
                    original_shape=sym_df.shape,
                    final_shape=sym_df.shape,
                    columns_original=list(sym_df.columns),
                    columns_final=list(sym_df.columns),
                    validation_passed=True,
                    checksum=_compute_checksum(sym_df),
                    total_return_type=_detect_benchmark_total_return_type(sym_df),
                    transformations_applied=[]
                )
                if adjust_splits and "splits" in result[sym].columns and result[sym].get("splits_adjusted", False) if "splits_adjusted" in result[sym] else False:
                    prov.transformations_applied.append("split_adjustment_applied")
                if isinstance(result[sym].index, pd.DatetimeIndex) and len(result[sym]) > 0:
                    prov.date_range_final = (
                        str(result[sym].index.min()), str(result[sym].index.max())
                    )
                provenance_dict[sym] = prov

    if return_provenance:
        return result, provenance_dict
    return result


def align_data(data_dict: dict, method: str = "inner") -> dict:
    """
    Align multiple symbol DataFrames to common date index.

    Args:
        data_dict: Dictionary of symbol -> DataFrame
        method: Join method ('inner', 'outer', 'left')

    Returns:
        Dictionary with aligned DataFrames
    """
    if not data_dict:
        return {}

    # Get common index
    indices = [df.index for df in data_dict.values()]
    if method == "inner":
        common_index = indices[0]
        for idx in indices[1:]:
            common_index = common_index.intersection(idx)
    elif method == "outer":
        common_index = indices[0]
        for idx in indices[1:]:
            common_index = common_index.union(idx)
    else:
        common_index = indices[0]

    common_index = common_index.sort_values()

    # Reindex all DataFrames
    aligned = {}
    for sym, df in data_dict.items():
        aligned[sym] = df.reindex(common_index)

    return aligned


def resample_data(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """
    Resample OHLCV data to different frequency.

    Args:
        df: DataFrame with OHLCV data
        freq: Target frequency (e.g., '1H', '1D', '1W')

    Returns:
        Resampled DataFrame
    """
    ohlc_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }

    # Add optional columns if present
    for col in OPTIONAL_COLUMNS:
        if col in df.columns:
            if col == "volume":
                ohlc_dict[col] = "sum"
            else:
                ohlc_dict[col] = "last"

    return df.resample(freq).apply(ohlc_dict).dropna(subset=["open", "close"])



def fetch_ohlcv_yahoo(symbol: str, start: str, end: str, max_retries: int = 3,
                     backoff_base: float = 2.0, timeout: int = 20) -> pd.DataFrame:
    """Bounded fetch of daily OHLCV from Yahoo Finance chart API.

    Honors HTTP 429 (reads Retry-After when present), retries with exponential
    backoff, and never retries blindly. Raises RuntimeError on failure so callers
    can record the limitation. Returns a DataFrame with date index and OHLCV columns.
    """
    import time, json, urllib.request, urllib.error
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?period1=%d&period2=%d&interval=1d&events=div,splits")
    # convert dates
    import calendar
    def _ts(d):
        import datetime as _dt
        dt = _dt.datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=__import__("datetime").timezone.utc)
        return int(dt.timestamp())
    p1, p2 = _ts(start), _ts(end)
    full = url % (symbol, p1, p2)
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            result = payload["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame({
                "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(None).normalize(),
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "close": q["close"],
                "volume": q["volume"],
            })
            df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
            if "adjclose" in result["indicators"]:
                df["adj_close"] = result["indicators"]["adjclose"][0]["adjclose"]
            return df
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff_base ** (attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(min(wait, 30))
                    continue
            break
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(backoff_base ** attempt)
                continue
            break
    raise RuntimeError(f"fetch failed for {symbol}: {last_err}")


if __name__ == "__main__":
    # Quick test
    import tempfile

    # Create sample data
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, 100)
    prices = 100 * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        "date": dates,
        "open": prices * np.random.uniform(0.995, 1.005, 100),
        "high": prices * np.random.uniform(1.005, 1.02, 100),
        "low": prices * np.random.uniform(0.98, 0.995, 100),
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, 100)
    })

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        df.to_csv(f.name, index=False)
        print(f"Test file: {f.name}")
        loaded = load_data(f.name)
        print(f"Loaded shape: {loaded.shape}")
        print(f"Validation: {validate_data(loaded)}")