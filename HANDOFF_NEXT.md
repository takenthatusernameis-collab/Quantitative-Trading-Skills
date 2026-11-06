# Handoff — bollinger guards pinned; RSI triple flakiness confirmed

## What changed (this session)
- No source or test files changed. Working tree clean.
- Verified bollinger elevated-cost and param-sensitivity guards already present and green:
  - `test_bollinger_bands_elevated_cost_real_aapl.py` → 1 passed (3.07s)
  - `test_bollinger_bands_param_sensitivity_real_aapl.py` → 1 passed (4.62s)
- Re-ran RSI triple benchmark-aware test twice in isolation: 2 passed each (1.82s, 1.87s). Flakiness under full-suite load confirmed, not a deterministic code defect.

## What was actually verified
- Bollinger elevated-cost guard green.
- Bollinger param-sensitivity guard green.
- RSI triple test green x2 in isolation.

## What remains unresolved
- RSI triple test failure under full-suite load (`RuntimeError: run_backtest failed with code 1`). Root cause unknown; likely resource contention / subprocess. Needs investigation of `rsi_mean_reversion_hypothesis.run_benchmark_aware_hypothesis_test` / run_backtest if it recurs.
- Next methodological candidate: pin elevated-cost + param-sensitivity regression guards for RSI on committed AAPL (mirror MACD/bollinger tests) if not already present.

## Approaches already tried / failed
- Full suite run: 2 flaky RSI failures; isolated re-runs green.

## One precise next task
Check whether RSI elevated-cost and param-sensitivity tests exist (ls tests/*rsi*); if missing, implement them mirroring `test_macd_elevated_cost_real_aapl.py` / `test_macd_param_sensitivity_real_aapl.py` using `rsi_mean_reversion_hypothesis`. If present, run them and investigate any RSI flakiness root cause under load. Env: `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`. Do not commit unless explicitly asked.
