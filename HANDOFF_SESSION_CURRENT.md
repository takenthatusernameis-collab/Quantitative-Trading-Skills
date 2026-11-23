# Handoff — Current State

## Latest
- HEAD `c4f12e8`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py`
- This session extended protocol-sensitivity + multiplicity control to a **ninth** signal family: EMA crossover on the committed single-asset AAPL fixture (prior eight: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion triple panel, RSI mean reversion triple panel, Donchian breakout AAPL, MACD AAPL, Bollinger Bands AAPL — all NOT SUPPORTED).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `ema_crossover` single-asset long/flat on AAPL, per-asset walk-forward (single asset), same construction as the other protocol-sensitivity studies.
- Grid: `{"fast_period": [12], "slow_period": [26]}` (1 configuration, advertised defaults from `strategy_builder.py` line 1689, matching `test_ema_cross_hypothesis_real_aapl.py`), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` (step == test).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 5-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).

## Honest finding (DIFFERENT from prior families — important)
- EMA crossover is the **first family where a single cell passes all three nominal criteria**: `(36,12,12)` → OOS Sharpe 1.1732 > 0, total return 0.5155 > 0, Deflated Sharpe p = 0.0631 < 0.10. Full matrix DSR p: (12,12,12)=0.7069, (18,12,12)=0.7549, (24,12,12)=0.6249, (30,12,12)=0.6756, (36,12,12)=0.0631.
- This is exactly the protocol-selection-bias hazard the study targets: 1 of 5 equally-valid protocols shows nominal significance; choosing it after seeing results would manufacture a false SUPPORT.
- However, the DSR inside that cell corrects only for its 2 walk-forward periods, NOT for the 5 protocols tried. Bonferroni across the five-protocol family inflates the best nominal p (0.0631) to **0.3155 > 0.10**, `n_rejected = 0`. So the nominal pass does NOT survive protocol-multiplicity correction and the honest overall verdict is **NOT SUPPORTED**.
- Tests therefore assert: exactly one nominal passer `(36,12,12)`; baseline `(12,12,12)` fails DSR; best-nominal protocol is `(36,12,12)`; Bonferroni-adjusted best p > 0.10; n_rejected == 0. This documents the selection-bias trap rather than hiding it.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed**, exit 0, verdict NOT SUPPORTED.
- Existing EMA tests still **OK** (no regression): `test_walk_forward_ema_crossover_real_aapl.py` (OK), `test_ema_cross_hypothesis_real_aapl.py` (OK).
- `git status`: only the new untracked file; no existing file touched.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH; run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control now covers **nine** signal families — all with an overall NOT SUPPORTED verdict after multiplicity correction: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (AAPL), MACD (AAPL), Bollinger Bands (AAPL), EMA crossover (AAPL).
- EMA crossover is a useful contrast case: it shows a nominal single-protocol pass that does NOT survive protocol multiplicity (0.0631 → Bonferroni 0.3155). Cite it when explaining why single-protocol "SUPPORTED" claims are unsafe.
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: **Kelly criterion, volatility targeting**.
- Candidate next bounded task: extend protocol-sensitivity + multiplicity control to **Kelly criterion** on single-asset AAPL, mirroring this EMA test. Confirm the strategy name and advertised defaults from `strategy_builder.py` and the base `test_kelly*_real_aapl.py` (find exact filename via `ls skills/quantitative-backtesting/tests | grep -i kelly`). If Kelly has no natural per-period position sizing in the walk-forward harness, document that limitation honestly rather than forcing a verdict. Do not commit unless explicitly asked.

(End of file)