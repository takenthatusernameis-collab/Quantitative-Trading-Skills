# Next Session Task — Methodological validation with cost-aware capacity across validation methods

## Task
Run a cross-method comparison (walk-forward / CPCV / monte-carlo) on a committed real fixture (AAPL/MSFT/GOOGL) with realistic costs (impact, borrow, funding, commission, slippage) and verify the cost-aware capacity numbers are internally consistent across the three validation methods. Exercise `--max-participation-rate`, `--max-borrow-cost`, `--max-funding-cost` caps end-to-end and assert the capacity CSV reflects the active cap. Optionally extend the CSV to include per-fold/per-combination regime diagnostics when regime analysis is engaged.

## Evidence / where to look
- CSV emit blocks for all five subcommands are in `walk_forward.py` (search `capacity_detail` and `output_format`).
- Template tests: `test_cli_cpcv_output_format_csv_writes_capacity_rows`, `test_cli_optimize_output_format_csv_writes_capacity_rows`, `test_cli_monte_carlo_output_format_csv_writes_capacity_rows` in `tests/test_walk_forward.py`.
- Real fixtures: `assets/example_data/real_market_data/*.csv` (AAPL, MSFT, GOOGL).
- Capacity estimation logic: `estimate_capacity` in `utils.py`, `book_capacity_estimate` in `utils.py`.

## Constraints
- Committed fixtures only (`assets/example_data/real_market_data/*.csv`), no network.
- Do not modify engine math; keep changes additive and reversible.
- Verify with `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py` (currently 235/235) and `tests/test_reporting.py`.

(End of file - total 14 lines)