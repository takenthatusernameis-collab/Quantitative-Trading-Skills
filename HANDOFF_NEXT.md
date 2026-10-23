# Handoff — Legacy results retired (2026-10-23)

## What changed

The assigned reproducibility task is resolved by **retirement**, not regeneration: `results/metrics.json`, `tear_sheet_summary.json`, `monte_carlo_results.json`, plots, and `report.txt` are absent from the tree; `results/RETIREMENT_NOTICE.md`, `results/README.md`, and `results/RESULTS_AUDIT.md` document that `splits_test_data.csv` is missing and these artifacts are historical only. `results/resolution_floor/*.json` remain reproducible.

## What was actually verified

- `git ls-files results` contains no `metrics.json`/`tear_sheet_summary.json`/`monte_carlo_results.json`.
- Only documentation references `splits_test_data` (no code path depends on it).
- Quantitative test suites green: `test_performance.py` 33/33, `test_strategy_builder.py` 33/33.

## What remains unresolved

Two pre-existing failures in `skills/quantitative-backtesting/tests/test_run_backtest.py` (also failing on clean baseline), unrelated to retirement:
- `test_run_backtest_split_surfaces_split_metadata_in_tear_sheet_summary`: HTML tear sheet does not contain "train_val_test_split / test_start" (metadata present in JSON but not rendered in HTML).
- `test_run_backtest_split_signals_share_split_index`: off-by-one — `len(results["returns"])` is 150 vs expected split size 151.

## One precise next task

Fix the two split-metadata test failures in `skills/quantitative-backtesting/tests/test_run_backtest.py` and the underlying code (`skills/quantitative-backtesting/scripts/run_backtest.py`, reporting/tear-sheet generation). Constraint: make the smallest change that makes split metadata render in the HTML tear sheet and aligns signal length with split size; do not weaken tests. Relevant files: `skills/quantitative-backtesting/scripts/run_backtest.py`, `skills/quantitative-backtesting/reporting.py` (or wherever `generate_tear_sheet` lives), `tests/test_run_backtest.py:3705,3765`.
