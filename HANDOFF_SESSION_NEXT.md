# Handoff — Next Session

## Status
- HEAD `4a4f18d` (main); working tree clean except one modified test file:
  `skills/quantitative-backtesting/tests/test_simple_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`
  (verified green via direct `python3` and `pytest`; not committed).
- Quant gate baseline green (SESSION_159, 1782 tests; ~1787 collected incl. the two
  additive files since, all individually verified with 0 failures except 9 pre-existing
  `test_reporting.py` environment failures).
- Simple momentum on the triple panel now has capacity/liquidity-sensitivity coverage
  via walk-forward analysis with panel pricing (was the one missing sensitivity dimension
  for that family on the triple). Cross-sectional momentum and TSMOM triple-panel
  capacity tests already green.

## One precise next task (bounded, evidence-based)
**Add capacity/liquidity sensitivity for EMA crossover on the committed triple panel
(AAPL/MSFT/GOOGL).** EMA crossover has pair-level capacity-sensitivity tests, but the
triple panel does not — mirror the simple momentum test just added.
- File to create:
  `skills/quantitative-backtesting/tests/test_ema_crossover_capacity_sensitivity_real_triple_aapl_msft_googl.py`
- Pattern: `walk_forward_analysis(..., panel_pricing="book", impact_coefficient=level)`
  sweeping `[0.0, 0.05, 0.1, 0.2]` on the committed triple panel; assert `capacity=None`
  at impact `0.0`, finite positive capacity at impact > 0, and monotonic fall as impact rises.
- Use the existing `ema_crossover` strategy from `strategy_builder` (supports panel data
  via equal-weighted mean of per-asset signals, similar to `time_series_momentum`).
- Offline, committed fixtures only (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`);
  no live network; no engine/fixture/default-JSON change; additive test only.
- Verify via direct `python3 <test_file>` (the walk-forward test convention); expect "OK".

## Constraints
- Additive only: do not modify engine, default JSON, or pinned matrices; do not weaken any
  safety/PIP controls.
- No profitability or capacity claim; capacity is an execution-side control.
- If slow, bound the run; if it cannot complete in-session, leave the passing direct-`python3`
  evidence and hand off the pytest-collectability check.

(End of file)