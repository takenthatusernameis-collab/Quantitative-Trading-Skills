# Handoff — added falsifiable momentum hypothesis using run_backtest (2026-10-23)

## What changed
- Added `skills/quantitative-backtesting/examples/simple_momentum_hypothesis.py`: a bounded, pre-registered falsifiable hypothesis test using `scripts/run_backtest.py` with explicit chronological train/val/test splits (0.6/0.2/0.2), test-split only evaluation, commission/slippage cost model, benchmark comparison, point-in-time validation, and written falsification criteria (Sharpe>0, total return>0). Verdict reported as SUPPORTED/NOT SUPPORTED without claiming profitability.
- Added `skills/quantitative-backtesting/tests/test_simple_momentum_hypothesis.py`: verifies the example exists with required methodology elements and runs end-to-end successfully.

## What was actually verified
- Ran the new hypothesis example successfully against shipped sample data; verdict was NOT SUPPORTED on this sample (criteria failed), which is a valid scientific outcome.
- Ran the new tests (`test_simple_momentum_hypothesis.py`) — all passed.
- Confirmed no generated results were committed (cleaned `results/` artifacts from test runs).

## What remains unresolved
- The tested SMA crossover on the shipped sample data does not pass the pre-registered criteria (small test window / weak signal on this synthetic sample). A more promising bounded hypothesis (different strategy/params/universe) could be tested.
- No real market/out-of-sample evidence exists in repo; all results remain synthetic or retired per prior audit.

## Approaches already tried
- Tried to call `run_backtest()` as a library function directly; its API expects `(data, strategy, args, ...)` from CLI parsing. Switched to calling the CLI via subprocess (consistent with how the framework is used) which matches the existing patterns.

## One precise next task
Test an alternative bounded hypothesis on the same reproducible sample data (e.g., a mean-reversion rule like Bollinger Bands with different parameters, or optimize/select on train only and evaluate strictly on test) using the same pattern as `skills/quantitative-backtesting/examples/simple_momentum_hypothesis.py` and `skills/quantitative-backtesting/scripts/run_backtest.py` with costs/benchmark/splits/PIT validation; add a falsification criterion set in advance, report resolution if possible, and commit only code/scripts with a test verifying reproducibility.
