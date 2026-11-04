# Handoff — next task

## What changed (this session)
Executed the assigned bounded task: added the two missing MACD single-asset sweep regression guards.
- Added `skills/quantitative-backtesting/tests/test_macd_param_sensitivity_real_aapl.py` (new), mirroring the EMA param-sensitivity test (6 pre-registered MACD fast/slow/signal settings, single-asset AAPL, relative-tolerance pinned metrics, honest verdict asserted).
- Corrected the docstring of the pre-existing `skills/quantitative-backtesting/tests/test_macd_elevated_cost_real_aapl.py` ("long/flat" → "long/short"; methodological note now cites the benchmark-aware p-values).
- No source/test files modified beyond these; working tree clean except the two new/edited test files.

## What was actually verified
- Focused gate: MACD elevated-cost + param-sensitivity + benchmark-aware + walk-forward → **6 passed, 0 failed** in 15.22s.
- No-regression gate across the other single-asset families (ema_cross incl. its sweep guards, bollinger_bands, donchian_breakout, simple_momentum, mean_reversion benchmark-aware) → **14 passed, 0 failed** in 37.20s.
- Honest findings recorded: MACD is NOT SUPPORTED at every tested cost level on committed AAPL, and mixed across the six pre-registered parameter settings (only (16,34,12) and (12,26,12) pass the weak 2-criterion sweep; the benchmark-aware guard pins NOT SUPPORTED, alpha p=0.60, deflated Sharpe p=0.96). No profitability claim.

## What remains unresolved
- Four families still lack pinned elevated-cost-sweep + param-sensitivity regression guards despite having the sweep machinery in their example scripts: bollinger_bands, donchian_breakout, mean_reversion, simple_momentum.

## One precise next task
Pin the elevated-cost-sweep and parameter-sensitivity regression guards for the remaining four single-asset families. Start with `bollinger_bands_hypothesis.py`:
1. Add `tests/test_bollinger_bands_elevated_cost_real_aapl.py` and `tests/test_bollinger_bands_param_sensitivity_real_aapl.py`, mirroring the two new MACD tests above (single-asset AAPL, relative-tolerance pinned metrics, honest verdict asserted — do not tune to force SUPPORT). Capture pinned metrics by running the sweep functions first; do not guess them.
2. Verify with a focused gate: the two new tests + `test_bollinger_bands_benchmark_aware_real_aapl.py` + `test_walk_forward_bollinger_real_aapl.py`.
3. Repeat for donchian_breakout, mean_reversion, simple_momentum if time permits; otherwise hand off after one.

Constraints: offline, committed fixtures only, no tuning to force SUPPORT, smallest reversible change.

(End of file - total 24 lines)