# Handoff — Current State

## Latest
- HEAD `350b488`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_bollinger_bands_protocol_sensitivity_real_aapl.py`
- This session extended protocol-sensitivity + multiplicity control to an **eighth signal family**: Bollinger Bands mean reversion on the committed single-asset AAPL fixture (prior: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion triple panel, RSI mean reversion triple panel, Donchian breakout AAPL, MACD AAPL — all NOT SUPPORTED).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `bollinger_bands` single-asset long/short/flat on AAPL, per-asset walk-forward then pooled (single asset), same construction as the other protocol-sensitivity studies.
- Grid: `{"period": [20], "std_dev": [2.0]}` (1 configuration, advertised defaults from `examples/bollinger_bands_hypothesis.py`), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` (step == test).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 5-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).
- Honest finding: Deflated Sharpe p-value > 0.10 in ALL five cells (0.9274 / 0.6832 / 0.7045 / 0.7718 / 0.6468), so 0/5 cells pass all three pre-registered criteria. Raw OOS Sharpe > 0 only in two cells ((18,12,12)=0.0052, (24,12,12)=0.0063) and neither survives correction. Best nominal cell (36,12,12), p=0.6468, Bonferroni-adjusted = 3.234 > 0.10; n_rejected=0. Verdict: consistently **NOT SUPPORTED** — Bollinger Bands' near-zero/positive raw Sharpe in some cells does not survive multiple-testing correction under any of the five equally-valid protocols.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed** (pinned regression guard matrix + verdict + multiplicity + registry checks), values match the probe run (rounded to 4 decimals, ABS_TOL 1e-3), exit 0.
- Existing Bollinger tests still **OK** (no regression): `test_bollinger_bands_param_sensitivity_real_aapl.py`, `test_bollinger_bands_hypothesis_real_aapl.py`, `test_bollinger_bands_benchmark_aware_real_aapl.py` — all NOT SUPPORTED, consistent with this study.
- `git status`: only the new untracked file; no existing file touched.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH; run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control now covers **eight** signal families — all consistently NOT SUPPORTED: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (single-asset AAPL), MACD (single-asset AAPL), Bollinger Bands (single-asset AAPL).
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: EMA crossover, Kelly criterion, volatility targeting.
- Candidate next bounded task: extend protocol-sensitivity + multiplicity control to EMA crossover on single-asset AAPL, mirroring the Bollinger test just added. Strategy name `ema_crossover`, advertised defaults `{"fast_period": [12], "slow_period": [26]}` (confirm costs from `test_ema_cross_hypothesis_real_aapl.py`), same 5 protocols, same 4-test structure. Or advance a new methodological study (walk-forward optimization vs fixed-parameter, ensemble, new signal family) on the committed triple panel. Do not commit unless explicitly asked.

(End of file)
