# Handoff — session 2026-10-28

## What changed
- `simple_momentum_hypothesis.py` (repo root) — added a capacity-sensitivity sweep:
  - New constant `CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]` (ascending market-impact coefficients), kept separate from `CAPACITY_SWEEP_SETTINGS` so the existing two-point regression guard (impact disabled vs advertised) and the cost sweeps that reuse its final level are undisturbed.
  - New `run_capacity_sensitivity_sweep()` runs the CLI backtest at each impact level and asserts the honest directional claim: capacity = max_impact * ADV_notional / impact_coefficient falls as impact_coefficient rises; impact disabled (0.0) reports `capacity=None`; all finite estimates are positive and strictly decreasing.
  - `main()` now calls `run_capacity_sensitivity_sweep(data_path)` after `run_capacity_sweep()`.
- `skills/quantitative-backtesting/tests/test_simple_momentum_hypothesis.py` — added `test_root_capacity_sensitivity_sweep_falls_with_impact` (imports the root script by path to avoid the examples/ sibling, runs the sweep, asserts ascending levels, None at impact 0.0, >=2 finite positive readings, strictly decreasing capacity, and that the advertised impact level is covered) and wired it into `__main__`.

## What was actually verified
- Empirically confirmed capacity scales exactly 1/impact_coefficient on the shipped sample (0.05→$6,206,928; 0.1→$3,103,464; 0.2→$1,551,732; 0.0→None) before asserting monotonicity — the claim is mathematically guaranteed, not assumed.
- `test_root_capacity_sensitivity_sweep_falls_with_impact` → PASS.
- Full `test_simple_momentum_hypothesis.py` → **All tests passed** (7 tests; includes the subprocess run of the full root script which now also exercises the new sweep).
- `py_compile` → OK for both modified files.
- Regression confirmation from prior handoffs still holds: `test_resolution_vs_sample_size.py` 79/79 passed, `test_walk_forward.py` 192/192 passed (verified this session via full runs).
- Reverted unintended regeneration of `skills/quantitative-backtesting/examples/example_output/*` (timestamps/float-repr/chart-divs) so the diff stays scoped to the two intended files.
- No Python lint/typecheck tooling is configured in this repo (no ruff/flake8/pyproject); compile check used instead.
- Did NOT commit (working tree has only the two intended modified files).

## What remains unresolved
- No blocker. The quant research machinery (cost sensitivity, deflated alpha/DAR, PIT, train/val/test split, capacity, borrow/funding/impact) is complete and green across examples + root scripts + slow framework suites.

## Approaches already tried / failed
- None for this task. Capacity monotonicity was verified empirically before asserting; no failed approach.

## One precise next task
- Run the broader focused suites to confirm the shared cost/backtest machinery remains green after touching `simple_momentum_hypothesis.py`:
  `python3 skills/quantitative-backtesting/tests/test_examples_coverage.py` and
  `python3 skills/quantitative-backtesting/tests/test_strategy_cost_model.py`
  Run each to completion and record pass/fail counts. If both green, the session is complete with no outstanding task. Do not commit unless explicitly asked.
  Relevant files: `skills/quantitative-backtesting/tests/test_examples_coverage.py`,
  `skills/quantitative-backtesting/tests/test_strategy_cost_model.py`.
