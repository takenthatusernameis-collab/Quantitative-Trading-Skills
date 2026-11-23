# Handoff — Next Task: Dual momentum protocol-sensitivity study (Bonferroni across protocols)

## Status (entering this task)
- HEAD `e5aead4`; working tree has one untracked additive file:
  `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_multiplicity_control_real_triple_aapl_msft_googl.py` (2/2 passing, NOT SUPPORTED).
- Multiplicity control is now in place for all four momentum-family signals (SMA crossover, cross-sectional momentum, time-series momentum, dual momentum) — all NOT SUPPORTED on the committed triple panel.
- Dual momentum has walk-forward + Deflated Sharpe (pooled OOS) and fold×lookback BH-FDR + Romano-Wolf FWER multiplicity control, but **no protocol-sensitivity** study. Cross-sectional momentum and time-series momentum both have one (`test_walk_forward_*_protocol_sensitivity_real_triple.py`).

## One precise next task (one bounded item)
Add a **dual momentum protocol-sensitivity** study (Bonferroni correction across train/test protocols), mirroring:
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`

Because dual momentum is inherently multi-asset (`generate_target_weights` returns None for single-asset data), use the **triple-panel `walk_forward_analysis`** interface (as `test_dual_momentum_walk_forward_real_triple_aapl_msft_googl.py` does), with `apply_deflation=True, validate_pit=True`.

### Concrete scope
- Signal: `dual_momentum` on the committed triple panel (AAPL/MSFT/GOOGL), `panel_pricing="book"`, costs 2bp commission + 1bp slippage.
- Parameter grid: reuse an EXISTING grid — e.g. `{"lookback": [189, 252], "top_quantile": [0.5], "risk_free_rate": [0.0]}` from `test_dual_momentum_walk_forward_real_triple_aapl_msft_googl.py` (do not invent a new one).
- Protocols (train_months, test_months, step_months with step==test): a small pre-registered family of equally-valid chronological protocols, e.g. `(12,12,12)`, `(24,12,12)`, `(36,12,12)`, `(30,12,12)` (12-month-test, informative since test window >= 252-day lookback). Optionally add a short-window family and mark it uninformative/degenerate.
- Per protocol: run `walk_forward_analysis` once on the triple panel, collect `oos_sharpe`, `total_oos_return`, `deflated_sharpe.p_value`, `deflated_sharpe.n_trials`, `periods_with_position`, `bias_controls_engaged`.
- Within-protocol DSR already corrects for the lookback grid; apply **Bonferroni across the protocol family** to the best nominal cell's DSR p-value (protocol-selection bias control).
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py` with a `__main__` runner printing PASS and exiting 0; run directly with `python3`.
- Offline, committed fixtures only. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.

### Methodological discipline (read before writing)
- **Discovery run first, then pin values.** Do not fabricate expected numbers. Run the walk-forward across the protocol family once to collect actual metrics, then write the test with those observed values as pinned regression guards (rounded, compared with a tolerance, never exact equality).
- Verdict-agnostic assertions where possible; record raw numbers, Bonferroni-adjusted p-values, and whether any cell survives. NOT SUPPORTED is an acceptable and likely honest outcome; no profitability claim.
- Per the mission: a single protocol cannot establish or falsify a verdict; this study makes that limitation explicit and regression-guarded.

## Approaches already tried / failed
- None for this task.

## Constraints / environment reminders
- Offline/committed fixtures only; default JSON backtest output unchanged; no profitability or capacity claims.
- `pytest` not installed on PATH — run each test file with `python3`; several tests are slow (>90s), use a generous timeout.
- Do not commit unless explicitly asked.

(End of file)
