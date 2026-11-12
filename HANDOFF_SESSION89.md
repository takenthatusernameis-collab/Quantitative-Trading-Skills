# Handoff — Session 89: Romano-Wolf Stepdown for the Strategy-Family Reality Check

## What changed
- `skills/quantitative-backtesting/scripts/utils.py`: new
  `romano_wolf_stepdown(performance, benchmark=None, n_bootstrap=1000,
  block_size=None, seed=None, studentize=True, alpha=0.05)`. Implements the
  Romano & Wolf (2005) stepdown on the same stationary block bootstrap used by
  `reality_check_test`: orders strategies by their (optionally studentized)
  statistic, tests the best *remaining* strategy at each step against the max
  bootstrap statistic over the surviving set, stops at the first non-rejection,
  and returns running-max FWER-adjusted p-values. With `K=1` it reduces exactly
  to `reality_check_test` (verified). Reuses one set of seeded bootstrap indices
  across strategies and steps.
- `skills/quantitative-backtesting/examples/reality_check_family_example.py`:
  new `run_romano_wolf_family_stepdown(...)` helper (reuses an existing family
  return matrix to avoid redundant backtests) and a Romano-Wolf section in
  `main()` printing the ordered ranking, raw p, adjusted p and rejection flags.
- `skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py`: new
  8 focused tests (K=1 equivalence to the Reality Check, dominant-strategy
  identification, no-skill no-rejection, adjusted-p monotonicity + prefix
  rejections, benchmark subtraction, unstudentized/reproducible, non-finite row
  dropping, input validation).
- `skills/quantitative-backtesting/tests/test_reality_check_family_example.py`:
  asserts the new entry point exists and runs; adds an end-to-end stepdown test
  on committed fixtures.
- `skills/quantitative-backtesting/tests/test_examples_coverage.py`: the
  `reality_check_family_example` run test now asserts the Romano-Wolf output
  lines (`Romano-Wolf stepdown`, `Rejected:`).
- `skills/quantitative-backtesting/references/validation_methods.md`: documents
  the stepdown and removes the "not yet implemented" note.
- `skills/quantitative-backtesting/SKILL.md`: mentions `romano_wolf_stepdown`
  alongside `reality_check_test`.

## Why this task
Session 88's handoff (and the state at HEAD) left the Reality Check as a
standalone utility: it could reject a family but not say *which* strategy
drove the rejection, with "Romano-Wolf stepdown not implemented" called out
explicitly in the reference docs and the `reality_check_test` docstring. This
session implements that bounded, well-defined, offline stepdown and wires it
into the committed-fixture family example, closing the documented gap.

## What was actually verified (run this session)
- Baseline reality-check tests at HEAD: `python3 -m pytest
  skills/quantitative-backtesting/tests/test_reality_check.py
  skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q`
  -> **10 passed** (Session 88 expected 9; the extra test is the
  benchmark-subtracted test already present at HEAD).
- New focused suite: `python3 -m pytest
  skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py -q`
  -> **8 passed** (2.37s).
- Combined focused: `python3 -m pytest
  skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py
  skills/quantitative-backtesting/tests/test_reality_check.py
  skills/quantitative-backtesting/tests/test_reality_check_family_example.py
  skills/quantitative-backtesting/tests/test_benjamini_hochberg_fdr.py
  skills/quantitative-backtesting/tests/test_deflated_sharpe.py -q`
  -> **29 passed** (6.31s).
- Coverage registration: `python3 -m pytest
  skills/quantitative-backtesting/tests/test_examples_coverage.py -q -k
  "reality_check"` -> **2 passed** (1.90s).
- Manual example run: `python3
  skills/quantitative-backtesting/examples/reality_check_family_example.py` ->
  exit 0, "EXAMPLE COMPLETE". Raw family: p=0.016 significant. Romano-Wolf:
  `Rejected: 1 of 2`, rank 0 `dual_momentum` adj_p=0.012 rejected=True, rank 1
  `cross_sectional_momentum` adj_p=0.162 rejected=False. No profitability
  claim; this is a multiple-testing control demonstration.
- `python3 -m py_compile` on all changed .py files -> OK.
- `git diff --check` -> no whitespace errors.
- Working tree after runs: only the 6 intended modified files plus the 1 new
  test file; no `example_output/` timestamp drift this run.

## What remains unresolved
- Full single-invocation quant gate
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -n 4`) still cannot
  complete in-session (~60+ min environmental timeout, per Sessions 84-88). Not
  retried unchanged. A CI run is still needed for 100% green confirmation.
- The stepdown is a standalone utility/example, like the Reality Check; it is
  not wired into the walk-forward summary or a CLI. Wiring a family path into
  `run_walk_forward`/CLI is a larger design step.
- The stepdown reuses full-sample Newey-West HAC variances for studentization
  (consistent with Hansen 2005); it does not recompute a bootstrap variance per
  resample. This is the documented standard, but a sensitivity check against a
  bootstrap-variance variant is not implemented.
- No per-strategy effect-size / confidence interval is returned; the output is a
  ranking and rejection decision only.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-85.
  Do not rerun the unchanged full gate in-session.
- The full `test_examples_coverage.py` suite (all examples via subprocess)
  exceeds the 120 s command timeout when combined with the other files in one
  invocation. Run the relevant `-k "reality_check"` subset instead; the rest of
  that suite is slow but not known to fail.
- Do not regress
  `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`
  (Session 85/86 book-capacity fix).

## One precise next task (for the next agent)
Add a committed-fixture, offline example/test for the stepdown's
benchmark-subtracted path end-to-end: extend
`run_romano_wolf_family_stepdown` in
`examples/reality_check_family_example.py` to accept a `benchmark` argument
(aligning the buy-and-hold MSFT per-period returns to the family OOS dates the
same way `run_reality_check_family_example_benchmark_subtracted` does), call
`romano_wolf_stepdown(..., benchmark=bench_aligned)`, and add a focused test in
`tests/test_reality_check_family_example.py` asserting the aligned lengths,
reordering and that benchmark subtraction changes the adjusted p-values. Keep it
committed-fixture/offline/additive; do not change default outputs that existing
coverage assertions depend on. Verify with `python3 -m pytest
skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py
skills/quantitative-backtesting/tests/test_reality_check_family_example.py
-q` and the `-k "reality_check"` coverage subset. Do not commit unless
explicitly asked; do not rerun the full gate in-session; CI is needed for 100%
green confirmation.