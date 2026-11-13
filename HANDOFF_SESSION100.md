# Handoff — Session 100: fix undeclared `scipy` runtime dependency (+ static guard)

## What changed
- `skills/quantitative-backtesting/requirements.txt`: added `scipy` (with a comment).
  - Root cause: `scripts/utils.py` imports `scipy.cluster.hierarchy` /
    `scipy.spatial.distance` for `hierarchical_risk_parity` (HRP), but the
    documented runtime requirements listed only `matplotlib`, `numpy`,
    `pandas`. A clean `pip install -r requirements.txt` therefore could not
    run HRP, its 15 tests, or its worked example.
- Added `skills/quantitative-backtesting/tests/test_requirements_declared_dependencies.py`
  (new file, 2 tests):
  - `test_runtime_third_party_imports_are_declared`: AST-scans `scripts/*.py`,
    subtracts stdlib + local module names, and asserts every remaining
    third-party import is declared in `requirements.txt`. Standard-library only,
    so it runs without the packages installed.
  - `test_scipy_declared_for_hierarchical_risk_parity`: explicit regression
    guard for this defect.

## What was actually verified
- Pre-fix failure reproduced on this environment (no scipy): 15
  `test_hierarchical_risk_parity.py` tests failed with
  `ImportError: hierarchical_risk_parity requires scipy`.
- After `pip install scipy` (1.18.1) and the requirements edit:
  - `tests/test_requirements_declared_dependencies.py tests/test_hierarchical_risk_parity.py`
    -> **17 passed in 0.78s**.
  - `test_hrp_portfolio_allocation_example_runs` (subprocess) -> passed.
- Negative control for the guard: with a temp requirements file containing only
  `matplotlib/numpy/pandas`, the guard reports `['scipy']` as missing — i.e. it
  would have caught this defect before the fix.
- Broader regression evidence on this environment (Python 3.14.4, numpy 2.5.4,
  pandas 3.1.1, scipy 1.18.1, pytest 9.x):
  - core batch (`test_out_of_sample_window`, `test_no_selection_diagnosis`,
    `test_execution_warmup`, `test_test_window_observations`,
    `test_cpcv_records_regime_analysis`, `test_regime_concentration_diagnostic`,
    `test_walk_forward_records_regime_robustness`,
    `test_monte_carlo_records_regime_robustness`, `test_strategy_cost_model`,
    `test_point_in_time_strict_abort_on_violation`) -> **98 passed in 66s**.
  - `test_walk_forward.py test_reporting.py test_run_backtest.py` ->
    **395 passed in 492s**.
  - earlier multiple-testing batch -> **43 passed**.
- `git status --porcelain` after reverting test-run drift contains only:
  - `M skills/quantitative-backtesting/requirements.txt`
  - `?? skills/quantitative-backtesting/tests/test_requirements_declared_dependencies.py`

## What remains unresolved
- **Not committed.** No explicit commit request was given; changes are left in the
  working tree.
- **CI does not install `requirements.txt`.** `.github/workflows/validate-skills.yml`
  only runs `skills-ref validate`; it never installs the skill's requirements, so
  this dependency fix (and the HRP suite) are not exercised in CI.
- **Stale committed example outputs.** Running the examples regenerates tracked
  files under `skills/quantitative-backtesting/examples/example_output/`
  (`report.txt`, `tear_sheet.html`, `multiple_benchmarks_metrics.json`,
  `data_provenance.json`) and dirties the tree. The committed copies predate the
  current code (they lack the "Test Resolution" section and BH-FDR fields). Only
  `scripts/results/` is gitignored, not `examples/example_output/`. I reverted the
  drift this session to keep the change set minimal.
- **HRP is undocumented.** `grep -rni "hrp\|hierarchical" SKILL.md references/*.md`
  returns nothing, although `utils.hierarchical_risk_parity` and
  `examples/hrp_portfolio_allocation_example.py` exist and are tested.

## Approaches already tried / failed (do not repeat unchanged)
- Sessions 95–99 repeatedly restored the `quant-regression-gate` CI job; it was
  removed again each time, and pushing `.github/workflows/*` fails with
  `refusing to allow a GitHub App to create or update workflow ... without
  workflows permission`. That line of work is blocked on GitHub App permissions —
  do not re-attempt the same restore/push cycle without new access.
- Full `pytest tests/` in one invocation times out in-session (~60+ min); use the
  chunked batches above.

## One precise next task
Add a CI step that installs the skill's declared runtime dependencies and runs the
fast dependency/HRP slice, so the `scipy` declaration (and any future missing
dependency) is actually exercised. Concretely, in
`.github/workflows/validate-skills.yml`, add a job/step with working-directory
`skills/quantitative-backtesting` that runs
`pip install -r requirements.txt pytest` then
`PYTHONPATH=scripts python3 -m pytest tests/test_requirements_declared_dependencies.py tests/test_hierarchical_risk_parity.py "tests/test_examples_coverage.py::test_hrp_portfolio_allocation_example_runs" -q`.
Evidence to compare locally: 17 passed for the first two files, and the HRP
example subprocess exits 0. This is blocked on the same `workflows` permission as
above only if the workflow file must be pushed; if permission is still missing,
prepare the diff and hand it off rather than retrying the blocked push.