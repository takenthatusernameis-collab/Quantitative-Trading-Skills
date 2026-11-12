# Handoff — next session

## Current state
- Session 94 added regression tests for the max-t small-sample warning surfacing
  committed in `fad88c6`. No production/statistical behavior changed.
- `simultaneous_ci_small_sample_warning` is now enforced to appear in:
  - walk-forward CLI stdout when `--family-stepdown` is used with a short OOS
    sample (189 bars), alongside the persisted summary field;
  - the reality-check family example's printed output (502 obs);
  - and the formatter is a no-op on `None`/non-dict input.
- Working tree has the two modified test files plus this handoff; no commit.
- Full details/evidence are in `HANDOFF_SESSION94.md`.

## What was actually verified
- `PYTHONPATH=scripts python3 -m pytest tests/test_walk_forward.py -q -k "family or main_registers"` -> 8 passed.
- `python3 -m pytest tests/test_reality_check_family_example.py -q` -> 6 passed (~8 s).
- `PYTHONPATH=scripts python3 -m pytest tests/test_romano_wolf_stepdown.py -q` -> 19 passed.
- Combined `-k "family or reality_check or romano_wolf or main_registers"` -> 33 passed (~22 s).
- `py_compile` and `git diff --check` -> OK.

## What remains unresolved
- Full single-invocation quant gate was not rerun; no CI workflow runs the quant
  pytest suite at all.
- Max-t bands remain asymptotic/approximate on short samples (warning only).
- `reality_check_test` still returns no per-strategy CIs.
- Changes are uncommitted.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: times out; do not rerun unchanged in-session.
- Full `test_examples_coverage.py` combined with other files can exceed 120 s.
- New module-level tests in `test_walk_forward.py` must be added to
  `TEST_REGISTRY` or `test_main_registers_every_module_level_test` fails.
- Bootstrap-variance studentization: inconsistent improvement; do not add.
- Do not assert `>=0.90` simultaneous coverage at T=252; committed test stays T=504.

## One precise next task
Add a bounded, fast quant regression gate to CI:
- Extend `.github/workflows/validate-skills.yml` with a step that installs
  `skills/quantitative-backtesting/requirements.txt` and runs only the fast,
  deterministic subset: `tests/test_romano_wolf_stepdown.py`,
  `tests/test_reality_check.py`, `tests/test_reality_check_family_example.py`,
  and `tests/test_walk_forward.py -k "family or main_registers"`.
- Evidence: 33 passed in ~22 s locally. Do NOT add the full `tests/` directory
  (it times out).
- Constraints: additive/reversible; verify the exact commands locally first; do
  not commit unless explicitly asked.