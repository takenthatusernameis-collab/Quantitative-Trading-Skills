# Handoff — Session 87: Family-wise Reality Check (White 2000 / Hansen 2005)

## What changed
- `skills/quantitative-backtesting/scripts/utils.py`: added two helpers
  (`_newey_west_long_run_variance`, `_stationary_bootstrap_indices`) and the
  public `reality_check_test(performance, benchmark=None, n_bootstrap=1000,
  block_size=None, seed=None, studentize=True, alpha=0.05)`. Purely additive —
  no existing function was modified. It implements White's (2000) Reality Check
  for a family of K strategies vs a benchmark, with the optional studentized
  (Hansen 2005 SPA-style) statistic, a seeded stationary (Politis-Romano) block
  bootstrap that resamples the *same* time indices for every strategy (so
  cross-sectional dependence is preserved), Newey-West HAC standard errors, and
  listwise deletion of non-finite rows. Returns `test_statistic`, `p_value`,
  `studentized`, `n_strategies`, `n_observations`, `block_size`,
  `n_bootstrap`, `best_index`, `best_mean`, `means`, `alpha`, `significant`.
- `skills/quantitative-backtesting/tests/test_reality_check.py`: new focused
  test file (7 tests) — no-skill high p-value, dominant strategy rejects,
  benchmark subtraction, unstudentized/1-D equivalence, seeded reproducibility,
  NaN-row dropping, input validation.
- `references/validation_methods.md`: new "Family-Wise Reality Check" section.
- `SKILL.md`: added a capability bullet.

## Why this task
The Session 86 next-task was: re-run the focused checks (done below), run the
full gate (blocked, see unresolved), then select a bounded methodological gap.
Session 80/81 documented "reality-check (White's Reality Check / Romano-Wolf)
over the full hypothesis family" as an *unimplemented* multiple-testing control,
distinct from the now-implemented DSR and Benjamini-Hochberg FDR. This closes
the raw Reality Check portion.

## What was actually verified (all run this session, deps present)
- Pre-change baseline reproduced at HEAD `c36b3f4`:
  - `test_walk_forward.py`: **200 passed** (273s).
  - `test_cpcv.py`: **29 passed** (52s).
  - Restored `examples/example_output/*` timestamp drift; working tree clean.
- Post-change focused evidence:
  - `tests/test_reality_check.py`: **7 passed**.
  - `tests/test_reality_check.py + test_benjamini_hochberg_fdr.py +
    test_deflated_sharpe.py`: **17 passed**.
  - `tests/test_strategy_cost_model.py + test_execution_warmup.py`:
    **27 passed**.
  - `tests/test_performance.py`: **34 passed**.
  - `python3 -m py_compile scripts/utils.py`: OK.
- Robustness spot-check of the no-skill case across seeds (2000 bootstraps):
  p = 0.366 / 0.493 / 0.991 / 0.952 — comfortably above 0.05, not a flaky pass.
  Dominant-edge case: p < 1e-4.

## What remains unresolved
- Full single-invocation quant gate (`pytest skills/quantitative-backtesting/tests/ -n 4`)
  still cannot complete in-session (~60+ min environmental timeout, failed
  repeatedly in Sessions 84-85). Not retried unchanged this session per the
  change-approach rule. Last chunked evidence (Session 85) was 1196 passed /
  1 failed; that one failure was fixed in Session 86. A CI run is still needed
  to confirm 100% green.
- The Reality Check is a **standalone utility**, not yet wired into any CLI or
  the walk-forward summary, because those paths run a *single* strategy and the
  test needs a family of per-period return series. No end-to-end "family run"
  exists that emits a K-column return matrix.
- Identifying *which* strategy in a rejected family is best requires a stepdown
  procedure (Romano-Wolf). Not implemented; documented as future work.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-85.
- Book-capacity "fix via asymmetric quantiles": misdiagnosis (Session 85); root
  cause was the NaN warmup seed, fixed in Session 86.
- Do not regress `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`;
  it passes at HEAD.

## One precise next task (for the next agent)
1. Confirm the additive change at HEAD:
   `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check.py -q`
   (expect 7 passed). Working tree should contain only the four intended files.
2. Add an end-to-end wiring so the Reality Check is actually usable: either
   (a) a small `examples/reality_check_family_example.py` that builds a K-column
   OOS return matrix from committed fixtures (reuse the `compare_dual_vs_cross_sectional_triple.py`
   pattern: run `run_backtest.py` per strategy, read the per-period equity/returns)
   and calls `reality_check_test`, plus a test that runs it; or (b) extend the
   Monte Carlo path to accept a family. Prefer (a) — smallest, offline, bounded.
   Constraint: offline/committed fixtures only; no live network.
3. Do not commit unless explicitly asked. Keep the working tree clean
   (`git checkout -- skills/quantitative-backtesting/examples/example_output/`
   after test runs to clear timestamp drift).