# Next Session Task — Exercise OOS borrow/funding cost caps end-to-end

## Task
Exercise the `--max-borrow-cost` / `--max-funding-cost` caps end-to-end on the out-of-sample path with a strategy that has actual borrow/funding exposure (MACD goes short), and confirm `cost_drag` > 0 and `cost_adjusted_capacity` reflects the binding cap in `out_of_sample_summary.csv`.

## Evidence / where to look
- CSV emission block: `skills/quantitative-backtesting/scripts/walk_forward.py:12574-12585` reads `cap = (summary_data.get("test_performance") or {}).get("capacity_detail") or {}` and writes `cost_drag`, `cost_adjusted_capacity` to `out_of_sample_summary.csv`.
- `capacity_detail` is populated at walk_forward.py:12494-12496 (`capacity`, `capacity_trend`, `capacity_detail`).
- Existing OOS sweep tests using MACD (short exposure): `test_cli_out_of_sample_borrow_sweep` test_walk_forward.py:4416, `test_cli_out_of_sample_funding_sweep` test_walk_forward.py:4450 — both use `--borrow-costs`/`--funding-costs` with MACD and assert held-out return degrades.
- Confirmed working: OOS `--output-format csv` on real AAPL fixture with `--impact-coefficient 0.0005` emits non-null capacity CSV (exit 0). Verified via `test_cli_out_of_sample_output_format_csv_writes_capacity_rows` (PASS) + manual run.

## Constraints
- Committed fixtures only, no network.
- Minimal change; do not modify engine math.
- Use `--max-borrow-cost` / `--max-funding-cost` (single-value caps, not the `-sweep` variants) so `cost_drag` binds.
- Confirm via a targeted test or direct CLI run that `out_of_sample_summary.csv` has `cost_drag > 0` and `cost_adjusted_capacity < impact_capacity` (binding cap).

## Expected outcome
A run like:
```
walk_forward out-of-sample --data <fixture> --symbol SPY --strategy macd \
  --param-grid '...' --validation-method walk_forward --train-frac 0.5 --val-frac 0.25 --test-frac 0.25 \
  --impact-coefficient 0.0005 --borrow-cost 0.03 --funding-cost 0.02 \
  --max-borrow-cost 0.01 --max-funding-cost 0.01 --output-format csv --output <dir>
```
should produce `out_of_sample_summary.csv` where `cost_drag > 0` and `cost_adjusted_capacity` reflects the binding borrow/funding cap.
