# Handoff — Next Session: EMA crossover base real walk-forward regression coverage

## Context
- HEAD `bfe5283` (main); working tree clean. Quant gate baseline green.
- Just completed (this session): regression coverage of `test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py` directly with `python3` — all green, exit code 0, no cell flips to SUPPORTED, no flat-signal warnings, working tree clean.
  - 4/4 tests passed: protocol_sensitivity_matrix_pinned, verdict_is_consistently_not_supported, no_cell_survives_protocol_multiplicity, main_registers_every_module_level_test.
- Previous sessions verified: cost-sensitivity family, protocol-sensitivity family, data-mining bias family (4 tests), capacity-sensitivity family, cross-family reality-check walk-forward family (4 files), EMA crossover capacity-sensitivity triple-panel (2 files) — all via direct `python3`, all green, no code changes.

## Task
Run regression coverage of the **base EMA crossover real walk-forward** test file directly with `python3`, confirming no regressions from accumulated additive tests.

### Target file (offline committed fixtures, direct `python3`, no commits)
- `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_real_aapl.py`

### Acceptance criteria
- File runs to completion with `python3 <file>` and exit code 0.
- Contained tests print OK (`test_walk_forward_ema_crossover_real_aapl_runs` + `test_walk_forward_ema_crossover_real_aapl_metrics_pinned`).
- Committed verdict remains NOT SUPPORTED: Deflated Sharpe p-value >= 0.10 fails; `assert all(passes.values()) is False` holds.
- Working tree remains clean (no engine/fixture/default-JSON changes).
- `pytest` unavailable on PATH; direct `python3` is established convention. If slow, bound the run per-file; leave passing direct-`python3` evidence.
- Do not commit unless explicitly asked.

(End of file)
