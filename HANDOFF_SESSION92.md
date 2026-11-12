# Handoff — Session 92: FWER-adjusted simultaneous confidence bands for the Romano-Wolf stepdown

## What changed (this session)
- `skills/quantitative-backtesting/scripts/utils.py`
  - `romano_wolf_stepdown(...)` now returns FWER-adjusted **max-t simultaneous
    confidence bands** in addition to the existing marginal percentile intervals.
  - New keys: `simultaneous_ci_lower`, `simultaneous_ci_upper`,
    `simultaneous_ci_level` (`1 - alpha`), `simultaneous_ci_critical_value`,
    `simultaneous_ci_method` (`"max-t"`), all aligned to `ordered_indices`.
  - Construction: the same seeded stationary-bootstrap resamples already used by
    the stepdown produce `boot_stats`; the `1 - alpha` quantile of
    `max_k |boot_stats[b, k]|` is the critical value, and each strategy's band
    is `mean_k ± critical_value * omega_k / sqrt(T)` (studentized) or
    `mean_k ± critical_value / sqrt(T)` (unstudentized).
  - `alpha` is now validated to be in `(0, 1)`.
  - No change to the stepdown statistic, p-values, adjusted p-values, ordering,
    rejections, or the existing marginal `ci_lower` / `ci_upper` fields.
- `skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py`
  - 6 new tests: simultaneous CI contract, simultaneous width >= marginal width,
    reproducibility/seed sensitivity, benchmark subtraction, a Monte Carlo FWER
    coverage check (60 zero-mean families, T=504, K=4), and `alpha` validation.
  - Extended the unstudentized test to check the simultaneous fields.
  - Total: 18 tests.
- `skills/quantitative-backtesting/tests/test_walk_forward.py`
  - The family summary and CLI tests now assert the simultaneous CI fields are
    persisted and bracket the ordered means.
- `skills/quantitative-backtesting/tests/test_reality_check_family_example.py`
  - The example stepdown test now checks the simultaneous CI fields.
- `skills/quantitative-backtesting/examples/reality_check_family_example.py`
  - Both stepdown print blocks now show `sim95%CI=[lo, hi]` next to the
    marginal `95%CI=[lo, hi]`.
- `skills/quantitative-backtesting/SKILL.md` and
  `references/validation_methods.md`
  - Document the new fields, the `max-t` construction, the `1 - alpha` coverage,
    and the asymptotic/small-sample caveat.

## Why this task
The previous handoff's unresolved list explicitly said: "CIs remain marginal
percentile intervals, not FWER-adjusted simultaneous bands." This session closes
that gap with the smallest change: reuse the existing bootstrap resamples. It
directly serves the repository mission's "statistical uncertainty" and "honest
reporting" criteria — a family rejection now travels with an effect-size band
that controls the family-wise error rate, not just per-strategy marginal bands.

## What was actually verified (run this session)
- `python3 -m pytest skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py -q`
  -> **18 passed** (13.91 s).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check.py skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q`
  -> **12 passed** (9.05 s).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q`
  -> **5 passed** (6.50 s, after the added assertions).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -q -k "family or main_registers"`
  -> **7 passed** (1.09 s).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_examples_coverage.py -q -k "reality_check"`
  -> **2 passed** (2.47 s).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_benjamini_hochberg_fdr.py skills/quantitative-backtesting/tests/test_deflated_sharpe.py skills/quantitative-backtesting/tests/test_probabilistic_sharpe.py -q`
  -> **17 passed**.
- `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -q -k "notional_weighted_capacity_in_book_mode"`
  -> **1 passed** (no regression of the Session 85/86 book-capacity fix).
- Final combined focused run:
  `test_romano_wolf_stepdown.py test_reality_check.py test_reality_check_family_example.py`
  -> **30 passed** (22.39 s); walk-forward family subset **7 passed**;
  coverage subset **2 passed**.
- Manual `python3 skills/quantitative-backtesting/examples/reality_check_family_example.py`
  -> exit 0, "EXAMPLE COMPLETE"; raw stepdown prints
  `sim95%CI=[0.00009288, 0.00134762]` for `dual_momentum` and
  `sim95%CI=[-0.00020402, 0.00055589]` for `cross_sectional_momentum`; the
  benchmark-subtracted stepdown prints its own simultaneous bands.
- `python3 -m py_compile` on all changed .py files -> OK.
- `git diff --check` -> no whitespace errors.
- Working tree: 7 modified files, no generated artifacts, no commit (per the
  no-commit-without-request rule).

## What remains unresolved
- Full single-invocation quant gate
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -n 4`) was **not**
  rerun; it has timed out in-session in Sessions 84-91. CI is still needed for
  100% green confirmation.
- The max-t band is asymptotic. In a side measurement, T=252, K=5 families
  covered all means ~86% of the time (vs. ~95% at T=504), so the band can
  undercover on shorter samples or with highly persistent returns. The docs now
  state this caveat; the committed coverage test uses T=504 and asserts >= 90%.
- Studentization still uses full-sample Newey-West HAC variances; a
  bootstrap-variance studentization variant / sensitivity check is not
  implemented. The T=252 undercoverage above is a concrete motivation to
  investigate it.
- `reality_check_test` still returns no per-strategy CIs; only
  `romano_wolf_stepdown` has them.
- The simultaneous bands are carried by the walk-forward summary automatically
  (the whole stepdown dict is stored); there is no separate CLI flag for them.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-91.
  Do not rerun the unchanged full gate in-session.
- The full `test_examples_coverage.py` suite exceeds the 120 s command timeout
  when combined with other files. Run the `-k "reality_check"` subset.
- Do not regress
  `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`
  (Session 85/86 book-capacity fix).
- Do not use T=252 for the simultaneous-band coverage test: the observed
  coverage was ~86%, below the 90% assertion. T=504 is the committed test size.

## One precise next task (for the next agent)
Investigate the small-sample undercoverage of the new max-t bands and, if
confirmed, add a bounded, opt-in robustness improvement. Concretely:
- Reproduce the T=252 undercoverage with a small deterministic script and record
  the observed coverage vs. T (e.g., T=252, 378, 504) for K=4/5.
- Determine whether the cause is the full-sample Newey-West `omega_k` or the
  bootstrap max-statistic approximation.
- If it is the variance estimate, add an optional
  `studentize_method="bootstrap"` (or a `min_observations` warning field) to
  `romano_wolf_stepdown`, reusing the existing resamples; keep the default
  behavior unchanged.
- Add focused tests and update `references/validation_methods.md` with the
  measured coverage table.
- Constraints: offline, committed fixtures only; do not change default outputs;
  do not rerun the full gate in-session; do not commit unless explicitly asked;
  CI is needed for 100% green confirmation.