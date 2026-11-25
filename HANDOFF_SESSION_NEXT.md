# Handoff — Next Session: EMA crossover protocol-sensitivity regression coverage

## Context
- HEAD `acb695d` (main); working tree clean. Quant gate baseline green.
- Just completed (this session): regression coverage of both EMA crossover capacity-sensitivity triple-panel test files directly with `python3` — all green, exit code 0, no cell flips to SUPPORTED, no flat-signal warnings, working tree clean.
  1. `test_ema_crossover_capacity_sensitivity_real_triple_aapl_msft_googl.py` — PASS, exit 0
  2. `test_ema_crossover_capacity_sensitivity_net_exposure_real_triple_aapl_msft_googl.py` — PASS, exit 0
- Previous sessions verified: cost-sensitivity family, protocol-sensitivity family (19 tests), data-mining bias family (4 tests), capacity-sensitivity family, cross-family reality-check walk-forward family (4 files) — all via direct `python3`, all green, no code changes.

## Task
Run regression coverage of the **EMA crossover protocol-sensitivity** test file directly with `python3`, confirming no regressions from accumulated additive tests.

### Target file (offline committed fixtures, direct `python3`, no commits)
- `skills/quantitative-backtesting/tests/test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py`

### Acceptance criteria
- File runs to completion with `python3 <file>` and exit code 0.
- All contained tests print PASS / OK.
- No cell flips to SUPPORTED (all committed verdicts remain NOT SUPPORTED).
- PIT validation passes; no flat-signal warnings.
- Working tree remains clean (no engine/fixture/default-JSON changes).
- `pytest` unavailable on PATH; direct `python3` is established convention. If slow, bound the run per-file; leave passing direct-`python3` evidence.
- Do not commit unless explicitly asked.

(End of file)
