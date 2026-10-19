# HANDOFF_NEXT

## The one precise next task

Regenerate the canonical `test_output/` regression snapshot under the current code's
defaults, so the pinned artifacts are not stale.

### Why

`skills/quantitative-backtesting/test_output/` (the pinned snapshot referenced by
`SKILL.md` line 584-589) was produced before the notional-weighted impact
aggregation, the `--panel-pricing book` mode, the book cost basis, and the
multiple-benchmark Deflated Alpha Ratio were added. Its artifacts therefore carry no
`panel_pricing`, `impact_aggregation`, `capacity_book`, `book_diagnostic`, or
`deflated_alpha` keys, and its `tear_sheet_summary.json` predates the capacity /
capacity-trend / participation-dilution rendering. It is a valid snapshot of an older
code state, not a defect — but consumers that diff against it will see every new key
as a change, and the SKILL.md instruction to regenerate it is now stale.

### Evidence

- `SKILL.md:584-589` documents the regeneration command and calls the snapshot "pinned".
- The prior handoff lists "Reference artifacts in `test_output/` not regenerated
  (no panel-mode artifact set exists yet)" as unresolved.
- `skills/quantitative-backtesting/test_output/` contains `metrics.json`,
  `report.txt`, `tear_sheet_summary.json`, `tear_sheet.html`, `equity_curve.png`,
  `returns_distribution.png`, `data_provenance.json` — all timestamped 2026-10-13,
  before the notional-weighted work.

### Constraints

- Use the exact command from `SKILL.md:586`:
  `python3 skills/quantitative-backtesting/scripts/run_backtest.py --data
  skills/quantitative-backtesting/assets/example_data/sample_ohlcv.csv --params
  '{"fast_period": 10, "slow_period": 30}' --output
  skills/quantitative-backtesting/test_output`
- Do not change default aggregation (`panel`) or default panel pricing
  (`net-exposure`); the snapshot must be a single-asset SMA run, so the new panel-only
  keys (`book_diagnostic`, `capacity_book`, `impact_*`) are `None`/absent by design.
- Do not commit unless asked; the regenerated PNGs are environment-dependent and will
  churn the diff.

### Verification

After regenerating, re-run `python3 skills/quantitative-backtesting/tests/test_run_backtest.py`
(103/103) and `test_examples_coverage.py` (7/7) to confirm no test pins a stale
artifact value.

(End of file - total 46 lines)
