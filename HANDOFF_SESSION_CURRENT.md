# Handoff — Current State (2026-11-21): TSMOM borrow/funding-cost realism audit COMPLETE

## Baseline
- HEAD `569ff2f`, branch `main`. Working tree has this session's UNCOMMITTED
  changes only (do NOT commit unless asked):
  - `AUDIT_BORROW_COST_REALISM.md` (new audit report)
- Focused tests (borrow_cost_realism_short_capable, borrow_funding_cost_sweep, regime_cost_sweep_short_capable, capacity_sensitivity) → all pass (but short-capable sweeps pass vacuously due to bug).

## Where the thread landed
- **CRITICAL BUG**: Short-capable sweeps (`run_borrow_cost_sweep_short_capable`, `run_regime_cost_sweep_short_capable`) use fixed `lookback=252` incompatible with 12-month test windows (~252 trading days). All signals NaN → zero positions → all metrics NaN. Tests pass vacuously (directional assertions skipped when metrics are None).
- **CORRECTED RESULTS** (using proper grid [126, 189, 252] with `allow_short=True`):
  - Frictionless: OOS Sharpe=1.40, Total Return=0.80, DSR p=0.45
  - 5% borrow: OOS Sharpe=1.34, Total Return=0.73, DSR p=0.49
  - **Directional claim HOLDS**: Higher borrow cost monotonically reduces net performance.
  - **Hypothesis NOT SUPPORTED at all levels**: Deflated Sharpe criterion (p < 0.10) fails (all p > 0.44).
  - 2/3 pre-registered criteria pass (Sharpe > 0, Return > 0), but DSR fails.
- **Borrow/Funding sweep (long/flat)**: Works correctly, negative performance at all levels, NOT SUPPORTED.
- **Capacity sweep**: Works correctly, capacity falls with impact.

## Approaches already failed (do not repeat)
- Using fixed `lookback=252` for short-capable sweeps with 12-month test windows.
- Interpreting vacuous test passes as evidence.

## One precise next task
See `HANDOFF_SESSION_NEXT.md`.

(End of file - total 23 lines)