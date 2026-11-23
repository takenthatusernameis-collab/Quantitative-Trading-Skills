# Handoff — Current State

## Latest
- HEAD `4c20e8b`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_donchian_protocol_sensitivity_real_aapl.py`
- This session extended protocol-sensitivity + multiplicity control to a **seventh signal family**: Donchian channel breakout on the committed single-asset AAPL fixture (the six prior families: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion on the triple panel, and RSI mean reversion on the triple panel — all NOT SUPPORTED).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `donchian_breakout` single-asset long/short/flat on AAPL, per-asset walk-forward then pooled (single asset), same construction as the other protocol-sensitivity studies.
- Grid: `{"period": [20], "exit_period": [10]}` (1 configuration, advertised defaults from the existing `test_walk_forward_donchian_real_aapl.py`), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` (step == test).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 5-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).
- Honest finding: Deflated Sharpe p-value > 0.10 in ALL five cells (0.4311 / 0.7728 / 0.6404 / 0.7685 / 0.6632), so 0/5 cells pass all three pre-registered criteria. Raw OOS Sharpe > 0 only in two cells ((12,12,12)=0.3655, (24,12,12)=0.0470) and neither survives correction. Best nominal cell (12,12,12), p=0.4311, Bonferroni-adjusted = 2.1554 > 0.10; n_rejected=0. Verdict: consistently **NOT SUPPORTED** — Donchian breakout's positive raw Sharpe in some cells does not survive multiple-testing correction under any of the five equally-valid protocols.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed** (pinned regression guard matrix + verdict + multiplicity + registry checks), values match the discovery run (rounded to 4 decimals, ABS_TOL 1e-3).
- Existing base test `test_walk_forward_donchian_real_aapl.py`: still **OK** (no regression).
- `git status`: only the new untracked file; no existing file touched.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH; run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control now covers **seven** signal families — all consistently NOT SUPPORTED: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (single-asset AAPL).
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: MACD, Bollinger, EMA crossover, Kelly criterion, volatility targeting.
- Candidate next bounded task: extend protocol-sensitivity + multiplicity control to MACD on single-asset AAPL, mirroring the Donchian test just added and `test_walk_forward_macd_real_aapl.py`. Or advance a new methodological study (walk-forward optimization / nested-CV vs fixed-parameter to quantify optimization bias; capacity/liquidity sensitivity; ensemble combination) on the committed triple panel. Do not commit unless explicitly asked.

(End of file)
