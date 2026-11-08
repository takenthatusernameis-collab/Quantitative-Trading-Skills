# Handoff — next session

## What changed (this session)
- Verified the four kelly_criterion falsification regression tests on the committed AAPL fixture already exist and pass: hypothesis, benchmark-aware (DSR N=...), elevated-cost sweep, param-sensitivity sweep. Result: 6 passed in 36.9s. No files modified.

## What was actually verified
- `python3 -m pytest ...test_kelly_criterion_{hypothesis,benchmark_aware,elevated_cost,param_sensitivity}_real_aapl.py` → 6 passed, EXIT 0.

## What remains unresolved
- Falsification coverage gap for `bollinger`: only cpcv test exists; missing hypothesis/benchmark-aware/elevated-cost/param-sensitivity tests on committed AAPL fixture, following ema/sma crossover patterns.

## One precise next task
Add the four missing falsification regression tests for `bollinger` on the committed AAPL fixture, modeled on the donchian/macd patterns: hypothesis, benchmark-aware (with DSR N=...), elevated-cost sweep, and param-sensitivity sweep. Pin metrics with rel tol 1e-3, never exact equality. Do not commit unless explicitly asked.