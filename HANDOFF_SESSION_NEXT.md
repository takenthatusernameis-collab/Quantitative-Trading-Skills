# Handoff — Next Session: Capacity-sensitivity walk-forward family regression coverage

## Context
- HEAD `8002b6a` (main); working tree clean. Quant gate baseline green.
- Previous sessions verified: cost-sensitivity family, protocol-sensitivity family (19 tests), data-mining bias family (4 tests) — all via direct `python3`, all green, no code changes.
- All committed verdicts remain NOT SUPPORTED; PIT validation passes; no flat-signal warnings.

## Task
Run regression coverage of the **capacity-sensitivity walk-forward family** directly with `python3`, confirming no regressions from accumulated additive tests.

### Target files (capacity-sensitivity only, offline committed fixtures, direct `python3`, no commits)
Search for files matching these patterns in `skills/quantitative-backtesting/tests/`:
- `test_walk_forward_*capacity*`
- `test_walk_forward_*participation*`
- `test_walk_forward_*net_exposure*`
- `test_walk_forward_*book_mode*`

### Acceptance criteria
- Each file runs to completion with `python3 <file>` and exit code 0.
- All contained tests print PASS.
- No cell flips to SUPPORTED (all committed verdicts remain NOT SUPPORTED).
- PIT validation passes; no flat-signal warnings.
- Working tree remains clean (no engine/fixture/default-JSON changes).

### Notes
- `pytest` unavailable on PATH; direct `python3` is established convention.
- If any file is slow, bound the run per-file; leave passing direct-`python3` evidence.
- Do not commit unless explicitly asked.

(End of file)