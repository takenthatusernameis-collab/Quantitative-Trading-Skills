# Handoff — Walk-forward cost-aware capacity breakdown per period complete

## What changed
- Added focused test `test_walk_forward_analysis_surfaces_cost_drag_and_holding_period_per_period` in `skills/quantitative-backtesting/tests/test_walk_forward.py:7672` verifying that each per-period capacity dict in walk-forward results carries `cost_drag` and `holding_period_years`, and that borrow/funding costs reduce `cost_adjusted_capacity` relative to `impact_capacity` per period.
- The existing `test_walk_forward_summary_capacity_surfaces_cost_drag_and_holding_period` already covers the summary-level breakdown.
- The per-period capacity breakdown (impact vs participation vs cost drag) is already surfaced in the JSON summary output (`walk_forward_summary.json`) under `periods[i]["capacity"]` and `summary["capacity"]` — no code changes needed in `walk_forward.py`.

## What was verified
- `pytest skills/quantitative-backtesting/tests/test_walk_forward.py::test_walk_forward_analysis_surfaces_cost_drag_and_holding_period_per_period` → PASSED
- `pytest skills/quantitative-backtesting/tests/test_walk_forward.py::test_walk_forward_summary_capacity_surfaces_cost_drag_and_holding_period` → PASSED
- All 49 capacity/participation-rate/cost-drag related tests pass.
- JSON output confirmed to include `impact_capacity`, `participation_capacity`, `cost_adjusted_capacity`, `cost_drag`, `holding_period_years` for both summary and every period.

## What remains unresolved
- 9 pre-existing `test_reporting.py` failures (matplotlib backend), unrelated.
- No CSV export for summaries (JSON only); the "CSV" mention in the task may refer to post-processing the JSON.
- No profitability/capacity claim; committed-fixture verdicts remain `NOT SUPPORTED`.

## One precise next task
Consider adding a CLI flag `--output-format {json,csv}` to emit `walk_forward_summary.csv` with flattened per-period capacity rows (period, impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years) alongside the existing JSON. This would make the cost-aware capacity breakdown directly consumable by spreadsheet tools. Baseline: 1538+ passed (ignoring 9 pre-existing reporting failures).