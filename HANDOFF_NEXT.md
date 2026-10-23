# Handoff — reproducible backtest example added (2026-10-23)

## What changed
- Added `skills/quantitative-backtesting/examples/reproducible_backtest_example.py` that runs
  `run_backtest.py` on committed fixture `assets/example_data/sample_ohlcv.csv` and writes
  metrics to `examples/example_reproducible_output/`.
- Added `tests/test_reproducible_backtest_example.py` pinning byte-identical metrics across runs.

## What was actually verified
- Example runs successfully; metrics.json SHA stable across two runs.

## One precise next task
Improve the example to also assert point-in-time validation passes and document its usage in examples/README.md.
