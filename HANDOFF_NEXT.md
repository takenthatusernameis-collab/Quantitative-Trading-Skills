# Handoff — zscore hypothesis + cost sensitivity on MSFT/GOOGL real window

## What changed
- Verified existing tests pass: test_zscore_hypothesis_real_msft_googl.py, test_zscore_cost_sensitivity_real_msft_googl.py.

## What was actually verified
- 2/2 passed (2.86s); verdict separation invariants and cost sweep monotonicity hold.

## What remains unresolved
- Pair not cointegration-tested; verdict stability semantics depend on run_backtest metrics.

## One precise next task
- Add focused real-market tests on committed GOOGL/MSFT single-asset or multi-asset panel using falsifiable machinery; or implement bounded fetch in data_loader.py honoring 429/backoff against local mock.
