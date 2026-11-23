# Handoff — Next Task: Multiplicity control for time-series momentum (or dual momentum) across folds × parameter grid

## Status (entering this task)
- HEAD `c897209`; working tree has one untracked additive file from the prior session:
  `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_multiplicity_control_real_triple_aapl_msft_googl.py` (2/2 passing, NOT SUPPORTED).
- Cross-sectional momentum now has BOTH protocol-sensitivity (Bonferroni on DSR) AND fold×lookback BH-FDR + Romano-Wolf FWER multiplicity control.
- SMA crossover has fold×parameter BH-FDR + Romano-Wolf FWER multiplicity control (commit c897209).

## One precise next task (one bounded item)
Apply the **same** paired-bootstrap Sharpe-difference + BH-FDR + Romano-Wolf stepdown methodology to **time-series momentum** (or **dual momentum**) across a walk-forward **fold × parameter** family on the committed triple panel, mirroring:
`skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_multiplicity_control_real_triple_aapl_msft_googl.py`
and
`skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_multiplicity_control_real_triple_aapl_msft_googl.py`.

Suggested concrete scope for time-series momentum:
- Signal: `time_series_momentum` (per-symbol trend signal, `panel_pricing` as in the existing `test_walk_forward_time_series_momentum_real_triple_aapl_msft_googl.py`).
- Parameter family: a small pre-registered lookback/threshold grid (e.g. lookbacks `[20, 60, 126]` or the grid already used by `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`). Reuse an EXISTING grid — do not invent a new one.
- Walk-forward: train12/test12/step12 → 4 folds; per (fold, symbol or fold, param) compute paired-bootstrap Sharpe-diff p-values vs. equal-weight panel benchmark, net of 2bp+1bp.
- Apply `utils.benjamini_hochberg` (FDR across all cells) + `utils.romano_wolf_stepdown` (FWER within each fold across params).
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_multiplicity_control_real_triple_aapl_msft_googl.py` with a `__main__` runner printing PASS and exiting 0; run directly with `python3`.
- Offline, committed fixtures only. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Record raw p, BH q, Bonferroni p, RW adjusted p, rejection decisions, final multiplicity-controlled verdict. No profitability claim; NOT SUPPORTED is acceptable and likely honest.

## Approaches already tried / failed
- None for this task (the two prior multiplicity studies succeeded).

## Constraints / environment reminders
- Offline/committed fixtures only; default JSON backtest output unchanged; no profitability or capacity claims.
- `pytest` not installed on PATH — run each test file with `python3`; several tests are slow (>90s), use a generous timeout.
- Do not commit unless explicitly asked.