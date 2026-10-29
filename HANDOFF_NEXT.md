# Handoff — zscore cost-sensitivity on MSFT/GOOGL real window

## What changed
- Added tests/test_zscore_cost_sensitivity_real_msft_googl.py: builds a combined two-symbol CSV from committed real-market MSFT.csv and GOOGL.csv and runs run_cost_sweep, asserting the cost sweep completes and records all five ascending levels.

## What was actually verified
- Test passes (4.67s); cost sweep monotonicity assertions hold.

## What remains unresolved
- The pair is not cointegration-tested; verdict stability semantics depend on run_backtest metrics availability. No claim of profitability.

## One precise next task
- Add a full falsifiable hypothesis test (run_hypothesis_test) on the MSFT/GOOGL combined real window asserting separation invariants and verdict reporting.
