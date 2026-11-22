# Handoff — Current State: cost-aware capacity breakdown per period in JSON summaries complete; capacity-format regressions fixed

## What changed

- `--max-participation-rate`, `--borrow-cost`, `--funding-cost`, `--leverage`, `--short-exposure`, `--max-borrow-cost`, `--max-funding-cost` flags all present in `common_parser` (walk_forward.py:12226+).
- Threaded through `walk_forward_analysis`, `cpcv_analysis`, `out_of_sample_validation`, and both Monte Carlo summary paths.
- Passed to every `estimate_capacity` call; `estimate_capacity` returns full cost-aware breakdown (impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years).
- Per-period capacity breakdown surfaced in JSON summary under `periods[i]["capacity"]` and aggregate under `summary["capacity"]` (dict keyed on the five breakdown fields; headline scalar is `cost_adjusted_capacity`).
- Focused tests added and passing: 49 capacity/participation-rate/cost-drag tests.
- **Regression fix this session:** `summary["capacity"]` changed from a scalar to a cost-aware dict, which broke `time_series_momentum_hypothesis.py:run_capacity_sensitivity_sweep` (`f"${capacity:,.0f}"` at time_series_momentum_hypothesis.py:820 raised `TypeError: unsupported format string passed to dict.__format__`). Fixed by extracting the headline scalar `cost_adjusted_capacity` from the dict when present (one-line change in the example script; no framework or test changes).

## What was actually verified

- `test_walk_forward.py -k "capacity or participation_rate or cost_drag"` → **49 passed**.
- `test_run_backtest.py -k "capacity or participation_rate or cost_drag"` → **12 passed**.
- Full `test_walk_forward.py` → **227 passed**.
- Full `test_run_backtest.py` → **127 passed**.
- Full quant gate: `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` → **1558 passed, 0 failed** in ~29m (offline/committed fixtures).
- The two previously failing tests (`test_capacity_sensitivity_sweep_runs_on_triple_real_window_time_series_momentum`, `test_report_runs_on_triple_real_window_time_series_momentum`) now pass.

## What remains unresolved

- 9 pre-existing `test_reporting.py` failures (tear sheet/heatmap PNG generation, matplotlib backend issues), unrelated to capacity work — present before this session.
- No CSV export for summaries (JSON only).
- No profitability/capacity claim. Committed-fixture verdicts remain `NOT SUPPORTED`.

## Approaches already tried / failed

- None; the capacity model with borrow/funding cost and participation-rate cap was already complete per HANDOFF_SESSION_153.md; per-period cost-aware breakdown complete per HANDOFF_SESSION_154.md.

## One precise next task

Consider adding a CLI flag `--output-format {json,csv}` to emit `walk_forward_summary.csv` with flattened per-period capacity rows (period, impact_capacity, participation_capacity, cost_adjusted_capacity, cost_drag, holding_period_years) alongside the existing JSON. This would make the cost-aware capacity breakdown directly consumable by spreadsheet tools. Baseline: 1558 passed, 0 failed (ignoring 9 pre-existing reporting failures). Constraints: offline/committed fixtures only; default JSON output must be bitwise identical; do not commit unless explicitly asked.
