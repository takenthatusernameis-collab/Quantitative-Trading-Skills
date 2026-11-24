# Handoff — Session: multiplicity-control regression slice green; reproducibility determinism guard added

## Status entering this session
- HEAD `6de4bdd` (main); working tree clean except one new untracked file:
  `skills/quantitative-backtesting/tests/test_statistical_engine_determinism_regression.py` (OK, exit 0; intentionally uncommitted — no commit requested).
- All previously assigned handoff tasks complete and committed (multiplicity-control baseline across all five triple-panel families confirmed; full quant gate 1196/1197 with one known non-blocking artifact-mutation failure).

## What changed this session
- Ran the remaining 4 multiplicity-control regression tests (`python3`, offline, committed fixtures, no modifications): all 2/2 PASS, exit 0, NOT SUPPORTED verdicts (SMA crossover, TSMOM, dual momentum, cross-sectional momentum).
- Added `test_statistical_engine_determinism_regression.py` — reproducibility hardening: identical inputs + identical seed -> bit-identical Reality Check / Romano-Wolf outputs; `py_compile` COMPILE_OK.

## What was verified (with evidence)
- 4 multiplicity-control regression tests: 2/2 PASS each, exit 0.
- New determinism test: OK, exit 0.
- `git status`: only the new untracked file; `git diff --stat` empty.

## What remains unresolved
- The new determinism test file is untracked/uncommitted (commit only if explicitly requested).
- One precise next task below (capacity-aware sizing opt-in guard) is not yet started.

## Approaches already tried / failed
- None this session (all green; no failures).

## One precise next task (bounded, evidence-based)
**Capacity-aware sizing opt-in guard.** `run_backtest.py` exposes `--max-impact` (capacity-aware position cap; unset = no scaling, so no published number moves — see `run_backtest.py:83-86`), and the existing capacity-sensitivity test
`test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py` documents the convention.
Add a bounded test: run `run_backtest.py` on a committed single-asset fixture twice (without `--max-impact`, and with a binding `--max-impact`) and assert:
  (a) unset flag leaves output unchanged (opt-in, no published-number movement);
  (b) with a binding cap, estimated per-trade impact stays below the threshold and traded notional is reduced.
Constraints: additive file only; offline; committed fixtures only; direct `python3 <file>` execution (pytest unavailable on PATH); do not modify existing tests/fixtures/engine. Expect each run to print its result and exit 0; allow ~1-2 minutes per run.

(End of file)
