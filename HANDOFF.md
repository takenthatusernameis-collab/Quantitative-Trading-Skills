# HANDOFF

## Repository state (as of this session)

- Working tree has uncommitted changes (1 file: test_walk_forward.py). No commits made this session.
- Test suite: **278/278 passing** (`python3 -m pytest skills/quantitative-backtesting/tests/ -q`), up from 277 (1 new test added).
- Standalone runner `python3 skills/quantitative-backtesting/tests/test_walk_forward.py`: **82/82 passed** (was 81).
- Root end-to-end script `verify_end_to_end.py`: **passes, exit 0**.

## What changed this session

### Extended the four-path DSR parity invariant to the cost-sweep artifacts

The prior handoff's parity work (`test_deflated_sharpe_parity_across_all_four_analysis_paths`) guarded the single-run paths (walk-forward / cpcv / out-of-sample / monte-carlo). The cost sweeps (`--impact-coefficients`, `--borrow-costs`, `--funding-costs`) re-run the same pipelines and record per-coefficient `deflated_sharpe` + `deflated_sharpe_n_trials` rows, but **no test asserted the DSR correction basis was consistent across coefficients** — a regression in per-coefficient trial counting would have gone unnoticed while the sweep still "ran".

**Added `test_cost_sweep_dsr_parity_across_paths` in `skills/quantitative-backtesting/tests/test_walk_forward.py`:**
- Runs all four impact sweeps on the same 9-combo grid / 600-period data (seed 11), with the DSR gate enabled (`--deflate` for walk-forward/oos/cpcv, `--n-trials 500` for monte-carlo).
- For each sweep artifact asserts:
  - 3 rows written, `deflated_sharpe` present and in [0, 1] for every row.
  - `deflated_sharpe_n_trials` is **coefficient-stable** (identical across the 3 coefficients) — the grid is unchanged, so the counting basis cannot drift.
  - `n_trials >= 1`.
- Registered in `main()`'s test list.

**No production code changed.** This is a test-only change; behavior is unchanged. The test passes (verified: 278/278).

## Empirically verified sweep DSR basis (evidence, not assumption)

On the canonical 9-combo grid / 600-period data (seed 11), the impact sweeps currently emit:

| path | n_trials (per coeff) | DSR[0] |
|------|---------------------|--------|
| walk-forward | 44, 44, 44 | 0.1450 |
| out-of-sample | 9, 9, 9 | 0.1605 |
| cpcv | 15, 15, 15 | 0.0114 |
| monte-carlo | 9, 9, 9 | 0.3447 |

Each path is internally coefficient-stable (the invariant this test guards). The paths differ from each other because they count different things (walk-forward sums evaluated combos across periods; oos/monte-carlo count one grid traversal; cpcv counts across folds) — same as the single-run parity finding, and not a bug.

## What remains unresolved

- The four paths still report different absolute `n_trials` (44 vs 9 vs 15) because they legitimately count different bases; only the within-path coefficient stability is now guarded.
- `monte-carlo` gates the DSR on `--n-trials`, not `--deflate`; the test passes the equivalent flag. No schema change.
- Candidate follow-ups (pick one):
  1. **Borrow/funding/commission/slippage sweep parity**: the same coefficient-stability check for the non-impact sweeps (currently only the impact sweep is guarded by this test).
  2. **Degenerate/constant-return DSR consistency**: `deflated_sharpe_ratio` emits DSR=0/p=1 for zero-variance returns; verify all four sweep paths emit identical degenerate dicts (currently OOS uses `len(oos_returns) > 1`, monte-carlo uses `len(returns.dropna()) >= 2`).
  3. **Document the DSR methodology** in `skills/quantitative-backtesting/SKILL.md` or a references file, since the parity invariant is now executable-guarded but not yet written down for researchers.

(End of file)