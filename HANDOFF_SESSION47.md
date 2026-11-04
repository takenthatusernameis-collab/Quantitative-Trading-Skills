# Handoff — EMA and Bollinger benchmark-aware guards already present; next candidate mean reversion

## What changed
- Verified `test_ema_cross_benchmark_aware_real_aapl.py` and `test_bollinger_bands_benchmark_aware_real_aapl.py` pass (2 each) against committed AAPL fixtures.
- EMA and Bollinger already include benchmark-aware + elevated-cost-sweep + param-sensitivity guards.

## What remains unresolved
- `mean_reversion_hypothesis.py` and `simple_momentum_hypothesis.py` still lack benchmark-aware + elevated-cost-sweep + param-sensitivity guards mirroring `donchian_breakout_hypothesis.py` / `macd_hypothesis.py`.

## One precise next task
Add benchmark-aware + elevated-cost-sweep + param-sensitivity falsification guards for mean reversion on committed AAPL, mirroring `donchian_breakout_hypothesis.py`, with pinned regression tests; do not claim profitability.
