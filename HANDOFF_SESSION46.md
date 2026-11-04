# Handoff — Donchian benchmark-aware falsification guards added

## What changed
- Added `skills/quantitative-backtesting/examples/donchian_breakout_hypothesis.py` (benchmark-aware + elevated cost sweep + param sensitivity), mirroring MACD/dual momentum patterns.
- Added `skills/quantitative-backtesting/tests/test_donchian_breakout_benchmark_aware_real_aapl.py` (structural + pinned assertions, verdict stays NOT SUPPORTED).

## What was actually verified
- `test_donchian_breakout_benchmark_aware_real_aapl.py` + `test_walk_forward_donchian_real_aapl.py` → 4 passed, 0 failed.
- Observed (committed fixtures only): OOS Sharpe ~0.839 > 0 but fails vs buy-and-hold (48.81% vs 77.43%), deflated Sharpe p-value high, alpha p-value > 0.05; verdict NOT SUPPORTED. Elevated cost sweep remains SUPPORTED at higher costs on this window (sensitivity noted).

## What remains unresolved
- EMA and Bollinger single-asset families still lack benchmark-aware + elevated-cost-sweep + param-sensitivity guards (next candidates).

## Approaches already tried / failed
- None this session.

## One precise next task
Add benchmark-aware + elevated-cost-sweep + param-sensitivity falsification guards for EMA crossover on committed AAPL, mirroring `donchian_breakout_hypothesis.py` / `macd_hypothesis.py` (create `examples/ema_cross_hypothesis.py`, add tests, verify offline with committed fixtures; do not claim profitability).
