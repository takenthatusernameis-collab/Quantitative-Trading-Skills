# Handoff — next task

## What changed
- Benchmark comparison + Deflated Sharpe Ratio multiple-testing correction added to dual momentum on the committed AAPL/MSFT/GOOGL panel (benchmark=MSFT.csv, N_TRIALS=6). `tests/test_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py` passes (2/2, 4.34s).

## What was actually verified
- Benchmark-aware test green; offline committed fixtures only.

## What remains unresolved
- Elevated-cost sweep and parameter-sensitivity grid for dual momentum have not yet been evaluated with benchmark comparison + DSR; only the baseline 3bps cost setting has benchmark/DSR coverage.

## One precise next task
Extend `test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py` and `test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py` to pass `benchmark_path="MSFT.csv"` and `n_trials=6`, pin strategy + benchmark metrics (net of costs) with relative tolerance, and assert the four BENCHMARK_CRITERIA. Do not tune to force SUPPORT.
