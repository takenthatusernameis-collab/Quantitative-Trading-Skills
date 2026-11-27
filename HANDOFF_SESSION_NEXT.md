# Next Session Task — `--output-format csv` for optimize & monte-carlo subcommands

## Task
Add `--output-format {json,csv}` emit blocks to the **optimize** and **monte-carlo** subcommands of `skills/quantitative-backtesting/scripts/walk_forward.py`. The `--output-format` flag is already parsed for every subcommand via `common_parser` (see `main()` ~line 12557); only the per-subcommand CSV emit blocks are missing. Emit `optimize_summary.csv` and `monte_carlo_summary.csv` with flattened capacity/cost rows, and add one CLI test per subcommand (presence in csv mode, absence in default json mode), registered in `TEST_REGISTRY`.

## Evidence / where to look
- Mirror the CPCV emit block: search `print(f"CPCV summary saved to: {summary_path}")` in `walk_forward.py` — the csv block sits immediately after it and reads `capacity_detail` from each `capacity_per_fold` entry.
- Template test: `test_cli_cpcv_output_format_csv_writes_capacity_rows` in `tests/test_walk_forward.py`.
- The cost breakdown lives in `capacity_detail` (impact / participation / cost_adjusted / cost_drag / holding_period_years), NOT in the scalar `capacity` field. Do not mutate the existing scalar `capacity` field — it is relied on by `test_cli_cpcv_writes_capacity_per_fold`.

## Constraints
- Committed fixtures only (`assets/example_data/real_market_data/*.csv`), no network.
- Do not modify engine math; keep changes additive and reversible.
- Verify with `python3 skills/quantitative-backtesting/tests/test_walk_forward.py` (currently 235/235) and `tests/test_reporting.py`.