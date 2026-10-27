# Handoff — next task: investigate notional-weighted capacity invariant failure

## What changed
- Ran slow framework suite. `test_walk_forward.py`: 184 passed, 1 failed.
- Failing: `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`
  - `assert summary["capacity_notional_weighted"] < summary["capacity_book"] * 2.0`
  - actual: 21864161.55 < 10932080.77 is False (4.0x)

## What was actually verified
- Failure is deterministic, not transient. Root cause in `utils.book_capacity_estimate`: notional-weighted capacity = max_impact*ADV/(coeff*dw^2), panel capacity = max_impact*ADV/(coeff*|dw|); ratio = 1/|dw|. For fractional trades |dw|<0.5 the notional-weighted reading exceeds 2x the panel reading by construction. The test's 2.0x threshold assumes |dw|>=0.5, which this fixture's book does not satisfy.

## One precise next task
- Decide whether the invariant threshold should be derived from observed |dw| (e.g. assert ratio <= 1/min_trade) or whether the fixture should use larger trade sizes; do not weaken the test without evidence. Relevant: `skills/quantitative-backtesting/scripts/utils.py:book_capacity_estimate`, test at `tests/test_walk_forward.py:7620`.
" filePath="/home/runner/work/Quantitative-Trading-Skills/Quantitative-Trading-Skills/HANDOFF_NEXT.md