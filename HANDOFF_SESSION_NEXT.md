# Handoff — Next Task: Extend protocol-sensitivity coverage to SMA crossover

## Status (entering this task)
- HEAD `6d2367a0fa82d2b1dc624c608f4b0557dca4507e`; working tree has two untracked additive files:
  - `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py` (4/4 passing, NOT SUPPORTED)
  - `skills/quantitative-backtesting/tests/test_walk_forward_zscore_multi_pair_protocol_sensitivity_real_triple.py` (5/5 passing, NOT SUPPORTED)
- Protocol-sensitivity + multiplicity control is now in place for **five** signal families on the committed triple panel: cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion — all NOT SUPPORTED. SMA crossover has walk-forward coverage (`test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py`) but lacks a protocol-sensitivity study.

## One precise next task (one bounded item)
Extend protocol-sensitivity study coverage (Bonferroni across train/test protocols) to **SMA crossover**. The next agent must FIRST verify the signal family is missing one by scanning `skills/quantitative-backtesting/tests/` for `*protocol_sensitivity*` files and matching against `*walk_forward*`/`*hypothesis*` coverage; do not assume.

Concrete scope (template to mirror):
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_zscore_multi_pair_protocol_sensitivity_real_triple.py`

### Concrete requirements
- Pick SMA crossover (existing committed-fixture walk-forward test but no `*protocol_sensitivity*` sibling).
- Use a PRE-REGISTERED small protocol family (equally-valid chronological protocols), reuse an EXISTING parameter grid (fast=20, slow=50 from the walk-forward test), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Discovery run first, then pin values (rounded, tolerance comparison, never exact equality). New test file with `__main__` runner printing PASS and exiting 0; run directly with `python3`.
- Per-cell criteria: OOS Sharpe > 0 AND OOS total return > 0 AND Deflated Sharpe p-value < 0.10; Bonferroni across the protocol family on the best nominal cell; verdict-agnostic (NOT SUPPORTED acceptable).
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_*.py`; TEST_REGISTRY + main() conventions; `test_main_registers_every_module_level_test`.
- Offline, committed fixtures only. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Note: SMA crossover is a per-asset long-only trend strategy. The existing walk-forward test computes per-asset returns and equal-weights them. For protocol-sensitivity, adapt the approach to work with `walk_forward_analysis` (which expects panel-aware strategies) or implement a per-asset protocol-sensitivity loop. Use the same protocol family as other studies: 12-month-test family `(24,12,12)`, `(36,12,12)`, `(18,12,12)`, `(30,12,12)`.

## Constraints / environment reminders
- `pytest` not installed on PATH — run each test file with `python3`; several tests are slow (>90s), use a generous timeout.
- Do not commit unless explicitly asked.
- No profitability/capacity claim; committed verdicts remain NOT SUPPORTED.

## Approaches already tried / failed
- None for this task.

(End of file)