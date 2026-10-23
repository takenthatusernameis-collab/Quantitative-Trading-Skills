# Handoff — legacy results artifacts retired (2026-10-23)

## What changed
- Added `results/README.md` documenting that the committed legacy artifacts
  (`metrics.json`, `tear_sheet_summary.json`, `monte_carlo_results.json`, plots,
  `report.txt`) depend on `splits_test_data.csv`, which is absent from the repo and
  all git history. They are retained as historical reference only and must not be
  treated as reproducible evidence.
- `results/resolution_floor/*.json` cost sweeps are unaffected.

## What was actually verified
- Searched all git revisions (`git rev-list --all`); `splits_test_data.csv` never
  committed.
- Filesystem search found no copy.
- No test references `results/metrics.json`, so documenting retirement does not
  break the suite.

## What remains unresolved
- The input data itself is unrecoverable; regeneration requires restoring it
  (209 bytes, 5 trading days from 2020-01-01, SPY with `splits` column).

## One precise next task
Implement a small, reproducible worked example in
`skills/quantitative-backtesting/examples/` that regenerates a metrics artifact from
a committed tiny CSV fixture, so the project has at least one end-to-end
reproducible backtest. Use the existing `data_loader`/`run_backtest.py` path;
add a test pinning that the example reproduces byte-for-byte.
