# Handoff — example coverage for zscore and real_data_pipeline (2026-10-23)

## What changed
- Added `_ZSCORE_MR_PATH` and `_REAL_DATA_PIPELINE_PATH` and executable coverage for `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py` (import + run exit 0 + hypothesis/costs/falsification/OOS + METHODOLOGY CONTROLS with train/val/test and Point-in-time validation).
- Added executable coverage for `skills/quantitative-backtesting/examples/real_data_pipeline_example.py` (import with required callables + end-to-end run asserting PIPELINE COMPLETE - SUMMARY).
- Registered all new tests in `TEST_REGISTRY`.

## What was actually verified
- `cd skills/quantitative-backtesting && python -m pytest tests/test_examples_coverage.py -v` → 32 passed.

## What remains unresolved
- All examples in `skills/quantitative-backtesting/examples/` now have executable coverage in either `tests/test_examples_coverage.py` or `tests/test_walk_forward.py` (real_data_pipeline covered in both). No obvious untested example surfaced.
- If desired, consider tightening assertions for the new zscore/real_data tests to check specific methodology keywords (e.g., "book" pricing) mirroring the existing regression guards.

## Approaches already tried
- Mirrored existing coverage pattern (subprocess runs with timeouts, banner/keyword assertions) — consistent and passing.

## One precise next task
Review and potentially strengthen regression guards in the quant skill: e.g. add a test ensuring `zscore_mean_reversion_hypothesis` surfaces "book" panel pricing when using pairs fixtures (as documented), or add coverage for `real_data_pipeline_example`'s deflated alpha/MCC outputs. Relevant files: `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py`, `skills/quantitative-backtesting/tests/test_examples_coverage.py`.
