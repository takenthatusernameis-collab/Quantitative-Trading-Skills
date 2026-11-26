# Task for Next Agent

## What changed (this session)
- Executed the prior handoff (`HANDOFF_NEXT_SESSION.md`): add pytest config for
  long-running integration tests + document them.
- `pytest-timeout` is **NOT installed** (`ModuleNotFoundError: No module named
  'pytest_timeout'`; pytest 9.2.0). Per the handoff's fallback (step 3), did NOT
  add an inert `pytest.ini`/`pyproject.toml` `timeout` (it would do nothing
  without the plugin).
- Created `skills/quantitative-backtesting/tests/README.md` documenting:
  - how to run tests (`python3 <file>`, portable; `pytest` not always on PATH),
  - the two long-running suites and their runtimes
    (`test_walk_forward.py` ~8 min/468 s; `..._protocol_sensitivity_real_triple.py`
    ~6 min/360 s),
  - `timeout 900 python3 -m pytest ...` wrapper guidance,
  - explicit note that `pytest-timeout` is absent so a `timeout=` ini setting is inert.

## What was verified (evidence)
- `python3 -m pytest ".../test_walk_forward.py::test_out_of_sample_validation_benchmark_cost_is_periodic" -v`
  → **1 passed in 1.35s** (handoff step 4 check).
- `git status --short` → only `?? skills/quantitative-backtesting/tests/README.md`.
  No test files, engine, fixtures, or default JSON modified.
- Did NOT re-run the two ~6–8 min suites (already proven all-pass in prior session:
  235 passed/468 s and 5/5 passed/360 s).

## What remains unresolved
- The two integration suites still take ~6–8 min; no methodology-weakening speedup
  attempted (would risk changing results). Runtime is inherent.
- `pytest` not on PATH in this env; `python3 <file>` convention still required.
- Not committed (no explicit request).

## Approaches already tried / failed
- None this session. (Prior sessions proved the "hang" was expected runtime, not a defect.)

## One precise next task (bounded, evidence-based)
Run regression coverage of remaining single-asset walk-forward family test files
directly with `python3`, confirming no regressions from accumulated additive tests.
Targets in `skills/quantitative-backtesting/tests/` (run each, expect exit 0 / OK):
- `test_walk_forward_sma_crossover_real_aapl.py`
- `test_walk_forward_time_series_momentum_real_aapl.py`
- `test_walk_forward_zscore_real_aapl_msft.py`
- any other walk-forward single-asset files not yet covered this cycle.
Constraints: committed fixtures only (offline); verdicts must remain NOT SUPPORTED
where applicable (`assert all(passes.values()) is False` holds); working tree stays
clean; do not commit unless explicitly asked.