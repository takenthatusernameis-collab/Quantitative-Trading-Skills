# Handoff — Next Task (2026-11-21): Fix short-capable TSMOM sweep lookback bug and re-verify

## Context
Audit COMPLETE: Short-capable borrow cost realism sweep (`run_borrow_cost_sweep_short_capable`) and stressed-regime cost sweep (`run_regime_cost_sweep_short_capable`) use fixed `lookback=252`, incompatible with 12-month test windows. All metrics NaN, tests pass vacuously. Corrected sweep with grid [126, 189, 252] + `allow_short=True` shows: OOS Sharpe 1.40→1.34, Return 0.80→0.73 as borrow rises 0→5%; DSR p-value 0.45→0.49 (fails criterion); directional claim holds; hypothesis NOT SUPPORTED.

## Precise next task
Fix `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`:
1. In `run_borrow_cost_sweep_short_capable`: replace fixed `lookback=252` with the full `PARAM_GRID` (`{"lookback": [126, 189, 252]}`) plus `allow_short=True` in the param grid passed to walk-forward.
2. In `run_regime_cost_sweep_short_capable`: same fix.
3. Update `_run_walk_forward_short_capable` to accept/use the full grid instead of a single lookback.
4. Verify corrected sweeps produce non-NaN metrics and directional claim holds with real numbers.
5. Harden test `test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py` to assert frictionless-level Sharpe/return are not NaN.

## Constraints
- Reuse existing walk_forward/cost models; no new frameworks.
- Offline committed fixtures only; no live network.
- Do not commit unless asked.
- Make no profitability claim beyond the test.

## Success criteria
- Both short-capable sweeps run with proper grid and produce non-NaN OOS Sharpe, return, DSR p-value at all borrow cost levels.
- Directional claim verified with actual numbers (monotonic degradation).
- Test passes with non-vacuous assertions (frictionless metrics not NaN).
- Verdict: NOT SUPPORTED at all levels (DSR criterion fails) — correctly reported.

(End of file - total 20 lines)