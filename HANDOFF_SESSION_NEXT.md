# Handoff — Next Session: EMA crossover capacity-sensitivity triple-panel regression coverage

## Context
- HEAD `acb695d` (main); working tree clean. Quant gate baseline green.
- Just completed (this session): regression coverage of all 4 cross-family reality-check walk-forward test files directly with `python3` — all green, exit code 0, no cell flips to SUPPORTED, all pinned regression values match exactly, working tree clean.
  1. `test_walk_forward_cross_family_reality_check_real_triple.py` — 6/6 PASS (RC p=0.1310, NOT SUPPORTED)
  2. `test_walk_forward_cross_family_reality_check_5family_real_triple.py` — 6/6 PASS (RC p=0.1630, NOT SUPPORTED)
  3. `test_walk_forward_cross_family_cpcv_reality_check_5family_real_triple.py` — 6/6 PASS (CPCV RC p=0.2610, NOT SUPPORTED; verdict stable vs walk-forward: YES)
  4. `test_walk_forward_cross_family_meta_analysis_real_triple.py` — 5/5 PASS (Bonferroni adjusted p=0.4981, n_rejected=0, NOT SUPPORTED)
- All committed verdicts remain NOT SUPPORTED; PIT validation passes; no flat-signal warnings.
- Previous sessions verified: cost-sensitivity family, protocol-sensitivity family (19 tests), data-mining bias family (4 tests), capacity-sensitivity family — all via direct `python3`, all green, no code changes.

## Task
Run regression coverage of the **EMA crossover capacity-sensitivity triple-panel** test files directly with `python3`, confirming no regressions from accumulated additive tests.

### Target files (EMA crossover capacity only, offline committed fixtures, direct `python3`, no commits)
Search for files matching these patterns in `skills/quantitative-backtesting/tests/`:
- `test_ema_crossover_capacity_sensitivity_real_triple_aapl_msft_googl.py`
- `test_ema_crossover_capacity_sensitivity_net_exposure_real_triple_aapl_msft_googl.py`

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
