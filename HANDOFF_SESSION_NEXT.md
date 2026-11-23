# Handoff — Next Task: Protocol-sensitivity + multiplicity control for volatility targeting on single-asset AAPL

## Status (entering this task)
- HEAD `c4f12e8`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_kelly_criterion_protocol_sensitivity_real_aapl.py` (4/4 passing via `python3`; overall verdict NOT SUPPORTED after Bonferroni across 5 protocols; NOT committed).
- Protocol-sensitivity + multiplicity control now covers **ten** signal families, all overall NOT SUPPORTED after protocol-multiplicity correction: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (AAPL), MACD (AAPL), Bollinger Bands (AAPL), EMA crossover (AAPL), Kelly criterion (AAPL).
- Kelly criterion: zero cells pass the three nominal criteria; all Sharpe > 0 and total return > 0, but every DSR p-value >= 0.10; best nominal p = 0.2789 at (30,12,12) → Bonferroni-adjusted = 1.0, n_rejected = 0. Verdict NOT SUPPORTED.
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: **volatility targeting**.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Extend protocol-sensitivity + multiplicity control to **volatility targeting on single-asset AAPL**, mirroring `test_walk_forward_kelly_criterion_protocol_sensitivity_real_aapl.py` and the base walk-forward test.

Steps:
1. Inspect the base volatility-targeting walk-forward test to confirm the exact strategy name, advertised default parameter grid, and cost convention:
   - `ls skills/quantitative-backtesting/tests | grep -i volatility` → read `test_walk_forward_volatility_targeting_real_aapl.py`.
   - Confirm the strategy registry name (likely `volatility_targeting`) in `skills/quantitative-backtesting/scripts/strategy_builder.py` (grep `volatility`) and its default params (the `DEFAULT_PARAMS`-style dict).
   - Confirm whether the volatility-targeting strategy produces a per-period *position* (so `periods_with_position` is meaningful). If it is a sizing overlay that is always "in" the market, the OOS record may still be informative — verify with a probe.
2. Create `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_aapl.py` with:
   - Signal: the volatility-targeting strategy (single-asset), parameter grid = advertised defaults (1 configuration), `apply_deflation=True, validate_pit=True`, costs 2bp commission + 1bp slippage (confirm from base test).
   - Protocols (12-month test, step == test): `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` — confirm each is informative (periods_with_position >= 2); drop any that are not, and document the drop.
   - Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10.
   - Four `test_*` functions + `TEST_REGISTRY` + `main()` returning 0 on success, mirroring the Kelly test.
3. Run the file once with `python3` to capture real numbers (probe), then pin them in EXPECTED; do NOT hard-code guessed values. Record the honest verdict — whether zero, one, or more cells pass nominal criteria, and whether any survive Bonferroni across the protocol family.
4. Run the base volatility-targeting test too and confirm no regression.

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from the repo root; use generous timeouts (>90s per file known).
- Several tests print PIT progress to stdout while running; redirect to a log if needed, but the PASS/FAIL summary is the signal.
- Do NOT force a predetermined verdict. If a cell passes nominal criteria but not Bonferroni, report that honestly rather than asserting zero nominal passers.
- No profitability/capacity claim; the honest overall verdict is expected to be NOT SUPPORTED after multiplicity correction.

## Approaches already tried / failed
- None for this task.

(End of file)
