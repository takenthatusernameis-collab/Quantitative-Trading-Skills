# Handoff — dual momentum SUPPORTED on triple (AAPL/MSFT/GOOGL), robust to elevated costs and parameter perturbation

## What changed
- Added three new regression tests exercising the previously untested dual momentum family on the committed three-asset panel (AAPL / MSFT / GOOGL):
  - `skills/quantitative-backtesting/tests/test_dual_momentum_hypothesis_real_triple_aapl_msft_googl.py` — hypothesis test, chronological 0.6/0.2/0.2 split, PIT true, panel book pricing, net of costs.
  - `skills/quantitative-backtesting/tests/test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py` — elevated-cost sweep with pinned metrics per cost level.
  - `skills/quantitative-backtesting/tests/test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py` — pre-registered parameter-sensitivity sweep with pinned metrics per setting.
- Added `run_param_sensitivity_sweep` and `PARAM_SENSITIVITY_GRID` to `skills/quantitative-backtesting/examples/dual_momentum_hypothesis.py`, mirroring the existing `cross_sectional_momentum_hypothesis.py` convention. No framework source changes.

## What was actually verified
- New tests: 3 passed in 23.31s.
- Prior regression guards still green: z-score elevated cost triple, cross-sectional momentum elevated cost triple, cross-sectional momentum param sensitivity triple — 3 passed in 26.69s.
- Offline, committed fixtures only; no live network.

Dual momentum on the triple (committed fixtures, chronological disjoint split, PIT true, panel book pricing, net of costs):

Elevated-cost sweep:
| Cost level | Sharpe | Return | Verdict |
|---|---|---|---|
| 2bp comm + 1.00bp slip | 1.1677 | 40.83% | SUPPORTED |
| 5bp comm + 2.50bp slip | 1.1033 | 38.38% | SUPPORTED |
| 10bp comm + 5.00bp slip | 0.9958 | 34.39% | SUPPORTED |
| 20bp comm + 10.00bp slip | 0.7804 | 26.73% | SUPPORTED |

Parameter sensitivity grid (fixed costs 2bp+1bp), all six pre-registered settings SUPPORTED:
| lookback | top_q | rf | Sharpe | Return | Verdict |
|---|---|---|---|---|---|
| 252 | 0.5 | 0.00 | 1.1677 | 40.83% | SUPPORTED |
| 189 | 0.5 | 0.00 | 0.9194 | 42.99% | SUPPORTED |
| 315 | 0.5 | 0.00 | 1.2420 | 38.32% | SUPPORTED |
| 252 | 0.4 | 0.00 | 1.1677 | 40.83% | SUPPORTED |
| 252 | 0.6 | 0.00 | 1.2250 | 43.51% | SUPPORTED |
| 252 | 0.5 | 0.02 | 1.3044 | 46.06% | SUPPORTED |

(top_quantile 0.4 and 0.5 give identical metrics on a 3-asset panel because ceil(3*0.4) == ceil(3*0.5) == 2 assets in the long book; structural, not a regression.)

This is the first family on the triple to pass pre-registered falsification criteria net of costs, survive the full elevated-cost sweep, AND remain SUPPORTED across a pre-registered parameter perturbation grid. Contrast: cross-sectional momentum NOT SUPPORTED at all levels; multi-pair z-score flips SUPPORTED→NOT SUPPORTED between 5bp+2.5bp and 10bp+5bp.

## What remains unresolved
- This is a single-panel, single-hypothesis positive result on committed fixtures. It is NOT evidence about any market and has NOT been tested for: multiple-testing/deflated-sharpe correction, benchmark (buy-and-hold) alpha comparison, walk-forward re-optimization, or alternative universes/lookback ranges. Per the repo's evidence standards, a robust claim requires independent/out-of-sample evidence net of plausible costs plus multiple-testing controls.
- Full real-market suite (`test_falsifiable_hypothesis_example.py`) remains slow (minutes per test); not re-run in full this session.

## Approaches already tried / failed
- Cross-sectional momentum on triple: NOT SUPPORTED at all cost levels (monotonic degradation).
- Multi-pair z-score on triple: SUPPORTED at advertised/5bp+2.5bp, NOT SUPPORTED at 10bp+5bp and above (verdict flips — not robust).
- Batch runs of large test groups time out/hang; per-file focused gates are the reliable verification mode.

## One precise next task
Strengthen the dual momentum evidence with the methodology controls the repo already applies to the SMA-crossover example in `falsifiable_hypothesis_example.py`, on the same triple (AAPL/MSFT/GOOGL) using committed fixtures only:
1. Add a benchmark (buy-and-hold) comparison for dual momentum — reuse the existing `--benchmark` / Deflated Alpha Ratio machinery where applicable, or report benchmark alpha/total-return alongside the strategy on the held-out test split.
2. If multiple parameter settings are compared, apply the Deflated Sharpe Ratio multiple-testing correction (the framework already exposes it via `--n-trials` / `walk_forward`); report the corrected p-value as an additional pre-registered criterion rather than tuning to force SUPPORT.
3. Pin the observed metrics (strategy + benchmark, net of costs) as regression guards with relative tolerance, mirroring the pinned-metrics pattern already used in the three new dual momentum tests.
Keep changes small and reversible; do not expand to live data or infrastructure changes.

Evidence/constraints:
- Committed fixtures: `assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv` only; no live network.
- Python env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 at `/home/runner/work/_temp/kilo-home/.local/` (`export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`).
- Reuse `dual_momentum_hypothesis.py` and the pinned-metrics pattern.

(End of file)