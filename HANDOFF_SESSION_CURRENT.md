# Handoff — Current State

## Latest
- HEAD `b899ae0e06b4bb590f60512b812f338a90ffa3d4`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_aapl_msft_googl.py`
- This session extended protocol-sensitivity + multiplicity control to a **sixth signal family**: RSI mean reversion on the committed AAPL/MSFT/GOOGL triple panel (the five prior families were SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion — all NOT SUPPORTED).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `rsi_mean_reversion` per-asset long/short mean reversion, equal-weight pooled portfolio across AAPL/MSFT/GOOGL (per-asset `walk_forward_analysis` then pool per-period OOS returns — same construction as the SMA crossover protocol-sensitivity study).
- Grid: `{"period": [14], "oversold": [30], "overbought": [70], "neutral": [50]}` (1 configuration, advertised defaults from strategy_builder.py), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(24,12,12)`, `(36,12,12)`, `(18,12,12)`, `(30,12,12)` (step == test).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 4-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).
- Honest finding: raw OOS Sharpe > 0 and total return > 0 in ALL four cells (0.5137 / 0.4730 / 0.3078 / 0.2528; returns +0.3120 / +0.1611 / +0.2551 / +0.1523), but Deflated Sharpe p-value > 0.10 in ALL cells (0.8365 / 0.7230 / 0.9598 / 0.8984), so 0/4 cells pass all three pre-registered criteria. Best nominal cell (36,12,12), p=0.7230, Bonferroni-adjusted = 1.0 > 0.10; n_rejected=0. Verdict: consistently **NOT SUPPORTED** — RSI mean reversion's positive raw Sharpe does not survive multiple-testing correction under any of the four equally-valid 12-month protocols.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed** (pinned regression guard matrix + verdict + multiplicity + registry checks), values match the discovery run (rounded to 4 decimals, ABS_TOL 1e-3).
- `git status`: only the new untracked file; no existing file touched.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control now covers **six** signal families on the committed triple panel — all consistently NOT SUPPORTED: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion.
- Prior full-suite re-run (994 passed / 0 failed) cannot be executed as written because pytest is not installed; the direct-`python3` convention is the working alternative.
- Candidate next bounded task: extend protocol-sensitivity + multiplicity control to one of the remaining single-asset families (Donchian, MACD, Bollinger, EMA crossover, Kelly criterion, volatility targeting) on a single asset, mirroring their existing `test_walk_forward_*_real_aapl.py` tests. Or advance a new methodological study (e.g., walk-forward optimization/nested-CV vs fixed-parameter to quantify optimization bias, or capacity/liquidity sensitivity) on the committed triple panel. Do not commit unless explicitly asked.

(End of file)
