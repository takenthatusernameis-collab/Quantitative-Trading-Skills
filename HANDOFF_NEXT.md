# Handoff — next task: harden benchmark total-return edge cases

## What changed
- Added regression tests in `skills/quantitative-backtesting/tests/test_data_loader.py` locking `_compute_benchmark_total_return` behavior for dividends, adj_close, and price-only paths.

## What was actually verified
- `pytest tests/test_data_loader.py -k benchmark_total_return`: 7 passed.

## What remains unresolved
- No code change; tests lock existing behavior. Consider verifying dividend yield convention (prior close denominator) against a real vendor sample.

## One precise next task
- Inspect `_adjust_for_splits` and add a regression test for a 2-for-1 split adjustment, verifying pre-split prices divided by ratio.
