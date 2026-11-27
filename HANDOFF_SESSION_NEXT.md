# Handoff — DSR monotonic-degradation sweep guard added; focused suite green

## What changed (this session)
- Added `test_dsr_monotonic_degradation_across_trial_sweep` to
  `skills/quantitative-backtesting/tests/test_deflated_sharpe.py` (and registered
  it in that file's `__main__` runner).
- The test sweeps `n_trials` over `[1,2,3,5,10,25,50,100,500,1000,5000]` and
  asserts the Deflated Sharpe Ratio is non-increasing at every step, on BOTH the
  i.i.d.-normal null path and the `trial_sharpes` dispersion path, and that the
  sweep actually deflates (`values[-1] < values[0]`).
- No production code changed. `deflated_sharpe_ratio` in
  `skills/quantitative-backtesting/scripts/walk_forward.py:2360` already yields a
  monotone DSR because `sr_star` grows with `ln(n_trials)`, so `z` and
  `Phi(z)` fall. This test pins that invariant (the prior test only compared the
  two endpoints 5 vs 5000).
- Scope: 1 file, +28 lines. `git diff --stat` clean otherwise.

## What was actually verified (evidence)
- `python3 skills/quantitative-backtesting/tests/test_deflated_sharpe.py` →
  `ALL TESTS PASSED` (now 7 tests).
- `python3 .../test_deflated_sharpe_reproducibility.py` → `ALL TESTS PASSED`.
- `python3 .../test_probabilistic_sharpe.py` → `ALL TESTS PASSED`.
- Manual pre-check confirmed strict monotone decline on both paths (e.g. i.i.d.
  DSR 0.920 → 0.003; trial_sharpes 0.920 → 0.089 across the sweep).
- `pytest` is NOT installed in this env (`No module named pytest`); the repo's
  portable default `python3 <file>` was used, per `tests/README.md`.

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data`
  CSVs are placeholders/synthetic (MSFT==sample_benchmark, AAPL==sample_ohlcv,
  GOOGL==AAPL.bak). Regression guards test committed data only, NOT real
  securities. Restoring authentic data needs network (unavailable offline) — do
  NOT fabricate. See PROVENANCE.json and HANDOFF_SESSION_164.md.
- Full 245-test `test_walk_forward.py` registry was NOT re-run this session (it is
  ~8 min and unrelated to this change); the change is isolated to a standalone
  focused test file.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned; use
  foreground timed batches. (Prior sessions.)
- `pytest` invocation fails (module absent); use `python3 <file>` directly.

## One precise next task (bounded, evidence-based)
Pick ONE of the remaining handoff options and deliver a focused test + minimal
code if needed:
1. **Cross-method capacity comparison** — `CROSS_METHOD_CAPACITY_COMPARISON.md`
   describes comparing `panel_pricing="net-exposure"` vs `"book"`. Implement a
   test that runs the same market-neutral strategy under both and quantifies the
   capacity gap. (Note: `test_ema_crossover_capacity_sensitivity_net_exposure_*`
   already exists as a partial precedent to reuse.)
2. **Regime-aware impact validation** — extend `--regime-impact-coefficients`
   with a walk-forward test showing regime-specific impact yields different
   capacity than the flat model on regime-labeled data.
Verify with `python3 <test_file>` (pytest unavailable). Keep scope to one file;
do not touch the inherited marketplace catalog.