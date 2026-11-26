# Handoff — Next: close the pytest-timeout gap for the heaviest test

## What changed (this session)
- Nothing in the repo (no commits). Swept the full skill-level suite
  (`skills/quantitative-backtesting/tests/`, 328 files): **327 PASS / 1 non-test helper**.
  The only non-PASS is `_cli_pit_lookahead.py` (a test-only wrapper imported by a passing
  test; rc=2 on direct call is by design). Installed pytest+matplotlib via pip (no repo
  change); all are declared in requirements.txt. Detail: HANDOFF_SESSION_CURRENT.md.

## What was verified
- 327/328 files green in this env. Heaviest: `test_resolution_vs_sample_size.py` PASS
  79/79 (EXIT=0, ~900s); `test_walk_forward.py` PASS 370s; `test_examples_coverage.py`
  PASS 494s. Working tree clean.

## What remains unresolved / next task (bounded, evidence-based)
- **pytest-timeout gap (real, reproducible):** `skills/quantitative-backtesting/pytest.ini`
  sets `timeout = 600`, but `tests/test_resolution_vs_sample_size.py` is pytest-collectable
  (verified: `pytest --collect-only` → 79 tests) and takes ~900s to run to completion
  (evidence: this session's `resolution.out`, EXIT=0 at ~900s). Under the documented
  parallel gate (`pytest ... -n 4` with pytest-timeout, per requirements.txt pytest-timeout
  pin) this test would be KILLED at 600s and reported as a failure/timeout — a
  reproducibility defect, not a code bug.

## One precise next task
Reconcile the timeout with the measured runtime, smallest reversible change first:
  1. Reproduce: `cd skills/quantitative-backtesting && timeout 1000 python3 -m pytest
     tests/test_resolution_vs_sample_size.py -q` (expect it to pass standalone, ~900s).
  2. Confirm the gate kills it: `python3 -m pytest tests/test_resolution_vs_sample_size.py
     -q --timeout 600` (expect a timeout failure) — this is the defect.
  3. Fix by raising `timeout` in `pytest.ini` to a value above the measured ~900s
     (e.g. 1200) with a comment citing the measurement, OR mark that one test with
     `@pytest.mark.timeout(1200)` / a documented skip-under-parallel marker if the gate
     is meant to stay at 600. Prefer the smallest change that makes the gate green.
  4. Verify: rerun step 2's command (now green) and `test_requirements_declared_dependencies.py`
     still passes. Do NOT commit unless explicitly asked.
- Constraints: do not weaken/skip the test's assertions; do not change the 600s default
  for the whole suite without evidence it is safe; keep the change to pytest.ini (and a
  one-line comment). If the test is intentionally excluded from the gate, document that in
  tests/README.md instead of raising the global timeout.