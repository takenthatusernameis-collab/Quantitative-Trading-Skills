# Data Schema Reference

This document specifies the expected data formats, column specifications, and
ingestion rules for the quantitative backtesting skill.

## Supported File Formats

| Format   | Extension | Reader                | Notes                              |
| -------- | --------- | --------------------- | ---------------------------------- |
| CSV      | `.csv`    | `pandas.read_csv`     | Column names are lowercased        |
| Parquet  | `.parquet`| `pandas.read_parquet` | Preserves dtypes; supports partitions |

## Required Columns

Every dataset must contain these columns (case-insensitive; names are
normalized to lowercase on load):

| Column   | Type        | Description                                  |
| -------- | ----------- | -------------------------------------------- |
| `date`   | datetime    | Trading session date (or DatetimeIndex)     |
| `open`   | float > 0   | Opening price                                |
| `high`   | float > 0   | Highest price of the session                 |
| `low`    | float > 0   | Lowest price of the session                  |
| `close`  | float > 0   | Closing price                                |
| `volume` | float >= 0  | Trading volume                               |

## Optional Columns

| Column       | Type       | Description                                   |
| ------------ | ---------- | --------------------------------------------- |
| `adj_close`  | float      | Adjusted close (splits/dividends applied)     |
| `dividends`  | float      | Dividend payment per share                    |
| `splits`     | float      | Split ratio (e.g. 2.0 for a 2-for-1 split)   |
| `symbol`     | string     | Ticker symbol (required for multi-symbol files) |
| `ticker`     | string     | Alternate symbol column name                  |

## Date Handling

- The `date` column is parsed with `pd.to_datetime` and set as the index.
- If the input already has a `DatetimeIndex`, the date column is optional.
- The index is sorted ascending after load.
- Duplicate dates are treated as a validation failure.

## Multi-Symbol Files

When loading multiple symbols from a single file, include a `symbol` (or
`ticker`) column. The `load_multi_symbol` function returns a dictionary keyed
by symbol, with the identifier column dropped from each frame.

## Validation Rules

The `validate_data` function enforces the following checks:

1. Required columns are present.
2. No null values in required columns (warning only in non-strict mode).
3. No non-positive prices.
4. `high >= low` for every row.
5. `high >= open` and `high >= close`; `low <= open` and `low <= close`.
6. No duplicate dates in the index.
7. No negative volume.

## Example CSV

```csv
date,open,high,low,close,volume
2020-01-02,323.26,324.20,322.90,323.80,28900300
2020-01-03,323.50,325.20,323.10,324.90,26300900
2020-01-06,325.00,326.10,324.60,325.92,25601300
```

## Resampling

Use `resample_data` to convert between frequencies. OHLCV aggregation rules:

| Column  | Aggregation |
| ------- | ----------- |
| `open`  | `first`     |
| `high`  | `max`       |
| `low`   | `min`       |
| `close` | `last`      |
| `volume`| `sum`       |