# Handoff — session 2026-10-27 (follow-up 3)

## What changed
- `skills/quantitative-backtesting/tests/test_strategy_cost_model.py` — fixed the
  failing test added in commit ea08c5b (`test_market_impact_reduces_returns_market_neutral_pairs_portfolio`)
  and added one more focused regression test.

  Root cause of the failure: the test's `positions` were **all zero**. It built
  `positions = (sig_a - sig_b) * 2` with `sig_a = sig_b = 1.0`, so the position
  series was identically 0.0 — no position change, no notional traded, so
  `market_impact_cost` returned a zero impact term and `on == off` (both
  0.0000%). The test was committed broken and would have caught nothing even
  had it passed, because a zero-turnover signal cannot exercise the impact
  machinery at all.

  Fix: replaced the constant-zero signal with a long/short-flipping signal on
  a 2-asset dict panel, which has full turnover and exercises the per-asset
  `is_panel=True` branch of `market_impact_cost` (the path that divides the
  portfolio notional across `n_assets` and measures each constituent against
  its own ADV). Verified `impact=5.0 -> -69.97%` vs `off -> +3.97%`.

  Added `test_dict_panel_constant_position_pays_no_per_bar_impact_after_entry`:
  a constant non-zero position on a dict panel trades only once (at entry), so
  per-bar market impact after the warmup must be exactly zero — guards that the
  per-asset ADV division does not manufacture spurious impact from a static
  position. Asserts the net return equals `positions * raw_returns` to
  `atol=1e-12`.

## What was actually verified
- `skills/quantitative-backtesting/tests/test_strategy_cost_model.py` → 18/18
  passed (was 16/17 before the fix; the 17th was the broken test).
- `skills/quantitative-backtesting/tests/test_examples_coverage.py` → 39/39
  passed (27.82s), unchanged baseline.
- `py_compile` of the test file → OK.
- `test_walk_forward.py` does not import `test_strategy_cost_model`, so the
  slow suite is unaffected by this change; it was not re-run this session
  (prior handoff: 185 passed / 0 failed).

## What remains unresolved
- No independent out-of-sample evidence beyond synthetic fixtures (unchanged).
- `test_walk_forward.py` slow suite not re-run this session; presumed unaffected
  (no import dependency on the cost-model test file).

## Approaches already tried / failed
- Commit ea08c5b added `test_market_impact_reduces_returns_market_neutral_pairs_portfolio`
  with a zero-turnover signal; it failed at `assert on < off` with both values
  0.0000%. Diagnosed by reproducing the assertion directly and inspecting
  `positions.unique()` rather than guessing at the cost model. The fix is a
  materially different signal (flipping long/short), not a retry of the same
  assertion.

## One precise next task
- Re-run the full `test_walk_forward.py` slow suite to confirm no regression
  (185 passed / 0 failed expected), then pick one bounded quant research task.
  Candidate: extend the falsifiable hypothesis example
  (`skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`)
  with a cost-sensitivity sweep that reports how the verdict changes as
  transaction costs rise, with explicit falsification criteria. Do not commit
  unless explicitly asked.