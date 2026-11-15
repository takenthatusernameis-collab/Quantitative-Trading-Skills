# Handoff: next task (session ending 2026-11-15, session 119)

## State of baseline
- **Full gate GREEN**: session 119 ran `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1453 passed, 0 failed, EXIT 0, 32:19** (4 CPUs). Log: `/home/runner/work/_temp/kilo-tmp/kilo/gate_session119.log`. Gate artifacts reverted; tree clean at HEAD `65fc8f5`.
- Session 119 itself changed no source code; only uncommitted files are `HANDOFF_SESSION119.md` and this file (left uncommitted per instruction).
- Environment note: `pytest-xdist` is not preinstalled in fresh containers; `pip install pytest-xdist` first. Serial full gate times out (~60 min) — use `-n 4`.

## One precise next task
Implement **time-series momentum (TSMOM-style)** as a new standalone, falsifiable hypothesis (it exists today only as a base layer inside `KellyCriterion`/`VolatilityTargeting`, `skills/quantitative-backtesting/scripts/strategy_builder.py:1398,1456`):

1. Add `TimeSeriesMomentumStrategy` (e.g. long/flat on sign of trailing 12-month return) to `strategy_builder.py`, following the `StrategyBase` pattern (`DualMomentumStrategy`, line 669).
2. Pin falsification criteria BEFORE running (anti-tuning rule; mirror `tests/test_pin_criteria_consistency.py` pin pattern), then evaluate on the committed real AAPL/MSFT/GOOGL panel via walk-forward, net of existing cost models (`scripts/cost_models.md`), vs buy-and-hold; report `test_resolution`.
3. Add tests following `examples/volatility_targeting_hypothesis.py` / `test_walk_forward_*_benchmark_aware_*` patterns.
4. Verify: focused tests, then full gate `-n 4` (expect EXIT 0, ~32 min). Revert dirtied `examples/example_output/*`, `scripts/results/*` with `git checkout -- .`. Do not commit unless explicitly asked.

## Constraints and evidence
- Do not flip criterion/verdict assertions to force green (honesty / anti-tuning rule).
- Prior failures: serial gate (timeout), chunked runs (fallback only). See `HANDOFF_SESSION119.md` for full detail.