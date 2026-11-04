# Handoff — RSI mean reversion elevated-cost-sweep + param-sensitivity guards added

## What changed (this session)
- Added `skills/quantitative-backtesting/tests/test_rsi_mean_reversion_elevated_cost_real_aapl.py` (new file): runs `run_elevated_cost_sweep` on committed single-asset AAPL, pins per-cost-level Sharpe/total_return at rel tol 1e-3, asserts verdict structure (two criteria: oos_sharpe_gt_zero, oos_total_return_positive), ascending cost levels, honest verdict (NOT SUPPORTED at every level). No profitability claim.
- Added `skills/quantitative-backtesting/tests/test_rsi_mean_reversion_param_sensitivity_real_aapl.py` (new file): runs `run_param_sensitivity_sweep` on committed single-asset AAPL, pins per-setting Sharpe/total_return at rel tol 1e-3 across the 5-setting PARAM_SENSITIVITY_GRID ((14,30,70),(10,30,70),(20,30,70),(14,25,70),(14,35,70)), asserts verdict structure and advertised 3bp costs. Honest verdict (NOT SUPPORTED at every setting).
- Mirrored the MACD/Bollinger/Donchian/EMA/simple_momentum/mean_reversion single-asset guard pattern (skills/quantitative-backtesting/tests/).
- No source changes; `run_elevated_cost_sweep`/`run_param_sensitivity_sweep` already existed in `examples/rsi_mean_reversion_hypothesis.py`. Note: RSI's sweep functions print no banner, so the output-string assertions carried over from MACD were omitted (they would fail for RSI).

## What was actually verified
- `test_rsi_mean_reversion_elevated_cost_real_aapl.py` → PASS
- `test_rsi_mean_reversion_param_sensitivity_real_aapl.py` → PASS
- Focused RSI gate (both new + test_rsi_mean_reversion_hypothesis.py) → **7 passed, 0 failed** in 29.02s
- Offline, committed fixtures only (`assets/example_data/real_market_data/AAPL.csv`); no live network; no tuning to force SUPPORT.
- Observed on committed AAPL (net of 3bp costs, weak two-criterion sweep): RSI mean reversion is NOT SUPPORTED at every cost level (Sharpe -0.829→-1.041, return -29.7%→-35.7% as costs rise to 20bp/10bp) and across all five parameter settings (Sharpe -0.829→-1.276, return -28.3%→-39.0%). Uniformly negative = parameter sensitivity / cost sensitivity, not a robust edge. No profitability claim.
- Working tree clean: only the two new test files are untracked.

## What remains unresolved
- All single-asset families (MACD, Bollinger Bands, Donchian, EMA cross, simple momentum, mean reversion, RSI mean reversion) now have elevated-cost-sweep + param-sensitivity regression guards on committed AAPL.
- Full quant-backtesting suite (~981 tests, ~34 min) too slow to complete in-session; per-file focused gates are the reliable verification mode.
- Multi-asset benchmark-aware coverage and remaining families without benchmark-aware guards (e.g. zscore_mean_reversion, pairs_trading) not yet reviewed.

## Approaches already tried / failed
- None this session; direct sweep execution on absolute AAPL path works (subprocess cwd=scripts_dir requires absolute data_path).

## One precise next task
Review whether zscore_mean_reversion (and pairs_trading) lack single-asset AAPL elevated-cost-sweep / param-sensitivity regression guards, mirroring the RSI pattern just added:
1. Inspect `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py` to confirm `run_elevated_cost_sweep` / `run_param_sensitivity_sweep` APIs, `ELEVATED_COST_SWEEP_LEVELS`, `PARAM_SENSITIVITY_GRID`, defaults, and whether they support single-asset AAPL CSV directly.
2. Capture pinned metrics by running the sweep functions on committed `assets/example_data/real_market_data/AAPL.csv` first (do not guess).
3. Add `tests/test_zscore_mean_reversion_elevated_cost_real_aapl.py` and `tests/test_zscore_mean_reversion_param_sensitivity_real_aapl.py` with honest docstrings, asserting verdict structure and pinned metrics at rel tol 1e-3.
4. Verify with focused gate: the two new tests plus any existing zscore single-asset/AAPL-adjacent guards.
Constraints: offline, committed fixtures only, no tuning to force SUPPORT, smallest reversible change, no profitability claim. Do not commit unless explicitly asked.
