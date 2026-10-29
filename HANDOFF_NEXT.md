# Handoff — walk-forward determinism regression test

## What changed
- Added `test_walk_forward_determinism_across_repeated_runs` to `skills/quantitative-backtesting/tests/test_walk_forward.py` (and registered it). The test asserts identical split boundaries/selected params/OOS Sharpe and deflated Sharpe across repeated runs of `walk_forward_analysis`, `out_of_sample_validation` (walk-forward), and `cpcv_analysis`.

## What was actually verified
- `python -m pytest tests/test_walk_forward.py -k determinism -v` → PASSED (1 passed).
- Existing walk-forward logic uses fixed iteration order (no RNG in grid search/splitting) and the regression test confirms determinism holds.

## What remains unresolved
- None for this bounded task. The walk-forward module appears deterministic under the tested paths.

## One precise next task
- Extend determinism coverage to `monte_carlo_simulation` output shape/ordering if needed (note in test says monte_carlo excluded because it's a distribution; only block-size selection pinned elsewhere) — or alternatively add a quick check that `cpcv_analysis` with default params remains deterministic on a fixed seed/data in a separate small test. File: `skills/quantitative-backtesting/tests/test_walk_forward.py`. Bounded, offline.
