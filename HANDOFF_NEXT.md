# Handoff — next session

## Current state
- Session 92 added FWER-adjusted max-t simultaneous confidence bands to
  `utils.romano_wolf_stepdown`. The fields are `simultaneous_ci_lower`,
  `simultaneous_ci_upper`, `simultaneous_ci_level`, `simultaneous_ci_critical_value`,
  and `simultaneous_ci_method`; they are carried by the walk-forward family
  summary and the CLI summary JSON.
- Focused tests pass: `test_romano_wolf_stepdown.py` (18), reality-check +
  family-example tests (12), walk-forward family subset (7), coverage subset (2).
- Working tree has 7 modified files, no commit (per the no-commit rule).
- Full details, evidence, and the exact commands are in
  `HANDOFF_SESSION92.md`.

## What was actually verified
- `python3 -m pytest skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py -q` -> 18 passed.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check.py skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q` -> 12 passed.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -q -k "family or main_registers"` -> 7 passed.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_examples_coverage.py -q -k "reality_check"` -> 2 passed.
- `git diff --check` and `py_compile` on all changed files -> OK.
- Manual example run -> exit 0; both stepdown blocks print `sim95%CI`.

## What remains unresolved
- Full single-invocation quant gate was not rerun; CI is still needed for 100%
  green confirmation. Do not rerun the unchanged full gate in-session.
- The max-t band is asymptotic: a side measurement at T=252, K=5 covered all
  means ~86% of the time (vs. ~95% at T=504). The docs now state this caveat.
- Studentization still uses full-sample Newey-West HAC variances; a
  bootstrap-variance studentization variant is not implemented.
- `reality_check_test` still returns no per-strategy CIs.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-92.
- The full `test_examples_coverage.py` suite exceeds the 120 s command timeout
  when combined with other files. Run the `-k "reality_check"` subset.
- Do not regress `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`.
- Do not use T=252 for the simultaneous-band coverage test; the committed test
  uses T=504 and asserts >= 90%.

## One precise next task
Investigate the small-sample undercoverage of the new max-t bands and add a
bounded, opt-in robustness improvement if the evidence supports it:
- Reproduce coverage vs. T (252, 378, 504) for K=4/5 with a deterministic script.
- Determine whether the cause is the full-sample Newey-West `omega_k` or the
  bootstrap max-statistic approximation.
- If it is the variance estimate, add an optional `studentize_method="bootstrap"`
  (or a `min_observations` warning field) to `romano_wolf_stepdown`, reusing the
  existing resamples; keep the default output unchanged.
- Add focused tests and update `references/validation_methods.md` with the
  measured coverage table.
- Constraints: offline, committed fixtures only; do not change default outputs;
  do not rerun the full gate in-session; do not commit unless explicitly asked;
  CI is needed for 100% green confirmation.

(End of file)