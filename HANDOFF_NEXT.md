# Handoff — EMA crossover walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_real_aapl.py` — walk-forward OOS falsification test for EMA crossover on AAPL with pre-registered grid, costs, point-in-time validation, DSR. 2 passed.

## What was verified
- EMA crossover WF on AAPL: Sharpe 0.625, total return +155.88%, DSR p=0.3927 >= 0.10 → NOT SUPPORTED. Focused gate passed.

## What remains unresolved
- All tested families fail DSR p < 0.10 on committed fixtures (AAPL/MSFT/GOOGL). No profitability/robustness claims warranted.

## Approaches already tried / failed
- Followed established test pattern; no new failures.

## One precise next task
Add `skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py` for MACD walk-forward falsification on AAPL. Use pre-registered grid (e.g. fast_period=[12], slow_period=[26], signal_period=[9]), same WF/costs/PIT/DSR setup, pin metrics, assert NOT SUPPORTED, run focused gate.

Evidence/constraints:
- MACD in registry; committed fixtures in `skills/quantitative-backtesting/assets/example_data/real_market_data/`
