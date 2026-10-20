# Next task — 2026-10-20 (session)

## Task

**Rename `test_n_periods` -> `test_n_observations` in the framework's `test_performance` (the held-out window counts test *bars*, not periods), with a parity harness.**

## Why this is the next thing

The held-out-fraction sweep task is complete: `print_test_frac_sweep` now prints the alpha columns/crossings, the sweep was run at 5,000 and 10,000 bars, and `tests/test_resolution_vs_sample_size.py` is 16/16 pinning the sweep's alpha numbers against the framework's own blocks.

The one outstanding API change from HANDOFF.md is the `test_n_periods` rename. The framework emits `"test_n_periods": len(test_returns)` in `test_performance` (`walk_forward.py:5797`) and `out_of_sample_validation` passes it through (`walk_forward.py:10148`), but that value is the number of test *bars*, not periods. The example already reports `test_n_observations`, and `tests/test_falsifiable_hypothesis_example.py:256-257` asserts `obs["test_n_observations"] == 100` and `"test_n_periods" not in obs`. `references/validation_methods.md:1365-1369` documents the distinction. This is a breaking API change that needs its own parity harness so nothing consuming `test_n_periods` breaks silently.

## Evidence and constraints

- `walk_forward.py:5797`: `"test_n_periods": len(test_returns)` inside `test_performance` (within `out_of_sample_validation`/`walk_forward_analysis`).
- `walk_forward.py:10148`: `out_of_sample_validation`'s returned `test_performance` re-emits `test_n_periods`.
- `tests/test_falsifiable_hypothesis_example.py:250-257`: `test_the_test_window_is_reported_in_observations_not_periods` — `obs["test_n_observations"] == 100`, `"test_n_periods" not in obs`.
- `references/validation_methods.md:1365-1369`: the held-out window is counted in observations, not periods; "100" is not 100 independent periods.
- Constraint: this is a breaking API change — rename only `test_n_periods` (test bars) in `test_performance`, NOT `summary.n_periods` (`walk_forward.py:1446`, `3088`, which is the number of walk-forward periods and is correctly named) and NOT reporting.py:728's `("Number of Periods", "n_periods", ...)` (reads the walk summary diagnostic). No threshold, bound, criterion or verdict moves.
- Verification: add/extend a parity test that every consumer of `test_performance` reads `test_n_observations` and that `test_n_periods` is no longer emitted; run the neighbouring suites (`test_falsifiable_hypothesis_example.py`, `test_out_of_sample_window.py`, `test_walk_forward.py`, `test_run_backtest.py`, `test_reporting.py`, `test_cpcv.py`) to confirm no regressions.

## Subsequent options (after this task)

- Re-run the held-out-fraction sweep on the effect series (inject_effect=True) at 5,000 / 10,000 bars; so far only no_effect has been measured at those sizes.

(End of file)
