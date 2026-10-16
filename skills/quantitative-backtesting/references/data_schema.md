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

## Split Adjustment Conventions

The `splits` column records the split ratio as `new_shares / old_shares`
(e.g. `2.0` for a 2-for-1 split), matching the Yahoo Finance convention.
The close price on the split date is already at the **post-split** price level.

`adjust_for_splits()` (a.k.a. `_adjust_for_splits`) brings all pre-split prices
to the post-split level by **dividing** them by the cumulative product of the
split ratios that occur on or after each date. This is the inverse of the
multiplicative convention used by some vendors, and it keeps the split-date
return at zero (no artificial drop) when the split-date close is already at
the post-split level.

For multiple consecutive splits, the ratios accumulate: a 2-for-1 split
followed by a 3-for-1 split applies a cumulative factor of `2.0 * 3.0 = 6.0`
to dates before the first split, `3.0` to dates between the two splits, and
`1.0` to dates after the last split.

Pre-split **volume** is scaled **up** by the cumulative ratio so the series
stays comparable across the split date (volume was recorded in pre-split share
units). When an `adj_close` column is available, it may be used as ground
truth: after adjustment, `close` should match `adj_close` and the split-date
return should match the `adj_close` return.

## When Split Adjustment Applies During Benchmark Comparison

Strategy-vs-benchmark comparison (total return, annualized return, correlation,
alpha, beta, alpha t-statistic and p-value, R^2) is **split-adjusted whenever
the benchmark data carries a `splits` column**, in all three benchmark code
paths:

- single-benchmark comparison in `out_of_sample_validation`
- `_add_benchmark_to_summary` (used by walk-forward, CPCV, and parameter optimization)
- `_benchmark_list_alpha_correction` (multiple-benchmark Deflated Alpha correction)

Benchmarks without a `splits` column use the standard stats path unchanged.

Split adjustment is **orthogonal to the benchmark cost model**. The
`benchmark_cost_is_periodic` flag controls only whether benchmark transaction
costs are charged once (round-trip, default) or each period (periodic); it does
not gate split adjustment. A corporate action injects an artificial price drop
into benchmark returns under both cost models, so every split-bearing benchmark
is split-adjusted before benchmark stats are computed, independent of whether
costs are modeled as round-trip or periodic. `benchmark_cost_is_periodic` is
forwarded unchanged to `_benchmark_stats`, so periodic or round-trip cost
handling is preserved after split adjustment.