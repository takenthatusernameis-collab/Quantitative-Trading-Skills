# Handoff — Next Session

## Status
- HEAD `4a4f18d` (main); working tree clean except one untracked additive file:
  `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`
  (verified green via direct `python3`; not committed).
- Quant gate baseline green (SESSION_159, 1782 tests; ~1787 collected incl. the two
  additive files since, all individually verified with 0 failures except 9 pre-existing
  `test_reporting.py` environment failures).
- Cross-sectional momentum on the triple panel now has capacity/liquidity-sensitivity
  coverage (was the one missing sensitivity dimension for that family on the triple).

## One precise next task (bounded, evidence-based)
**Add capacity/liquidity sensitivity for simple momentum on the committed triple panel
(AAPL/MSFT/GOOGL).** Simple-momentum *pairs* already have capacity-sensitivity tests, but
the triple panel does not — mirror the cross-sectional momentum test just added.
- File to create:
  `skills/quantitative-backtesting/tests/test_simple_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`
- Pattern: `walk_forward_analysis(..., impact_coefficient=level)` sweeping
  `[0.0, 0.05, 0.1, 0.2]` on the committed triple panel; assert `capacity=None` at impact
  `0.0`, finite positive capacity at impact > 0, and monotonic fall as impact rises.
- Constraint: confirm the panel pricing mode (`book` vs `net-exposure`) by inspecting
  `tests/test_simple_momentum_benchmark_aware_real_triple_aapl_msft_googl.py` first and use
  the same mode as that pinned test.
- Offline, committed fixtures only
  (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`); no live network; no
  engine/fixture/default-JSON change; additive test only; do not commit unless explicitly
  asked.
- Verify via direct `python3 <test_file>` (the walk-forward test convention); expect "OK".

## Constraints
- Additive only: do not modify engine, default JSON, or pinned matrices; do not weaken any
  safety/PIP controls.
- No profitability or capacity claim; capacity is an execution-side control.
- If slow, bound the run; if it cannot complete in-session, leave the passing direct-`python3`
  evidence and hand off the pytest-collectability check.

(End of file)
