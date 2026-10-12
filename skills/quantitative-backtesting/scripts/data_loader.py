#!/usr/bin/env python3
"""
Utilities for loading and validating market data from various sources.

Supports CSV, Parquet, and common data vendor formats.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Union, List
import warnings


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["adj_close", "dividends", "splits"]


def load_data(
    path: Union[str, Path],
    symbol: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    date_column: str = "date",
    **kwargs
) -> pd.DataFrame:
    """
    Load market data from file.

    Args:
        path: Path to data file (CSV or Parquet)
        symbol: Filter for specific symbol (if multi-symbol file)
        start: Start date filter (YYYY-MM-DD)
        end: End date filter (YYYY-MM-DD)
        date_column: Name of date column
        **kwargs: Additional arguments passed to pd.read_csv/read_parquet

    Returns:
        DataFrame with OHLCV data indexed by date
    """
    path = Path(path)

    if path.suffix == ".parquet":
        df = pd.read_parquet(path, **kwargs)
    elif path.suffix == ".csv":
        df = pd.read_csv(path, **kwargs)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}. Use CSV or Parquet.")

    # Standardize column names
    df.columns = df.columns.str.lower().str.strip()

    # Handle date column
    if date_column in df.columns:
        df[date_column] = pd.to_datetime(df[date_column])
        df = df.set_index(date_column)
    elif not isinstance(df.index, pd.DatetimeIndex):
        # Try to parse index as dates
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            raise ValueError("Could not parse date index. Specify date_column parameter.")

    # Ensure index is sorted
    df = df.sort_index()

    # Filter by symbol if provided and column exists
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol].copy()
        df = df.drop(columns=["symbol"])
    elif symbol and "ticker" in df.columns:
        df = df[df["ticker"] == symbol].copy()
        df = df.drop(columns=["ticker"])

    # Filter by date range
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    # Ensure required columns exist
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure numeric types
    for col in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def validate_data(df: pd.DataFrame, strict: bool = False) -> bool:
    """
    Validate market data quality.

    Args:
        df: DataFrame with OHLCV data
        strict: If True, raise exceptions on validation failures

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
        freq = pd.infer_freq(df.index)
        if freq and freq not in ["B", "D", "W"]:
            messages.append(f"Unusual frequency detected: {freq}")

    # Check volume
    if "volume" in df.columns and (df["volume"] < 0).any():
        messages.append("Negative volume detected")
        checks.append(False)

    if not all(checks):
        msg = "Data validation failed:\n" + "\n".join(f"  - {m}" for m in messages)
        if strict:
            raise ValueError(msg)
        else:
            warnings.warn(msg)
        return False

    return True


def load_multi_symbol(
    path: Union[str, Path],
    symbols: Optional[List[str]] = None,
    **kwargs
) -> dict:
    """
    Load data for multiple symbols.

    Returns:
        Dictionary mapping symbol to DataFrame
    """
    df = load_data(path, symbol=None, **kwargs)

    if "symbol" not in df.columns and "ticker" not in df.columns:
        raise ValueError("Multi-symbol file must have 'symbol' or 'ticker' column")

    sym_col = "symbol" if "symbol" in df.columns else "ticker"
    unique_symbols = df[sym_col].unique()

    if symbols:
        unique_symbols = [s for s in unique_symbols if s in symbols]

    result = {}
    for sym in unique_symbols:
        sym_df = df[df[sym_col] == sym].drop(columns=[sym_col])
        if validate_data(sym_df):
            result[sym] = sym_df

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