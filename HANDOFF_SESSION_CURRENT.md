# Handoff — Current State (2026-11-21): Short-capable TSMOM sweep lookback bug FIXED

## Baseline
- HEAD `d4aaaf0`, branch `main`. Working tree has this session's UNCOMMITTED
  changes (do NOT commit unless asked):
  - `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_regime_cost_sweep_short_capable_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/examples/short_capable_sweeps_corrected_results.json` (new, untracked)

## What changed
1. `_run_walk_forward_short_capable`: replaced fixed `lookback=252` with the
   full pre-registered `PARAM_GRID` (`{"lookback": [126, 189, 252]}`) plus
   `allow_short=True`. A fixed lookback=252 was incompatible with 12-month test
   windows (~252 trading days) → `pct_change(252)` NaN everywhere → zero
   positions → all metrics NaN → tests passed vacuously.
2. Both `run_borrow_cost_sweep_short_capable` and
   `run_regime_cost_sweep_short_capable`: added explicit non-vacuity
   assertions (sharpe/return/DSR p-value must not be None at any level) and
   made the directional-claim assertions unconditional.
3. Both test files: same non-vacuity guards, directional assertions no longer
   guarded by `is not None`.

## What was actually verified (evidence)
- Corrected borrow-cost sweep (short-capable, allow_short=True, full grid):

  | borrow /yr | OOS Sharpe | Total Return | DSR p-value | Verdict |
  |------------|-----------|-------------|-------------|---------|
  | 0.00%      | 1.4026    | 0.7975      | 0.4498      | NOT SUPPORTED |
  | 1.00%      | 1.3899    | 0.7844      | 0.4572      | NOT SUPPORTED |
  | 3.00%      | 1.3645    | 0.7584      | 0.4721      | NOT SUPPORTED |
  | 5.00%      | 1.3390    | 0.7329      | 0.4871      | NOT SUPPORTED |

  Directional claim HOLDS: monotonic degradation. DSR criterion fails at every
  level → hypothesis NOT SUPPORTED at all levels. This matches the audit's
  corrected numbers exactly (AUDIT_BORROW_COST_REALISM.md).

- Corrected stressed-regime cost sweep (short-capable, borrow=3%):

  | regime mult | OOS Sharpe | Total Return | DSR p-value | Verdict |
  |-------------|-----------|-------------|-------------|---------|
  | 1.0         | 1.3645    | 0.7584      | 0.4721      | NOT SUPPORTED |
  | 2.0         | 1.3576    | 0.7516      | 0.4762      | NOT SUPPORTED |
  | 5.0         | 1.3371    | 0.7312      | 0.4885      | NOT SUPPORTED |
  | 10.0        | 1.3026    | 0.6975      | 0.5091      | NOT SUPPORTED |

  Directional claim HOLDS: monotonic degradation. DSR fails at every level.

- Full results JSON: `skills/quantitative-backtesting/examples/short_capable_sweeps_corrected_results.json`.
- Tests: both short-capable tests PASS with non-vacuous assertions (2 passed,
  4.63s). Adjacent TSMOM sweeps (borrow/funding long-flat, cost sensitivity,
  capacity) still pass (3 passed, 15.84s) → no regression.
- Environment: `source /tmp/venv/bin/activate` (Python 3.14.4, pytest 9.2.0).

## Approaches already failed (do not repeat)
- Fixed `lookback=252` for short-capable sweeps on 12-month test windows.
- Interpreting vacuous test passes (None-skipping assertions) as evidence.

## What remains unresolved
- No live/out-of-sample market data: all numbers are on committed fixtures
  (AAPL/MSFT/GOOGL 2020-2025) and are sensitivity analyses, not profitability
  claims. No claim beyond the test scope is made.
- The hypothesis remains NOT SUPPORTED (DSR criterion fails at all cost
  levels); this is the honest outcome and is correctly reported.

## One precise next task
See `HANDOFF_SESSION_NEXT.md`.

(End of file - total 49 lines)