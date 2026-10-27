# Handoff — session 2026-10-27 (follow-up 7)

## What changed
No source changes this session. Working tree is clean; all Session 8 changes (zscore cost-sensitivity sweep + tests) are already committed. This session executed the outstanding handoff item: re-running the slow framework suites.

## What was actually verified
All three slow framework suites were run against the committed tree:

| Suite | Result |
|-------|--------|
| `skills/quantitative-backtesting/tests/test_walk_forward.py` | 191 passed, 0 failed |
| `skills/quantitative-backtesting/tests/test_cpcv.py` | 29 passed, 0 failed |
| `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` | 72 passed, **7 failed** (pre-existing on clean tree) |

The walk-forward and CPCV suites show no regression. `test_resolution_vs_sample_size.py` has 7 failures that exist on the clean, committed tree (I made no changes to it or to any framework script), so they are NOT regressions from this session. Prior handoffs recorded this suite at 79 passed, so something in the committed state now produces different resolution numbers than the tests expect.

## Evidence for the 7 failures (single consistent root cause)
All 7 failures indicate the framework's statistical-resolution measurement now reports LOWER minimum-detectable effects at small samples than the test expectations — i.e. things previously "unpriceable" or "beyond the plausibility bound" are now priceable / within bound:

- `test_the_crossing_is_not_a_property_of_one_random_draw` — at 2500 bars, seed=1, effect=True: `min_detectable_sharpe=1.9147509076281488`, `sharpe_beyond_plausible_bound=False`; test expects `> 2.0` (beyond bound) at the 2500-bar rung. Reproduced directly via `measure_synthetic(2500, 1, True)`.
- `test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes` — `by_path[WALK_FORWARD]["first_size_all_within_bound"]` is 2500, test expects 5000 (`assert 2500 == 5000`).
- `test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound` — `by_path[CPCV]["first_size_any_within_alpha_bound"]` is 2500, test expects 5000 (`assert 2500 == 5000`).
- `test_the_effect_series_sweep_crossings_are_pinned` — at 5000 bars `first_any=0.1`, test expects 0.2 (`assert first_any == 0.2`).
- `test_an_unpriceable_alpha_floor_is_reported_as_unpriceable` — the reproducer's Deflated Alpha criterion, previously unpriceable, is now priced by the framework.
- `test_an_unpriceable_sharpe_floor_is_reported_as_unmeasurable` — `assert False is True`.
- `test_a_measured_sharpe_floor_is_still_reported` — `assert 'not_applicable' == 'resolvable'`; the floor is now reported as `resolvable` instead of `not_applicable`.

Root-cause hypothesis (unverified): the resolution computation in `scripts/measure_resolution_vs_sample_size.py` (`_build_test_resolution`, fed by `walk_forward.py`/`cpcv_analysis`/`out_of_sample_validation` `test_resolution` blocks) now yields smaller minimum-detectable Sharpe/alpha at 2,500–5,000 bars. Either the framework's resolution genuinely improved (then test expectations are stale and must be re-pinned against re-run measurements) or there is a regression that overstates resolution (then the framework must be fixed). Direction not yet determined — do not flip test expectations without establishing which.

## What remains unresolved
- The 7 `test_resolution_vs_sample_size.py` failures (pre-existing, isolated, not caused by this session).
- Independent out-of-sample evidence beyond synthetic fixtures (still open; no market data wired in).

## Approaches already tried / failed
- None new this session. The prior sessions' cost-sweep pattern is complete across all examples (simple_momentum, mean_reversion, rsi_mean_reversion, zscore_mean_reversion, falsifiable_hypothesis), each with a registered sweep test.

## One precise next task
Investigate the 7 `test_resolution_vs_sample_size.py` failures:
1. Re-run `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` to confirm the same 7 failures (it is slow: ~4–5 min).
2. Read `scripts/measure_resolution_vs_sample_size.py` `_build_test_resolution` and the `test_resolution` blocks in `scripts/walk_forward.py` to determine whether the lower minimum-detectable effects at 2,500–5,000 bars are a legitimate framework improvement or an overstatement of resolution.
3. If legitimate improvement: re-pin the affected test expectations against re-run measurements (do not hand-tune). If regression: fix the framework with the smallest change and verify all 7 tests plus `test_walk_forward.py`/`test_cpcv.py` remain green.
Constraint: do not flip test expectations without first establishing the direction; these tests guard statistical-resolution honesty, which is core to the quant-research mission. Do not commit unless explicitly asked.
