# Handoff — benchmark-aware falsification complete for dual momentum AND cross-sectional momentum on the triple (AAPL/MSFT/GOOGL)

## What changed
- Dual momentum family fully wired for benchmark-aware falsification (already committed): `skills/quantitative-backtesting/examples/dual_momentum_hypothesis.py` exposes `--benchmark` / `--n-trials`, `BENCHMARK_CRITERIA` (OOS Sharpe > 0, OOS total return > benchmark, Deflated Sharpe p-value < 0.10 across N=6 pre-registered parameter grid, raw benchmark alpha p-value < 0.05) and `run_benchmark_aware_hypothesis_test`. Benchmark test `tests/test_dual_momentum_benchmark_real_triple_aapl_msft_googl.py` pins strategy + benchmark metrics (rel tol 1e-6).
- THIS SESSION: extended the same benchmark-aware machinery to cross-sectional momentum in `skills/quantitative-backtesting/examples/cross_sectional_momentum_hypothesis.py`:
  - Added `BENCHMARK_FILE = "MSFT.csv"`, `N_TRIALS = len(PARAM_SENSITIVITY_GRID) == 6`, `BENCHMARK_CRITERIA` (4 criteria), `_resolve_benchmark`, `--benchmark`/`--n-trials`/`--no-benchmark`/`--output-json` CLI args, and `run_benchmark_aware_hypothesis_test`.
  - `run_hypothesis_test` now accepts optional `benchmark_path`/`n_trials` (backward compatible; baseline 2-criterion path unchanged).
  - Added regression test `tests/test_cross_sectional_momentum_benchmark_real_triple_aapl_msft_googl.py` (run + pinned metrics, rel tol 1e-6).
- No framework source changes; offline, committed fixtures only; no live network.

## What was actually verified
- Dual momentum (8 tests): all pass in 86.29s. Benchmark-aware verdict honestly NOT SUPPORTED: Sharpe 1.1677, return 40.83% vs benchmark MSFT 90.15%; alpha p=0.3733 (>0.05), DSR p=0.5954 (>0.10).
- Cross-sectional momentum (5 tests incl. new benchmark test): all pass in 60.16s. Benchmark-aware verdict honestly NOT SUPPORTED: Sharpe -0.3896, return -2.06% vs benchmark +90.15%; alpha p=0.9366, DSR p=0.9924. All four benchmark-aware criteria fail.
- Existing cross-sectional momentum guards (baseline hypothesis, elevated cost, param sensitivity) still pass — backward compatible.
- Prior regression guards (dual momentum baseline/elevated cost/param sensitivity, z-score/mean_reversion fast groups) remain green per earlier sessions.

Key honest comparative result (same triple, same costs, chronological 0.6/0.2/0.2 split, PIT true, panel book pricing, net of costs):
| Family | OOS Sharpe | OOS Return | Benchmark (MSFT) Return | Alpha p-value | DSR p-value | Benchmark-aware verdict |
|---|---|---|---|---|---|---|
| Dual momentum | 1.1677 | +40.83% | +90.15% | 0.3733 | 0.5954 | NOT SUPPORTED |
| Cross-sectional momentum | -0.3896 | -2.06% | +90.15% | 0.9366 | 0.9924 | NOT SUPPORTED |

Neither momentum family beats buy-and-hold MSFT on the held-out test split net of costs.

## What remains unresolved
- All results are single-panel, single-window, committed fixtures only; NOT evidence about any market. No multiple-testing/deflated-Sharpe beyond the pre-registered N=6 grid, no walk-forward re-optimization, no alternative universes.
- z-score mean reversion family still lacks benchmark-aware treatment (has baseline + walk_forward tests only), so it is not yet comparable on the same honest criteria.
- Full slow framework suites (`test_falsifiable_hypothesis_example.py`, `test_walk_forward.py`, `test_cpcv.py`, `test_resolution_vs_sample_size.py`) not re-run in full this session; per-file focused gates are the reliable verification mode.

## Approaches already tried / failed
- Cross-sectional momentum baseline: NOT SUPPORTED at all cost levels (monotonic degradation).
- Multi-pair z-score: cost-fragile (verdict flips between cost levels).
- Dual momentum baseline: SUPPORTED, but does NOT survive benchmark comparison (honest NOT SUPPORTED).
- Batch runs of large test groups time out/hang; per-file focused gates are the reliable verification mode.

## One precise next task
Extend benchmark-aware falsification to the z-score mean reversion family on the committed triple (AAPL/MSFT/GOOGL), mirroring the `cross_sectional_momentum_hypothesis.py` / `dual_momentum_hypothesis.py` template:
1. Add `BENCHMARK_FILE`, `N_TRIALS`, `BENCHMARK_CRITERIA`, `_resolve_benchmark`, `--benchmark`/`--n-trials`/`--no-benchmark`/`--output-json` CLI, and `run_benchmark_aware_hypothesis_test` to `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py` (keep its baseline 2-criterion path backward compatible).
2. Add `tests/test_zscore_mean_reversion_benchmark_real_triple_aapl_msft_googl.py` with a run test + pinned regression test (rel tol 1e-6) using OBSERVED metrics only — run it first to capture real numbers, do not fabricate or tune to force SUPPORT.
3. Verify the new test passes and that existing z-score tests (`test_zscore_mean_reversion_hypothesis.py`, `test_walk_forward_zscore_*`) still pass.
Keep changes small and reversible; committed fixtures only; no live network.

Evidence/constraints:
- Committed fixtures: `skills/quantitative-backtesting/assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv` only; benchmark MSFT.csv.
- Python env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 at `/home/runner/work/_temp/kilo-home/.local/bin` (`export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`).

(End of file)
