# Handoff — session 2026-10-28 (session 17)

## What changed
Added one focused regression test file at repo root:
`test_root_scripts_pit_bias_controls.py` (8 tests, ~4 s runtime).

It guards the pre-registered methodology controls the root script
`simple_momentum_hypothesis.py` advertises, without asserting on the verdict
(SUPPORTED / NOT SUPPORTED are both valid scientific outcomes):

- `test_pre_registered_criteria_are_present` — CRITERIA has exactly the 4
  pre-registered criteria (OOS Sharpe > 0, OOS total return > 0,
  Deflated Alpha Ratio > 0.5, capacity > initial capital).
- `test_advertised_costs_are_recorded` — COMMISSION=2bp, SLIPPAGE=1bp,
  CAPACITY_INITIAL_CAPITAL=$100k, DEFLATED_ALPHA_THRESHOLD=0.5.
- `test_cost_sweep_is_a_frictionless_vs_advertised_regression_guard` — the
  two-point cost sweep is (frictionless 0) vs (advertised 2bp+1bp).
- `test_cost_sensitivity_levels_are_ascending_with_advertised_in_middle` —
  5 ascending cost levels 0→10bp round-trip, advertised at the middle rung.
- `test_capacity_sweep_is_impact_disabled_vs_advertised` — capacity sweep is
  (impact disabled 0.0) vs (advertised 0.1); sensitivity levels [0, 0.05, 0.1, 0.2].
- `test_pit_and_split_are_pre_registered_in_source` — `--validate-point-in-time`
  and `--train-frac/--val-frac/--test-frac` are present in source.
- `test_run_hypothesis_test_reports_methodology_controls` — runs
  `run_hypothesis_test()` once (~1.5 s) and asserts: determinate verdict, 4
  boolean criteria, OOS Sharpe/return computed, multiple-benchmark Deflated
  Alpha control live (n_benchmarks >= 2), capacity finite and > deployed
  capital at advertised impact ($3,103,464 vs $100,000), test-resolution
  block reported (n_test_observations > 0, alpha_status,
  min_detectable_alpha, alpha_beyond_plausible_bound, plausibility bounds).
- `test_advertised_costs_are_actually_applied` — runs run_backtest at
  frictionless vs advertised costs (~2.2 s) and asserts costed Sharpe and
  total return are strictly below frictionless (catches a cost model that
  silently no-ops).

## What was actually verified
`python3 test_root_scripts_pit_bias_controls.py` → 8/8 passed.
- New test executable, cwd-independent (uses Path(__file__).parent), syntax OK.
- Only the new file is untracked; working tree otherwise clean (`git status`
  shows only `?? test_root_scripts_pit_bias_controls.py`).
- No source, example, fixture, or other test file modified.

## What remains unresolved
- None from this task. The root script's PIT/bias controls, cost liveness,
  capacity liveness, and test-resolution reporting now have a regression guard.
- The slow framework suites (`test_walk_forward.py` 192 passed, `test_cpcv.py`
  29, `test_resolution_vs_sample_size.py` 77 per prior handoffs) were not
  re-run this session (time budget); they were not touched by this change.

## Approaches already tried / failed
- None for this task. The earlier attempt to run the full
  `test_falsifiable_hypothesis_example.py` suite timed out (>10 min) because
  each test runs walk-forward; this new test deliberately runs only one
  backtest plus two cost-level backtests (~4 s total) so it stays within the
  session budget.
- Real-market fetch (`fetch_ohlcv_yahoo` in data_loader.py) and committed
  real-market CSVs + real-market machinery tests already exist in the tree
  (committed); not part of this session.

## One precise next task
Extend the same regression-guard pattern to the other two root scripts,
`debug_strategy.py` and `debug_walk_forward.py` (currently no tests cover
them): add a bounded test asserting they import cleanly, build the
`sma_crossover` strategy, generate signals, and that
`walk_forward_analysis`/`_calculate_strategy_returns` execute on a small
synthetic fixture without error. Relevant files:
`debug_strategy.py`, `debug_walk_forward.py`,
`skills/quantitative-backtesting/scripts/walk_forward.py`. Do not commit
unless explicitly asked.

(End of file)
