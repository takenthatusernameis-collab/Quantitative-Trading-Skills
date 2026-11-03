# Handoff — MACD walk-forward falsification guard added

## What changed
- Added `skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py` — MACD walk-forward falsification on AAPL with pre-registered grid, costs, PIT, DSR. 2 passed.

## What was verified
- MACD WF on AAPL: Sharpe 0.1388, total return +20.31%, DSR p=0.8487 >= 0.10 → NOT SUPPORTED. Focused gate passed.
- `test_walk_forward.py` + `test_strategy_builder.py` still green (76 tests).

## What remains unresolved
- All tested families fail DSR p < 0.10 on committed fixtures (AAPL/MSFT/GOOGL). No profitability/robustness claims warranted.

## Approaches already tried / failed
- Followed established test pattern; no new failures.

## One precise next task
Verify walk-forward coverage inventory is complete for the panel/multi-asset strategy families; if a gap exists, add the matching walk-forward falsification test following the established pattern.

Evidence/constraints:
- MACD in registry; committed fixtures in `skills/quantitative-backtesting/assets/example_data/real_market_data/`
- New test: `skills/quantitative-backtesting/tests/test_walk_forward_macd_real_aapl.py` (2 passed)

(End of file - total 19 lines)