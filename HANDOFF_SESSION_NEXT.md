# Handoff — Next Task (2026-11-21): audit cross-sectional momentum cost/borrow realism on real triple panel

## Context
The synthetic `fat_tail_crash` regime-detector thread is CLOSED (`HANDOFF_SESSION_149.md`).
All detector variants fail to beat uniform target_vol=0.20, and uniform-tv
experiments are provably regime-independent (OOS Sharpe identical across all
threshold/window settings). Do not continue tuning detectors on this synthetic
scenario.

## Precise next task (pick ONE, bounded, verifiable this session)
**Audit one existing real-data walk-forward result for cost realism and honest
out-of-sample reporting.** Concretely:
- Open `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py`
  (and the module it exercises).
- Determine whether its stated conclusion survives net-of-cost / borrow / capacity,
  and report the net numbers with a clear hypothesis-vs-result separation.
- Make NO profitability claim beyond what the test itself demonstrates.

Alternative (only if a fresh hypothesis is preferred): state a new testable
hypothesis with an EXPLICIT falsification criterion and a chronological
train/validation/test split BEFORE writing code.

## Constraints / evidence
- Reuse `detect_combined_regime` + `walk_forward_analysis` + existing cost models;
  do not add new frameworks for their own sake.
- Synthetic experiments: keep the no-significance/no-profitability discipline.
- Do NOT commit unless the user asks.
- Environment: `source /tmp/venv/bin/activate` (pytest is available; pandas 3.1.1, numpy 2.5.5).
- Working tree currently has session 149's uncommitted changes; inspect
  `git status`/`git diff` before checkpointing.
- See `HANDOFF_SESSION_149.md` for full results, per-setting table, and the list
  of already-failed approaches.