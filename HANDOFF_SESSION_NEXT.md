# Handoff — Next Task: Protocol-sensitivity + multiplicity control for volatility targeting on single-asset MSFT and GOOGL (cross-asset robustness)

## Status (entering this task)
- HEAD `f9adfae`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_aapl.py` (4/4 passing via `python3`; overall verdict NOT SUPPORTED after Bonferroni across 5 protocols; NOT committed).
- Protocol-sensitivity + multiplicity control now covers **eleven** signal families, all overall NOT SUPPORTED after protocol-multiplicity correction: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (AAPL), MACD (AAPL), Bollinger Bands (AAPL), EMA crossover (AAPL), Kelly criterion (AAPL), volatility targeting (AAPL).
- Volatility targeting (AAPL): zero cells pass the three nominal criteria; two cells have negative Sharpe/return; best nominal DSR p=0.4792 at (30,12,12) → Bonferroni-adjusted = 1.0, n_rejected = 0. Verdict NOT SUPPORTED. Baseline (12,12,12) p=0.8606 matches base test.
- All single-asset families with base `*_real_aapl.py` tests now have protocol-sensitivity coverage.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Extend protocol-sensitivity + multiplicity control to **volatility targeting on single-asset MSFT and GOOGL**, mirroring `test_walk_forward_volatility_targeting_protocol_sensitivity_real_aapl.py`, to check cross-asset robustness (same signal, same grid, same protocols, different assets).

Steps:
1. Confirm base volatility-targeting tests exist for MSFT/GOOGL or adapt the AAPL base test convention:
   - `ls skills/quantitative-backtesting/tests | grep -i volatility` → read `test_walk_forward_volatility_targeting_real_aapl.py` for the exact convention (PARAM_GRID `{"target_vol": [0.15], "lookback": [63]}`, costs 2bp + 1bp, `apply_deflation=True, validate_pit=True`).
   - Confirm `MSFT.csv` and `GOOGL.csv` exist in `skills/quantitative-backtesting/assets/example_data/real_market_data/`.
2. Create two files:
   - `test_walk_forward_volatility_targeting_protocol_sensitivity_real_msft.py`
   - `test_walk_forward_volatility_targeting_protocol_sensitivity_real_googl.py`
   Each mirroring the AAPL test:
   - Signal: `volatility_targeting` (single-asset), PARAM_GRID `{"target_vol": [0.15], "lookback": [63]}` (1 config), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
   - Protocols (12-month test, step == test): `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` — confirm each is informative (periods_with_position >= 2); drop any that are not and document the drop.
   - Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10.
   - Four `test_*` functions + `TEST_REGISTRY` + `main()` returning 0 on success, mirroring the AAPL test.
   - SYMBOL = "MSFT" / "GOOGL" respectively.
3. Run each file once with `python3` to capture real numbers (probe), then pin them in EXPECTED; do NOT hard-code guessed values. Record the honest verdict per asset — whether zero, one, or more cells pass nominally, and whether any survive Bonferroni across the protocol family.
4. Run the base volatility-targeting AAPL test too and confirm no regression.

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from the repo root; use generous timeouts (>90s per file known).
- Several tests print PIT progress to stdout while running; redirect to a log if needed, but the PASS/FAIL summary is the signal.
- Do NOT force a predetermined verdict. If a cell passes nominally but not Bonferroni, report that honestly rather than asserting zero nominal passers.
- No profitability/capacity claim; the honest overall verdict is expected to be NOT SUPPORTED after multiplicity correction.

## Approaches already tried / failed
- None for this task.

(End of file)
