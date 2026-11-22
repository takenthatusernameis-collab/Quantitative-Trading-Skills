# Handoff — Current State: cost-aware capacity breakdown per period in JSON summaries complete

## What changed

- `--max-participation-rate`, `--borrow-cost`, `--funding-cost`, `--leverage`, `--short-exposure`, `--max-borrow-cost`, `--max-funding-cost` flags all present in `common_parser` (walk_forward.py:12226+).
- Threaded through `walk_forward_analysis`, `cpcv_analysis`, `out_of_sample_validation`, and both Monte Carlo summary paths.
- Passed to every `estimate_capacity` call; `estimate_capacity` returns full cost-aware breakdown (impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years).
- Per-period capacity breakdown surfaced in JSON summary under `periods[i]["capacity"]` and aggregate under `summary["capacity"]`.
- Focused tests added and passing: 49 capacity/participation-rate/cost-drag tests.

## What was actually verified

- `test_walk_forward.py -k "capacity or participation_rate or cost_drag"` → **49 passed** (includes per-period, summary, CLI, CPCV, OOS, Monte Carlo paths).
- `test_run_backtest.py -k "capacity or participation_rate or cost_drag"` → **12 passed** (CLI parse, capacity bind, no-bind, invalid rejection, cost drag).
- Full `test_walk_forward.py` → **227 passed**.
- Full `test_run_backtest.py` → **127 passed**.
- Full quant gate: **1538+ passed, 9 failed** in 38m47s with `-n 4`. The 9 failures are pre-existing in `test_reporting.py` (tear sheet/heatmap PNG generation, matplotlib backend issues), unrelated to capacity work.

## What remains unresolved

- 9 pre-existing `test_reporting.py` failures (tear sheet/heatmap generation). These are environment/backend issues, not regressions.
- No CSV export for summaries (JSON only).
- No profitability/capacity claim. Committed-fixture verdicts remain `NOT SUPPORTED`.

## Approaches already tried / failed

- None; the capacity model with borrow/funding cost and participation-rate cap was already complete per HANDOFF_SESSION_153.md.

## One precise next task

Consider adding a CLI flag `--output-format {json,csv}` to emit `walk_forward_summary.csv` with flattened per-period capacity rows (period, impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years) alongside the existing JSON. This would make the cost-aware capacity breakdown directly consumable by spreadsheet tools. Baseline: 1538+ passed (ignoring 9 pre-existing reporting failures).