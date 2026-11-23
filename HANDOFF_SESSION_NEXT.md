# Handoff — Next Task: Protocol-sensitivity + multiplicity control for EMA crossover on single-asset AAPL

## Status (entering this task)
- HEAD `350b488`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_bollinger_bands_protocol_sensitivity_real_aapl.py` (4/4 passing via `python3`; NOT SUPPORTED; NOT committed).
- Protocol-sensitivity + multiplicity control now covers **eight** signal families — all consistently NOT SUPPORTED: SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion, RSI mean reversion (triple panel), Donchian breakout (AAPL), MACD (AAPL), Bollinger Bands (AAPL).
- Remaining single-asset families with base `*_real_aapl.py` tests but NO protocol-sensitivity coverage: EMA crossover, Kelly criterion, volatility targeting.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Extend protocol-sensitivity + multiplicity control to **EMA crossover on single-asset AAPL**, mirroring the Bollinger test just added and the existing base test `test_ema_cross_hypothesis_real_aapl.py`:

Create `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py` with:
- Signal: `ema_crossover` (single-asset), parameter grid `{"fast_period": [12], "slow_period": [26]}` (1 configuration, advertised defaults from `strategy_builder.py` line 1689; confirm costs from `test_ema_cross_hypothesis_real_aapl.py` — expected 2bp commission + 1bp slippage), `apply_deflation=True, validate_pit=True`.
- Protocols (12-month test, step == test): `(12,12,12)`, `(18,12,12)`, `(24,12,12)`, `(30,12,12)`, `(36,12,12)` — confirm each is informative (periods_with_position >= 2); drop any that are not.
- Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10.
- Four `test_*` functions + `TEST_REGISTRY` + `main()` returning 0 on success, mirroring `test_walk_forward_bollinger_bands_protocol_sensitivity_real_aapl.py`:
  1. `test_protocol_sensitivity_matrix_pinned` — pinned cell matrix rounded to 4 decimals, ABS_TOL 1e-3.
  2. `test_verdict_is_consistently_not_supported` — no cell passes all three criteria; DSR p-value >= 0.10 in every cell.
  3. `test_no_cell_survives_protocol_multiplicity` — Bonferroni across the protocol family; best-adjusted p > 0.10; n_rejected == 0.
  4. `test_main_registers_every_module_level_test`.
- Run directly: `python3 skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py` → expect 4/4 PASS, exit 0, verdict NOT SUPPORTED.
- First run the file once to capture real numbers (probe), then pin them in EXPECTED; do not hard-code guessed values.

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from the repo root; use generous timeouts (>90s per file known).
- Several tests print PIT progress to stdout while running; redirect to a log if needed, but the PASS/FAIL summary is the signal.
- No profitability/capacity claim; NOT SUPPORTED is the honest outcome.

## Approaches already tried / failed
- None for this task.

(End of file)
