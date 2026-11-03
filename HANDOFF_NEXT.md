# Handoff — dual momentum vs cross-sectional momentum comparison added

## What changed
- Added `skills/quantitative-backtesting/examples/compare_dual_vs_cross_sectional_triple.py` to compare dual momentum vs cross-sectional momentum on the committed triple (AAPL/MSFT/GOOGL) with same split/costs/benchmark.
- Ran comparison (OOS test, net of 3bps, benchmark MSFT):
  - dual_momentum: Sharpe 1.1677, total_return 0.4083, maxDD -0.1055; benchmark TR 0.9015; alpha/deflated_sharpe p None in this direct CLI run (benchmark-aware criteria handled in hypothesis scripts)
  - cross_sectional_momentum: Sharpe 0.3297, total_return 0.0864, maxDD -0.0795; benchmark TR 0.9015

## Verified
- `python -m pytest tests/test_dual_momentum_* -q` in skills/quantitative-backtesting → 8 passed (benchmark-aware test pinned and passing).
- Comparison script executed successfully on committed fixtures.

## What remains unresolved
- Both underperform strong buy-and-hold MSFT on this window; need to assess if any configuration/robustness treatment can meet falsification criteria or justify different benchmark.
- Walk-forward/CPCV deeper runs may take long; partial/slow tests need targeted runs.

## Failed approaches
- None new. Previous benchmark-aware dual momentum correctly returned NOT SUPPORTED with honest metrics.

## Precise next task
Add a worked example showing walk-forward for both strategies on the same triple (or extend comparison to walk-forward) with same costs/benchmark and report OOS aggregate metrics net of costs; verify with a quick targeted test if exists.
