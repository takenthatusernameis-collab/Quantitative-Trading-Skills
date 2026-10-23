# Handoff — mean_reversion_hypothesis example coverage (2026-10-23)

## What changed
- Added executable coverage for `skills/quantitative-backtesting/examples/mean_reversion_hypothesis.py` in `skills/quantitative-backtesting/tests/test_examples_coverage.py` (import smoke, run exit 0, hypothesis/costs/falsification/OOS assertions, point-in-time split validation). Added `_MEAN_REVERSION_PATH` and registered 4 new tests.

## What was actually verified
- `cd skills/quantitative-backtesting && python -m pytest tests/test_examples_coverage.py -v` → 22 passed.

## What remains unresolved
- Remaining examples without dedicated coverage: `rsi_mean_reversion_hypothesis.py`, `zscore_mean_reversion_hypothesis.py` (hypothesis examples), and `real_data_pipeline_example.py`.
- `real_data_pipeline_example.py` exercises real data path/persistence; `rsi_*` and `zscore_*` follow the same falsifiable hypothesis pattern as the others.

## Approaches already tried
- Followed existing coverage pattern for `simple_momentum_hypothesis.py` (subprocess run with timeouts, asserts on banners/keywords and methodology controls). Worked.

## One precise next task
Add executable coverage for `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py` in `tests/test_examples_coverage.py`: mirror the mean_reversion/simple_momentum coverage (import + run exit 0 + assert hypothesis/RSI/bps/falsification/OOS/Sharpe + METHODOLOGY CONTROLS with train/val/test and Point-in-time validation). Relevant files: `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py`, `skills/quantitative-backtesting/tests/test_examples_coverage.py`.
