# Handoff — Next Task (2026-11-21): Move from cost-realism sweeps to a fresh real-data hypothesis thread

## Context
Session 150 fixed the short-capable TSMOM sweep lookback bug (see
`HANDOFF_SESSION_CURRENT.md`). Both borrow-cost and stressed-regime cost
sweeps now produce real, non-NaN, monotonic-degradation results; DSR criterion
fails at all levels → hypothesis NOT SUPPORTED (correctly reported). Evidence:
`skills/quantitative-backtesting/examples/short_capable_sweeps_corrected_results.json`.

The borrow/funding/capacity/regime-cost sensitivity threads on the AAPL/MSFT/
GOOGL triple panel are now well-covered and honest. Do NOT re-audit them
without new evidence.

## Precise next task
Pick ONE fresh, bounded quant-methodology task that materially improves our
ability to form, test, falsify, or compare quantitative trading methodologies.
Concrete candidate (recommended):

1. **Cross-sectional momentum on the same real triple panel with honest
   multiple-testing control.** `skills/quantitative-backtesting/examples/cross_sectional_momentum_hypothesis.py`
   exists — audit it the same way session 150 audited TSMOM: does it use a
   pre-registered grid, chronological walk-forward, net-of-cost OOS reporting,
   and a Deflated Sharpe / reality-check correction? If any of those are
   missing or broken, fix with the smallest reversible change and report
   corrected numbers. If it is already sound, state that with evidence and
   move to the next candidate below.

2. **Purged/embargoed CV vs walk-forward comparison.** The skill has CPCV
   (`test_cpcv_dual_momentum_real_aapl_googl_structure.py` notes lookback=252
   exceeds ~100-bar CPCV windows — same class of bug just fixed). Audit
   whether any CPCV example/test uses lookbacks incompatible with its
   window and produces vacuous NaN metrics; fix if so.

## Constraints
- Offline committed fixtures only (`skills/quantitative-backtesting/assets/example_data/real_market_data/`); no live network.
- Reuse existing walk_forward / cost / DSR machinery; no new frameworks.
- Do not commit unless asked.
- No profitability claim beyond what the test shows; separate hypothesis,
  implementation, verified results, and unresolved assumptions.
- Environment: `source /tmp/venv/bin/activate` (pytest 9.2.0 available).

## Success criteria
- A concrete methodological defect found and fixed (or a sound component
  verified with evidence), with non-vacuous assertions and corrected numbers
  recorded in a results JSON + handoff.
- Focused tests pass non-vacuously; adjacent tests re-run to confirm no
  regression.

## Evidence locations
- `skills/quantitative-backtesting/examples/short_capable_sweeps_corrected_results.json`
- `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`
- `AUDIT_BORROW_COST_REALISM.md`
- This session's handoff: `HANDOFF_SESSION_CURRENT.md`

(End of file - total 47 lines)