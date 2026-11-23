# Handoff — Next Task: Extend protocol-sensitivity coverage to one more signal family

## Status (entering this task)
- HEAD `6d2367a0fa82d2b1dc624c608f4b0557dca4507e`; working tree has one untracked additive file:
  `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py` (4/4 passing, NOT SUPPORTED).
- Protocol-sensitivity + multiplicity control is now in place for all four momentum-family signals: SMA crossover, cross-sectional momentum, time-series momentum, and dual momentum — all NOT SUPPORTED on the committed triple panel (AAPL/MSFT/GOOGL).

## One precise next task (one bounded item)
Extend protocol-sensitivity study coverage (Bonferroni across train/test protocols) to **one more signal family** that has walk-forward coverage but lacks a protocol-sensitivity study. The next agent must FIRST verify which signal families are missing one by scanning `skills/quantitative-backtesting/tests/` for `*protocol_sensitivity*` files and matching against `*walk_forward*`/`*hypothesis*` coverage; do not assume.

Concrete scope (template to mirror):
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py` (just added)

### Concrete requirements
- Pick a signal with an existing committed-fixture walk-forward test but no `*protocol_sensitivity*` sibling.
- Use a PRE-REGISTERED small protocol family (equally-valid chronological protocols), reuse an EXISTING parameter grid (do not invent one), costs 2bp commission + 1bp slippage, `panel_pricing` appropriate to the signal, `apply_deflation=True, validate_pit=True`.
- Discovery run first, then pin values (rounded, tolerance comparison, never exact equality). New test file with `__main__` runner printing PASS and exiting 0; run directly with `python3`.
- Per-cell criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10; Bonferroni across the protocol family on the best nominal cell; verdict-agnostic (NOT SUPPORTED acceptable).
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_<signal>_protocol_sensitivity_real_*.py`; TEST_REGISTRY + main() conventions; `test_main_registers_every_module_level_test`.
- Offline, committed fixtures only. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.

## Constraints / environment reminders
- `pytest` not installed on PATH — run each test file with `python3`; several tests are slow (>90s), use a generous timeout.
- Do not commit unless explicitly asked.
- No profitability/capacity claim; committed verdicts remain NOT SUPPORTED.

## Approaches already tried / failed
- None for this task.

(End of file)
