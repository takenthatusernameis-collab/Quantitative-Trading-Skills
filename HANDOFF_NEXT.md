# Handoff — dual momentum benchmark baseline captured

## What changed
- Ran dual momentum on the committed AAPL/MSFT/GOOGL triple with `--benchmark sample_benchmark.csv` (no code changes this session).

## Observed metrics (test split, 3 bps round-trip costs)
- strategy total_return: 0.40834454698372635
- strategy sharpe_ratio: 1.1676593094877479
- benchmark_total_return: 0.9015402575236577
- alpha: 0.0739839443419926
- alpha_pvalue: 0.3732887195760113
- correlation_with_benchmark: 0.5381343533335552

## What remains unresolved
- Add `--benchmark` support to `dual_momentum_hypothesis.py` (`_run_backtest_metrics` + a benchmark comparison function) mirroring `falsifiable_hypothesis_example.py`, plus Deflated Sharpe Ratio via `--n-trials` and walk_forward.
- Pin observed strategy + benchmark metrics (net of costs) as regression guards with relative tolerance.
- Do not tune to force SUPPORT. Alpha p-value is 0.37 (>0.05), so benchmark-alpha criterion would FAIL; expected verdict NOT SUPPORTED on benchmark comparison.

## One precise next task
Implement benchmark comparison + DSR in `dual_momentum_hypothesis.py` reusing `falsifiable_hypothesis_example.py` machinery (`--benchmark`, `--n-trials`, walk_forward Deflated Sharpe Ratio), then add a regression test pinning the observed metrics above with relative tolerance 1e-6. Keep falsification criteria honest; do not tune.