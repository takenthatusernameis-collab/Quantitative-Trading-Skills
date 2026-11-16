# Handoff — Session 126 (2026-11-16): TSMOM triple-panel capacity/liquidity sensitivity sweep

## What changed
- **Modified** `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`:
  - Added optional `impact_coefficient` (default `0.0`, backward-compatible) to `_run_walk_forward_panel` and passed it to `walk_forward_analysis(...)`.
  - Added `CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]` and `run_capacity_sensitivity_sweep(...)` reporting `capacity`, `capacity_book`, `capacity_notional_weighted`, `oos_min_capacity` per level on committed triple panel (AAPL/MSFT/GOOGL) at advertised costs. Enforces: impact-disabled -> `capacity=None`; impact-enabled finite positive and strictly monotonically decreasing as impact rises. Defaults unchanged.
- **Added** `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py` (offline committed fixtures; directional monotonic capacity assertions, no profitability/capacity claim).
- Gate-dirtied generated artifacts reverted after gate.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| New capacity sensitivity test | `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py -p no:cacheprovider -q` -> **1 passed (1.73s)**. |
| Existing TSMOM elevated-cost test | `.../test_walk_forward_time_series_momentum_elevated_cost_real_triple_aapl_msft_googl.py -q` -> **1 passed (1.53s)**. |
| Related walk-forward example tests | `.../test_walk_forward.py -k "test_real_data_pipeline_example_runs or test_falsifiable_hypothesis_example_runs" -q` -> **2 passed, 206 deselected in 204.50s**, EXIT 0. |
| Full quant gate | `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1470 passed, 0 failed, 518 warnings, EXIT 0** in **2922.70s (0:48:42)**. |
| Sweep (committed fixtures, 2026-11-16T12:58:10Z) | 0.0: capacity None (UNMEASURABLE); 0.05: 292,185,567.88 / book 93,514,302.49 / nw 93,514,302.49 / oos_min 71,179,585.36; 0.10: 146,092,783.94 / 46,757,151.25 / 46,757,151.25 / 35,589,792.68; 0.20: 73,046,391.97 / 23,378,575.62 / 23,378,575.62 / 17,794,896.34. Monotonic decrease confirmed. |

## What remains unresolved
- No profitability/capacity/market evidence (sensitivity on committed fixtures only; nominal capacity is model/ADV math, not executable capacity/investability). TSMOM verdicts unchanged (sensitivity-only).
- Methodological/data gaps: survivorship/universe/PIT membership, corporate-action completeness, liquidity/capacity realism beyond linear impact sweep, borrow/funding/slippage realism, broader genuine OOS validation.
- Working tree has intended uncommitted changes/untracked test+handoff; not committed/pushed. Local `main` ahead of `origin/main`.

## Approaches already tried / failed (do not repeat unchanged)
- Keep default `impact_coefficient=0.0` and monotonic-capacity assertions (guards silent no-op). Do not tune/flip verdicts for SUPPORTED outcomes.
- Use full gate with `-n 4` (~48 min) and revert gate-dirtied generated artifacts. Do not claim nominal capacity proves real tradability.

## One precise next task
**Add a bounded, falsifiable OOS-min-capacity vs deployed-capital sensitivity report for the committed triple-panel TSMOM walk-forward path (no live data, no parameter tuning).** Use `run_capacity_sensitivity_sweep`'s `oos_min_capacity` and walk-forward capacity fields (`oos_min_capacity_book`, `capacity_trend`) to add an additive, pre-registered output/test scoped to committed fixtures that reports per impact level whether worst-OOS-window capacity exceeds a pinned deployed-capital reference (e.g. walk-forward default `initial_capital=100000`) and flags `NOT CAPACITY-CONSTRAINED` vs `CAPACITY-CONSTRAINED` honestly per level (no default/verdict changes). Verify with focused tests then `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (EXIT 0), revert gate-dirtied artifacts, and document commands/metrics/limitations in handoff.
