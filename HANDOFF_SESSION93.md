# Handoff — Session 93: max-t simultaneous band small-sample coverage investigation and warning

## What changed (this session)
- `skills/quantitative-backtesting/scripts/utils.py`
  - `romano_wolf_stepdown(...)` now returns `simultaneous_ci_small_sample_warning` (additive): `None` when `n_observations >= 504`, else a string warning that the asymptotic max-t simultaneous band may undercover on short samples.
  - Added inline measurement note near construction (asymptotic behavior) and documented the warning in the function docstring/returns.
  - No change to default stepdown/statistics/p-values/ordering/rejections, existing marginal CIs, simultaneous band construction, or any existing returned values except the new additive field.
- `skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py`
  - `test_romano_wolf_simultaneous_ci_contract` now asserts `simultaneous_ci_small_sample_warning is None` at T=504.
  - Added `test_romano_wolf_simultaneous_ci_small_sample_warning` (T=252 emits warning string containing "undercover"/"252"; T=504 returns `None`).
  - Total: 19 tests.
- `skills/quantitative-backtesting/references/validation_methods.md`
  - Replaced short-sample caveat prose with explicit measured coverage table and documented `simultaneous_ci_small_sample_warning`.
  - Recorded that a bootstrap-variance-studentized variant was investigated (Session 93) and did not show consistent improvement, so it is not exposed.

## Why this task
`HANDOFF_NEXT.md` / Session 92 identified max-t simultaneous band small-sample undercoverage as unresolved and requested: reproduce coverage vs T (252,378,504) for K=4/5, determine cause (full-sample Newey-West `omega_k` vs bootstrap max-stat approximation), add bounded opt-in robustness improvement if variance estimate is cause (or warning field), add focused tests, and update docs with measured coverage table.

## What was actually verified (run this session)
- Coverage reproduction (deterministic script, `alpha=0.05`, `n_bootstrap=300`, 60 sims, seed base `2026`, zero-mean Gaussian families):
  - T=252,K=4: 0.925 | T=252,K=5: 0.912
  - T=378,K=4: 0.963 | T=378,K=5: 0.900
  - T=504,K=4: 0.887 | T=504,K=5: 0.950
  (same setup run gave small Monte Carlo variation in-session; all ~0.89–0.96, confirming approximate/asymptotic behavior rather than systematic collapse.)
- Cause probe (bootstrap-variance-studentized max statistic, same resamples, compared to current): T=252,K=4 0.867→0.917, T=252,K=5 0.850→0.883, T=378,K=4 0.900→0.917, T=504,K=4 0.933→0.933, T=504,K=5 0.917→0.900 (60 sims). Improvement was not consistent across T/K, so no opt-in `studentize_method="bootstrap"` was added (would change behavior/complexity without clear evidence). Chosen bounded robustness improvement: additive `simultaneous_ci_small_sample_warning` surfaced when `n_observations < 504`.
- Focused tests:
  - `PYTHONPATH=skills/quantitative-backtesting/scripts python3 -m pytest skills/quantitative-backtesting/tests/test_romano_wolf_stepdown.py -q` -> **19 passed** (16.59s).
  - `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check.py skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q` -> **12 passed** (11.26s).
  - `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -q -k "family or main_registers"` -> **7 passed, 199 deselected** (1.96s).
  - `python3 -m pytest skills/quantitative-backtesting/tests/test_examples_coverage.py -q -k "reality_check"` -> **2 passed, 61 deselected** (2.92s).
- Sanity check (inline): T=252 result carried warning string with "undercover" and "252"; T=504 result carried `simultaneous_ci_small_sample_warning is None`.
- `python3 -m py_compile` on modified .py files -> OK.
- `git diff --check` -> no whitespace errors.

## What remains unresolved
- Full single-invocation quant gate (`python3 -m pytest skills/quantitative-backtesting/tests/ -n 4`) was **not** rerun (timeouts in prior sessions). CI is needed for 100% green confirmation.
- Max-t simultaneous bands remain asymptotic; warning documents approximation but coverage can vary (measured ~0.89–0.96 in this setup). No bootstrap-variance studentization option exposed because evidence was mixed.
- `reality_check_test` still returns no per-strategy CIs; only `romano_wolf_stepdown` has them.
- Simultaneous bands are carried by walk-forward summary automatically (whole stepdown dict stored); no separate CLI flag.

## Approaches already tried / failed (do not repeat unchanged)
- Do not rerun the unchanged full gate in-session (serial or `-n 4` timed out previously).
- Full `test_examples_coverage.py` combined with other files can exceed 120s timeout; run `-k "reality_check"` subset for focused checks.
- Do not regress `test_walk_forward_reports_notional_weighted_capacity_in_book_mode` (Session 85/86).
- Do not use T=252 for committed simultaneous-band coverage assertion expecting >=0.90 in all environments; committed coverage test remains T=504/K=4 as before.
- Bootstrap-variance-studentized max-t statistic (reusing resamples) was measured in-session but showed inconsistent improvement (e.g. T=504,K=5 0.917→0.900 in one run) — do not add as default/opt-in without stronger evidence.

## One precise next task (for the next agent)
Audit and, if needed, improve downstream surfacing of the new `simultaneous_ci_small_sample_warning` in user-facing outputs (walk-forward JSON/CLI summaries and reality-check example text) without changing default statistical behavior:
- Inspect `skills/quantitative-backtesting/scripts/walk_forward.py`, CLI formatting, and `examples/reality_check_family_example.py` for whether `simultaneous_ci_small_sample_warning` is visible when present (family stepdown results are stored/passed through as dicts).
- If absent, add minimal, additive display/persistence (e.g. print warning line in example when not None; ensure walk-forward summary JSON already includes it via stored dict — verify with a small offline run using committed fixtures/synthetic data).
- Add/extend focused tests only if needed (prefer existing walk-forward family and example coverage tests) and keep all changes offline with committed fixtures.
- Constraints: do not change default stepdown outputs/semantics beyond additive surfacing, do not rerun the full gate in-session, do not commit unless explicitly asked; CI is needed for 100% green confirmation.
