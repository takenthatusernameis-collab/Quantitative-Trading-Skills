# Handoff — Out-of-sample CSV capacity fix complete + regression test added

## What changed
- **Underlying fix (already committed, HEAD 99780e6):** `run_out_of_sample_validation()` in `skills/quantitative-backtesting/scripts/walk_forward.py` now populates `test_performance.capacity_detail` (and `capacity_trend`) in `summary_data` so the CSV emission block at walk_forward.py:12575 reads a `capacity_detail` dict instead of a float scalar. The `.get()`-on-a-float crash no longer reproduces; `cap` is a dict.
- **New regression test:** `test_cli_out_of_sample_output_format_csv_writes_capacity_rows` in `skills/quantitative-backtesting/tests/test_walk_forward.py` (+63 lines), registered in TEST_REGISTRY. Asserts the OOS CLI with `--output-format csv` writes `out_of_sample_summary.csv` with columns `impact_capacity`, `participation_capacity`, `cost_adjusted_capacity`, `cost_drag`, `holding_period_years`, exactly one row, positive `cost_adjusted_capacity`, and that default JSON mode writes no CSV.
- No engine math modified; no marketplace/catalog/schema changes. Working tree clean except the one test file.

## What was actually verified
- `test_cli_out_of_sample_output_format_csv_writes_capacity_rows` → PASS
- `test_main_registers_every_module_level_test` (registry integrity) → PASS
- Existing CSV tests (walk-forward, CPCV, optimize, monte-carlo) → 5/5 PASS (no regression)
- Manual end-to-end: OOS CLI on committed real AAPL fixture (`skills/quantitative-backtesting/assets/example_data/real_market_data/AAPL.csv`) with `--impact-coefficient 0.0005 --output-format csv` → exit 0 and `out_of_sample_summary.csv` has non-null capacity fields (`impact_capacity`/`cost_adjusted_capacity` = 11,614,740,393.89, `cost_drag` = 0.0, `holding_period_years` = 0.00397).

## What remains unresolved
- `--max-borrow-cost` / `--max-funding-cost` caps not exercised end-to-end (cost_drag = 0.0 for long-only sma_crossover; would require a short/leveraged strategy).
- `cost_drag = 0.0` for all runs with long-only strategies.

## Approaches that already failed (do not repeat)
- None for this change: the `.get()`-on-float crash no longer reproduces (`cap` is now a dict). Prior attempt to read `test_performance.capacity` (float) was superseded by reading the `capacity_detail` dict (already in HEAD).

## Next precise task
Exercise the `--max-borrow-cost` / `--max-funding-cost` caps end-to-end on the OOS path with a strategy that has actual borrow/funding exposure (e.g., MACD which goes short, using `--borrow-cost`/`--funding-cost` and `--max-borrow-cost`/`--max-funding-cost`), and confirm `cost_drag` > 0 and `cost_adjusted_capacity` reflects the binding cap in `out_of_sample_summary.csv`. Evidence: existing OOS borrow/funding sweep tests at test_walk_forward.py:4416 / :4450 use MACD with `--borrow-costs`/`--funding-costs`; the CSV block reads `capacity_detail.cost_drag`. Constraints: committed fixtures only, no network, minimal change, do not modify engine math.
