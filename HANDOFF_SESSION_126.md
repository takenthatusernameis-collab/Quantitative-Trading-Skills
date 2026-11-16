# Handoff — Session 126 (2026-11-16): TSMOM triple-panel capacity/liquidity sensitivity sweep

## What changed
- **Modified** `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`:
  - Added optional `impact_coefficient` (default `0.0`, backward-compatible) to `_run_walk_forward_panel` and passed it to `walk_forward_analysis(...)`.
  - Added `CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]` (pre-registered ascending grid; impact disabled first).
  - Added `run_capacity_sensitivity_sweep(grid=CAPACITY_SENSITIVITY_LEVELS)` which runs the committed three-asset TSMOM walk-forward panel (AAPL/MSFT/GOOGL) at advertised 3bps round-trip costs for each level and reports `capacity`, `capacity_book`, `capacity_notional_weighted`, and `oos_min_capacity`. Enforces directional claims: impact-disabled -> `capacity=None`; impact-enabled levels finite positive and strictly monotonically decreasing as `impact_coefficient` rises. Prints `CAPACITY SENSITIVITY SWEEP` and "Capacity falls with market impact". Defaults/hypothesis verdict logic unchanged.
- **Added** `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`:
  - Offline committed-fixture test on `assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv` asserting grid order, impact-disabled `None`, >=2 finite positive readings, strict monotonic decrease of capacity with rising impact, and expected output markers. No profitability/capacity claim.

No marketplace catalogs, schemas, upstream assets, or unrelated files modified. Gate-dirtied generated artifacts (`examples/example_reproducible_output/{data_provenance.json,tear_sheet.html,tear_sheet_summary.json}`) reverted after gate.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| New focused test | `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py -p no:cacheprovider -q` -> **1 passed in 1.73s**. |
| Existing TSMOM elevated-cost test | `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_elevated_cost_real_triple_aapl_msft_googl.py -p no:cacheprovider -q` -> **1 passed in 1.53s**. |
| Related walk-forward example subprocess tests | `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -k "test_real_data_pipeline_example_runs or test_falsifiable_hypothesis_example_runs" -p no:cacheprovider -q` -> **2 passed, 206 deselected in 204.50s (0:03:24), EXIT 0**. |
| Full quant gate | `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1470 passed, 0 failed, 518 warnings, EXIT 0** in **2922.70s (0:48:42)**. |
| Captured sweep output (committed fixtures, 2026-11-16T12:58:10Z) | impact 0.0: `capacity=None, capacity_book=None, capacity_notional_weighted=None, oos_min_capacity=None, verdict=UNMEASURABLE (impact off)`; 0.05: `capacity=292,185,567.88, capacity_book=93,514,302.49, capacity_notional_weighted=93,514,302.49, oos_min_capacity=71,179,585.36, MEASURABLE`; 0.10: `146,092,783.94 / 46,757,151.25 / 46,757,151.25 / 35,589,792.68`; 0.20: `73,046,391.97 / 23,378,575.62 / 23,378,575.62 / 17,794,896.34`. Capacity falls monotonically with rising impact; estimates move with `impact_coefficient` (no silent no-op). |

## What remains unresolved
- **No profitability/capacity/market evidence:** results are sensitivity analysis on committed fixtures (AAPL/MSFT/GOOGL CSVs, fixed panel, historical window) only. Large nominal capacity numbers reflect model/ADV math on fixture liquidity, not executable capacity, investability, or market impact realism.
- **TSMOM verdict unchanged:** prior handoffs record TSMOM elevated-cost/strategy verdicts on committed panels as NOT SUPPORTED/sensitivity-only; this session adds impact-capacity sensitivity only and does not alter falsification verdicts or claim support.
- **Methodological/data gaps:** survivorship/universe selection, point-in-time membership, corporate-action completeness, liquidity/capacity realism beyond linear impact coefficient sweep, borrow/funding realism, slippage regime dependence, and broader genuinely out-of-sample validation remain unresolved for triple-panel claims.
- **Persistence:** working tree has intended modifications/untracked files (`skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`, `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`, handoff updates). Not committed/pushed; local `main` remains ahead of `origin/main` per prior state. Do not commit/push unless explicitly asked.

## Approaches already tried / failed (do not repeat unchanged)
- Do not revert the `impact_coefficient` defaulted signature pass-through or the directional monotonic-capacity assertions without evidence; they preserve backward behavior and catch silent no-op impact paths.
- Do not rerun the full serial gate casually (~48 min); use `-n 4` and revert gate-dirtied generated artifacts afterward.
- Do not tune parameters, costs, impact grid, or verdict logic to force SUPPORTED/profitable/capacity-safe outcomes (anti-tuning).
- Do not claim the nominal capacity estimates prove real-world tradable capacity.

## One precise next task
**Add a bounded, falsifiable OOS-min-capacity vs deployed-capital sensitivity report for the committed triple-panel TSMOM walk-forward path (no live data, no parameter tuning).** Inspect `examples/time_series_momentum_hypothesis.py` (current `run_capacity_sensitivity_sweep` returns `oos_min_capacity`) and `scripts/walk_forward.py` capacity fields (`oos_min_capacity`, `oos_min_capacity_book`, `capacity_trend`) to determine the smallest additive, pre-registered criterion/output scoped to committed fixtures: e.g. report per impact level whether `oos_min_capacity` (worst OOS-window capacity, the binding liquidity reading) exceeds a pinned deployed-capital reference (such as `initial_capital=100000` used by walk-forward defaults) and flag NOT CAPACITY-CONSTRAINED vs CAPACITY-CONSTRAINED honestly per level without changing defaults or existing verdicts. Implement as an additive example function/test mirroring existing sensitivity sweep patterns, run focused tests then `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (EXIT 0), revert gate-dirtied artifacts, and document commands/metrics/limitations in handoff.
