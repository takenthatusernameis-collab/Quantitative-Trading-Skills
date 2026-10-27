# Handoff — session 2026-10-27 (follow-up 6)

## What changed
- `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py`
  - Declared the previously unused `COST_SWEEP_LEVELS` constant (5 ascending
    commission/slippage levels: 0/0, 1bp/0, 2bp/1bp, 5bp/2.5bp, 10bp/5bp) with
    the advertised 2bp/1bp setting as the middle rung.
  - Added `_run_backtest_metrics(data_path, commission, slippage, tmpdir_path)`
    helper: a single `run_backtest.py` invocation at a given cost setting on
    the cointegrated pair fixture (multi-symbol, book pricing, chronological
    train/val/test split, point-in-time validation), returning parsed
    metrics.json.
  - Added `run_cost_sweep(data_path)`: sweeps the five levels, prints a
    per-level table (commission, slippage, Sharpe, return, verdict), asserts
    ascending order, frictionless first level, advertised middle rung, and
    monotonic non-increase of net Sharpe and total return as costs rise, and
    reports per-level verdict with failing criteria plus whether the verdict
    changes across the sweep. Mirrors the proven pattern in
    `rsi_mean_reversion_hypothesis.py` and `simple_momentum_hypothesis.py`.
  - `run_hypothesis_test(data_path, label)` now calls `run_cost_sweep(data_path)`
    and returns `cost_sweep` rows in its result dict — but only for the
    cointegrated pair fixture (the no-effect pair is a control, not a sweep
    target), so the control verdict is unaffected.
- `skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py`
  - Added `test_zscore_cost_sensitivity_sweep` (row count, ascending order,
    frictionless first level, advertised middle rung, finite values, monotonic
    degradation of Sharpe and total return, per-level verdict shape and
    failing-criteria names).
  - Added `test_run_hypothesis_test_returns_cost_sweep_on_cointegrated_pair`
    (the sweep rows are surfaced in the `run_hypothesis_test` result).
  - Registered both in TEST_REGISTRY.

## What was actually verified
- `python3 skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py`
  → exit 0. Cointegrated pair: SUPPORTED (Sharpe 0.1748, return 1.84% at
  advertised costs). Cost sweep prints 5 levels, Sharpe degrades monotonically
  0.3952 → −0.7046, return 2.18% → 0.51%, verdict changes SUPPORTED → NOT
  SUPPORTED at the 5bp/2.5bp level (failing criterion: oos_sharpe_gt_zero).
  No-effect pair: NOT SUPPORTED (Sharpe −0.7165, return −2.79%), control
  unchanged.
- `python3 skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py`
  → 9/9 passed (was 7/7; two new tests added).
- `python3 skills/quantitative-backtesting/tests/test_mean_reversion_hypothesis.py`
  → All tests passed (sibling example using the same pattern, no regression).
- `py_compile` of both modified files → OK.
- `git status --porcelain` → only the two intended files modified
  (examples + tests), +227 insertions, 0 deletions.

## What remains unresolved
- No independent out-of-sample evidence beyond synthetic fixtures (unchanged;
  the zscore sweep is a sensitivity analysis on the shipped sample, not market
  evidence).
- Slow framework suites (`test_walk_forward.py`, `test_cpcv.py`,
  `test_resolution_vs_sample_size.py`) were not re-run; untouched by this change
  and presumed unaffected. Prior handoffs record `test_walk_forward.py` at
  185 passed / 0 failed, `test_cpcv.py` at 29 passed, `test_resolution_vs_sample_size.py`
  at 79 passed.
- All four falsifiable examples now carry a cost-sensitivity sweep:
  `simple_momentum_hypothesis.py`, `mean_reversion_hypothesis.py`,
  `rsi_mean_reversion_hypothesis.py`, `zscore_mean_reversion_hypothesis.py`.
  The remaining open items are (a) re-running the slow framework suites to
  close out pending verification, and (b) pursuing independent out-of-sample
  evidence. Do not commit unless explicitly asked.

## Approaches already tried / failed
- None new; this session followed the established cost-sweep pattern from the
  three sibling examples, which was already validated by prior sessions.

## One precise next task
- Re-run the slow framework suites to confirm no regression
  (`test_walk_forward.py`, `test_cpcv.py`, `test_resolution_vs_sample_size.py`),
  recording pass/fail counts in the next handoff. Then, if a quant research
  task is still wanted, pick one bounded, evidence-based improvement from
  `skills/quantitative-backtesting/` (e.g. add a benchmark-robustness check to
  one of the falsifiable examples, or extend the cost sweep to vary the
  strategy parameters rather than only costs). Do not commit unless explicitly
  asked.

(End of file - total 62 lines)