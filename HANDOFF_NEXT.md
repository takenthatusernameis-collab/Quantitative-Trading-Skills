# Handoff — next task: resolution / Deflated Alpha edge-case regression test

## What changed
- The prior session's capacity-invariant task is complete:
  `skills/quantitative-backtesting/tests/test_walk_forward.py` now asserts
  `abs(capacity_notional_weighted / capacity_book - n_assets) < n_assets * 0.05`
  with `n_assets = 4`, derived from the observed `|dw| = 0.25 = 1/n_assets` (measured ratio = 4.0x across all 11
  periods). Full `test_walk_forward.py` slow suite: 185 passed, 0 failed.

## One precise next task
- Add ONE bounded regression test for a resolution / Deflated Alpha edge case in
  `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` (e.g. behavior when alpha cannot be
  priced or benchmarks are degenerate).
- Relevant files:
  - `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`
  - `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`
  - `skills/quantitative-backtesting/scripts/capture_resolution_floor.py`
- Identify the exact minimal test, run only affected tests, record evidence. Do not commit unless explicitly asked.
