# Handoff — Next Task: Protocol-sensitivity + multiplicity control for Kelly criterion on single-asset AAPL

## Status (entering this task)
- HEAD `c4f12e8`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py` (4/4 passing via `python3`; overall verdict NOT SUPPORTED after Bonferroni across 5 protocols; NOT committed).
- Protocol-sensitivity + multiplicity control now covers **nine** signal families, all overall NOT SUPPORTED after protocol-multiplicity correction: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (AAPL), MACD (AAPL), Bollinger Bands (AAPL), EMA crossover (AAPL).
- EMA crossover is the first family where one cell (`(36,12,12)`) passes all three *nominal* criteria (Sharpe 1.1732, return 0.5155, DSR p 0.0631) but does NOT survive Bonferroni across the 5 protocols (0.0631 → 0.3155 > 0.10, n_rejected 0). Cite as the protocol-selection-bias example.
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: **Kelly criterion, volatility targeting**.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Extend protocol-sensitivity + multiplicity control to **Kelly criterion on single-asset AAPL**, mirroring `test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py` and the base test.

Steps:
1. Inspect the base Kelly test to confirm the exact strategy name, advertised default parameter grid, and cost convention:
   - `ls skills/quantitative-backtesting/tests | grep -i kelly` → find the base `*_real_aapl.py` file; read it.
   - Confirm the strategy registry name (likely `kelly_criterion` or `kelly`) in `skills/quantitative-backtesting/scripts/strategy_builder.py` (grep `kelly`) and its default params (the `DEFAULT_PARAMS`-style dict near line 1688).
   - Confirm whether the Kelly strategy in the walk-forward harness produces a per-period *position* (so `periods_with_position` is meaningful). If Kelly is a sizing overlay that is always "in" the market, the OOS record may still be informative — verify with a probe.
2. Create `skills/quantitative-backtesting/tests/test_walk_forward_kelly_crossover_protocol_sensitivity_real_aapl.py` (adjust name to the actual strategy, e.g. `..._kelly_criterion_...`) with:
   - Signal: the Kelly strategy (single-asset), parameter grid = advertised defaults (1 configuration), `apply_deflation=True, validate_pit=True`, costs 2bp commission + 1bp slippage (confirm from base test).
   - Protocols (12-month test, step == test): `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` — confirm each is informative (periods_with_position >= 2); drop any that are not, and document the drop.
   - Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10.
   - Four `test_*` functions + `TEST_REGISTRY` + `main()` returning 0 on success, mirroring the EMA test.
3. Run the file once with `python3` to capture real numbers (probe), then pin them in EXPECTED; do NOT hard-code guessed values. Record the honest verdict — whether zero, one, or more cells pass nominal criteria, and whether any survive Bonferroni across the protocol family.
4. Run the base Kelly test too and confirm no regression.

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from the repo root; use generous timeouts (>90s per file known).
- Several tests print PIT progress to stdout while running; redirect to a log if needed, but the PASS/FAIL summary is the signal.
- Do NOT force a predetermined verdict. If a cell passes nominal criteria but not Bonferroni, report that honestly (like EMA) rather than asserting zero nominal passers.
- No profitability/capacity claim; the honest overall verdict is expected to be NOT SUPPORTED after multiplicity correction.

## Approaches already tried / failed
- None for this task.

(End of file)