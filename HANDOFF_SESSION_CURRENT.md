# Handoff — Current State

## Latest
- HEAD `f9adfae`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_aapl.py`
- This session extended protocol-sensitivity + multiplicity control to an **eleventh** signal family: volatility targeting on committed single-asset AAPL (prior ten: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion triple panel, RSI mean reversion triple panel, Donchian breakout AAPL, MACD AAPL, Bollinger Bands AAPL, EMA crossover AAPL, Kelly criterion AAPL — all NOT SUPPORTED after multiplicity correction).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `volatility_targeting` single-asset (momentum-fallback base with volatility-targeting position-sizing overlay; produces a per-period position, so `periods_with_position` is meaningful), per-asset walk-forward (single asset), same construction as the other protocol-sensitivity studies.
- Grid: `{"target_vol": [0.15], "lookback": [63]}` (1 configuration, advertised defaults from `strategy_builder.py` and `test_walk_forward_volatility_targeting_real_aapl.py`), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` (step == test). All five cells informative (`periods_with_position >= 2`).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 5-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).

## Honest finding
- Volatility targeting: **zero** cells pass the three pre-registered nominal criteria (OOS Sharpe > 0 AND OOS total return > 0 AND DSR p < 0.10).
  - Cells: (12,12,12) Sharpe=0.0446 ret=0.0458 p=0.8606; (18,12,12) Sharpe=0.0810 ret=0.0604 p=0.5217; (24,12,12) Sharpe=-0.2236 ret=-0.0561 p=0.8484; (30,12,12) Sharpe=0.1517 ret=0.0719 p=0.4792; (36,12,12) Sharpe=-0.0363 ret=0.0053 p=0.5977.
  - Two cells have negative Sharpe/return and fail nominally; the remaining three pass Sharpe/return but all DSR p >= 0.10.
- Best nominal cell `(30,12,12)` p=0.4792 → Bonferroni-adjusted = 1.0 > 0.10, `n_rejected = 0`. Honest overall verdict: **NOT SUPPORTED**.
- Baseline `(12,12,12)` DSR p=0.8606 matches the base walk-forward test exactly; baseline fails DSR criterion (p >= 0.10).
- Tests assert: zero nominal passers; baseline fails DSR; best-nominal protocol is `(30,12,12)`; Bonferroni-adjusted best p > 0.10; n_rejected == 0.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed**, exit 0, verdict NOT SUPPORTED (EXPECTED pinned; probe run captured real numbers, not guessed).
- Base volatility test still OK (no regression): `test_walk_forward_volatility_targeting_real_aapl.py` prints OK.
- `git status`: only the new untracked file; no existing file touched.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH; run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control now covers **eleven** signal families — all with an overall NOT SUPPORTED verdict after multiplicity correction.
- All single-asset families with base `*_real_aapl.py` tests now have protocol-sensitivity coverage (volatility targeting and Kelly criterion both done).
- Candidate next bounded task: extend protocol-sensitivity + multiplicity control to volatility targeting on **MSFT and GOOGL** (single-asset), mirroring the AAPL test, to check cross-asset robustness. Confirm each cell is informative (periods_with_position >= 2); drop and document any that are not. Do not commit unless explicitly asked.
- Alternative next task: run the broader walk-forward family (non-protocol-sensitivity) directly with `python3` and confirm no regressions (see HANDOFF_SESSION_NEXT_EXECUTED.md examples).
- `pytest` unavailable; direct `python3` execution is the verified convention.

(End of file)
