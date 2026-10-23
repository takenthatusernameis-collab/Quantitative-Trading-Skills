# Results artifacts (legacy)

The committed artifacts in this directory (`metrics.json`, `tear_sheet_summary.json`,
`monte_carlo_results.json`, plots, `report.txt`) were generated on 2026-10-14 from
`splits_test_data.csv` (5 rows, 7 columns: date, open, high, low, close, volume, splits).

That input file is **not present** in this repository (searched all git history and
the working tree; no copy exists). The provenance files `data_provenance.json` and
`benchmark_provenance.json` record the load but cannot reconstruct the data.

Consequences:
- These artifacts cannot be regenerated from current code and must not be treated as
  reproducible evidence of any strategy's performance.
- They are retained only as historical reference and should not be cited as verified
  results.
- `results/resolution_floor/*.json` cost sweeps are unaffected and remain reproducible
  from their own scripts.

To regenerate: restore `splits_test_data.csv` (209 bytes, 5 trading days starting
2020-01-01, SPY with a `splits` column) and run
`skills/quantitative-backtesting/scripts/run_backtest.py`.
