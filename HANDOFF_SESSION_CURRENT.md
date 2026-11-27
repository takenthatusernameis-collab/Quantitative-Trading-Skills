# Handoff — Session: `--output-format csv` for optimize & monte-carlo (verified)

## What changed
- `skills/quantitative-backtesting/scripts/walk_forward.py`:
  - `parameter_optimization()` now stores an additive `result["capacity_detail"]` dict per combination (impact / participation / cost_adjusted capacity, cost_drag, holding_period_years), mirroring the per-period capacity dict `walk_forward_analysis` records. The existing scalar `result["capacity"]` is untouched.
  - `run_parameter_optimization()` CLI save path surfaces `capacity_detail` on the top-ranked combination and writes `optimize_summary.csv` with flattened columns: `rank, sharpe_ratio, total_return, impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years` when `--output-format csv` is set.
  - `run_monte_carlo()` now stores `mc_results["summary"]["capacity_detail"]` with the same cost breakdown and writes `monte_carlo_summary.csv` with columns: `sharpe_ratio, total_return, impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years` when `--output-format csv` is set.
  - JSON is always written; csv only *adds* the CSV artifact.

- `skills/quantitative-backtesting/tests/test_walk_forward.py`:
  - Added `test_cli_optimize_output_format_csv_writes_capacity_rows` and `test_cli_monte_carlo_output_format_csv_writes_capacity_rows` (assert CSV presence + exact columns + positive cost_adjusted in csv mode, and absence of CSV in default json mode) and registered both in `TEST_REGISTRY`.

## What was actually verified
- `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py::test_cli_optimize_output_format_csv_writes_capacity_rows skills/quantitative-backtesting/tests/test_walk_forward.py::test_cli_monte_carlo_output_format_csv_writes_capacity_rows skills/quantitative-backtesting/tests/test_walk_forward.py::test_cli_cpcv_output_format_csv_writes_capacity_rows` → **3/3 passed**.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_reporting.py` → **73/73 passed**.
- End-to-end CLI on committed fixture for optimize: `walk_forward.py optimize --data assets/example_data/real_market_data/AAPL.csv --impact-coefficient 0.5 --output <tmp> --output-format csv` → exit 0; `optimize_summary.csv` written with 1 row, cost columns populated.
- End-to-end CLI on committed fixture for monte-carlo: `walk_forward.py monte-carlo --data assets/example_data/real_market_data/AAPL.csv --impact-coefficient 0.5 --n-simulations 100 --output <tmp> --output-format csv` → exit 0; `monte_carlo_summary.csv` written with 1 row, cost columns populated.
- Default json mode on both subcommands → exit 0, **no** CSV emitted (only JSON artifacts).
- `git status`: only the two intended files modified vs the prior handoff baseline; `git diff --stat` = +194 lines, no unrelated edits.

## What remains unresolved
- `participation_capacity` is empty in the CSV when `--max-participation-rate` is not set (expected — no cap → None), and `cost_drag=0.0` for long-only sma_crossover with no borrow/funding (expected). A run with a participation cap + borrow/funding would populate those columns; not exercised end-to-end here but covered structurally by the unit tests.
- `walk-forward` and `out-of-sample` subcommands already have `--output-format csv` (implemented in prior sessions).
- All five CLI subcommands (`walk-forward`, `optimize`, `monte-carlo`, `cpcv`, `out-of-sample`) now support `--output-format csv` with capacity/cost breakdown.
- No profitability/capacity claim: this session added reporting plumbing only; committed-fixture verdicts remain NOT SUPPORTED.

## Approaches that already failed (do not repeat)
- Making `capacity` a dict (to match walk-forward) would break existing assertions on the scalar field. Chose the additive `capacity_detail` field instead.
- The full `estimate_capacity` dict is NOT stored by default (only `estimated_capacity` scalar + `capacity_trend`); the cost breakdown had to be captured explicitly as `capacity_detail`. If extending CSV columns, read from `capacity_detail`, not `capacity`.

## Next precise task
The `--output-format csv` reporting plumbing is now complete across all five CLI subcommands. The next high-value quant research task should target **methodological validation**, e.g.:
- Run a walk-forward / CPCV / monte-carlo comparison on a committed real fixture (AAPL/MSFT/GOOGL) with realistic costs (impact, borrow, funding, commission, slippage) and verify the cost-aware capacity numbers are internally consistent across the three validation methods.
- Exercise `--max-participation-rate`, `--max-borrow-cost`, `--max-funding-cost` caps end-to-end and assert the capacity CSV reflects the active cap.
- Add a regime-aware impact coefficient sweep (`--regime-impact-coefficients`) and verify the CSV capacity breakdown reflects regime-specific impact.
- Extend the CSV to include per-fold/per-combination regime diagnostics (regime label, regime-specific impact, regime cost multiplier) when regime analysis is engaged.

Evidence: The three CSV test fixtures pass; the capacity_detail dict is populated on optimize/monte-carlo/cpcv summaries; the CLI flag is wired to all subparsers. Constraint: committed fixtures only, no network, do not modify engine math, keep changes additive.

(End of file - total 28 lines)