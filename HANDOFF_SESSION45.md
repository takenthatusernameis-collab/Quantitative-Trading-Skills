# Handoff — MACD benchmark-aware falsification guards verified

## What changed
- Verified `skills/quantitative-backtesting/examples/macd_hypothesis.py` and `tests/test_macd_benchmark_aware_real_aapl.py` already present and green.
- Focused no-regression gate: `test_macd_benchmark_aware_real_aapl.py` + `test_walk_forward_macd_real_aapl.py` + `test_examples_coverage.py` → 47 passed, 0 failed.

## What was actually verified
- MACD benchmark-aware test: 2 passed; walk-forward MACD + examples coverage: 47 passed total.

## What remains unresolved
- Donchian, EMA, Bollinger single-asset families still lack benchmark-aware + elevated-cost + param-sensitivity guards (next candidates).

## One precise next task
Add benchmark-aware + elevated-cost-sweep + param-sensitivity falsification guards for Donchian breakout on committed AAPL, mirroring macd_hypothesis.py / dual_momentum_hypothesis.py.
