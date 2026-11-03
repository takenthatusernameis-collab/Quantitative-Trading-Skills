# Handoff — next task

## What changed (this session)
Prior agent's assigned task (benchmark + Deflated Sharpe for dual momentum on the committed triple) is already implemented and verified green. This session fixed 10 deterministic test regressions (9 matplotlib missing-dependency in test_reporting.py; 1 VolatilityTargeting/KellyCriterion constructor mismatch in strategy_builder.py) so the bounded quant-backtesting suite is green. See HANDOFF.md for details.

## One precise next task
Add benchmark-aware (alpha p-value + Deflated Sharpe multiple-testing correction) falsification test + pinned regression guard for RSI mean reversion on the committed triple panel (AAPL/MSFT/GOOGL), following the established dual-momentum/z-score pattern:
1. Extend `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py` with benchmark-aware machinery (`BENCHMARK_FILE="MSFT.csv"`, `BENCHMARK_CRITERIA`, `N_TRIALS`, `run_benchmark_aware_hypothesis_test`) — it currently only has basic `run_hypothesis_test`.
2. Add `skills/quantitative-backtesting/tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py` pinning strategy + benchmark metrics (net of costs, relative tolerance) and asserting the honest NOT SUPPORTED verdict (do not tune to force SUPPORT).
3. Run the new test + existing RSI tests; confirm green, no regressions.

Evidence/constraints:
- Offline, committed fixtures only; MSFT as buy-and-hold benchmark; relative tolerance only; no tuning to force SUPPORT.
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 (+matplotlib installed); `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Relevant files: `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py`, `skills/quantitative-backtesting/examples/dual_momentum_hypothesis.py` (pattern to mirror), `skills/quantitative-backtesting/tests/test_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py` (pattern to mirror).
