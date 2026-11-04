# Handoff — next task

## What changed (this session)
Executed the assigned bounded real-market falsification experiment for RSI mean reversion on the committed AAPL/MSFT/GOOGL triple panel using the existing benchmark-aware machinery (`examples/rsi_mean_reversion_hypothesis.py::run_benchmark_aware_hypothesis_test`, test `tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py`).
- Test result: 2 passed (1.71s).
- No source/test files modified; working tree clean except pre-existing untracked.

## What was actually verified
- Net-of-costs metrics on held-out test window (3bp round-trip): Sharpe -0.298, total return -31.8%, benchmark (MSFT) +90.2%, alpha -22.8%, alpha p=0.437, deflated Sharpe p=0.986 (5 trials).
- All four BENCHMARK_CRITERIA failed -> verdict NOT SUPPORTED (stable; not tuned to force SUPPORT).
- Methodology controls: chronological split 0.6/0.2/0.2 disjoint=True, PIT validation=True, panel pricing=book.

## What remains unresolved
- Other multi-asset hypothesis families (zscore_mean_reversion, cross-sectional momentum, dual momentum) may lack benchmark-aware guards; coverage not yet audited.

## One precise next task
Audit `examples/` and `tests/` for benchmark-aware guard coverage across hypothesis families; add a benchmark-aware guard only where a demonstrated methodological gap exists (mirror the RSI triple-panel pattern), pinned metrics + NOT SUPPORTED verdict, offline committed fixtures only.

Constraints: offline, committed fixtures only, no tuning to force SUPPORT, smallest reversible change.