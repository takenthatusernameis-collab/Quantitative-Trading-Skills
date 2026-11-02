# Handoff — pinned real-market falsification evidence as regression guards

## What changed (this session)
- Added regression guards to `skills/quantitative-backtesting/tests/test_zscore_elevated_cost_sensitivity_real_triple_aapl_msft_googl.py` pinning the observed out-of-sample metrics per cost level for multi-pair z-score mean reversion on the committed AAPL/MSFT/GOOGL triple:
  - 2bp+1bp: Sharpe 0.2293, Return +8.89% -> SUPPORTED
  - 5bp+2.5bp: Sharpe 0.0365, Return +3.02% -> SUPPORTED
  - 10bp+5bp: Sharpe -0.2835, Return -6.08% -> NOT SUPPORTED
  - 20bp+10bp: Sharpe -0.9119, Return -21.95% -> NOT SUPPORTED
- Compared with a relative tolerance (1e-3), never exact equality (last decimals depend on the numpy/pandas build), matching the repo's existing pinning convention.
- Reverted test-regenerated `examples/example_output/*` timestamp/float churn so the working tree contains only the intended test change.

## What was actually verified
- `test_zscore_elevated_cost_sensitivity_real_triple_aapl_msft_googl.py`: 1 passed in 5.48s, with the pinned metrics reproducing exactly (gate: `cd skills/quantitative-backtesting && python3 -m pytest tests/test_zscore_elevated_cost_sensitivity_real_triple_aapl_msft_googl.py -p no:cacheprovider -q`).
- Stale items from prior handoffs now green:
  - `tests/test_reporting.py`: 64 passed (TestParameterHeatmap no longer fails headless).
  - `tests/test_run_backtest.py`: 108 passed (trade-ledger/audit-params reconciled).
  - `tests/test_cpcv.py`, `test_data_loader.py`, `test_monte_carlo.py`, `test_performance.py`: 122 passed.
- Offline, committed fixtures only; no live network.

## What remains unresolved
- No pair/triple tested shows positive out-of-sample behavior net of costs that is robust to parameter or cost perturbation (momentum falsified at all cost levels; z-score flips SUPPORTED->NOT SUPPORTED between 5bp+2.5bp and 10bp+5bp round-trip).
- `tests/test_walk_forward.py` hangs on its compute-heavy CLI sweep tests in batch runs (does not block the run_backtest-based hypothesis tests). Not pursued as infra work; focused verification is more reliable here.

## Approaches already tried / failed
- Full `tests/` regression pass: ~48 min, 10 pre-existing failures only, zero regressions from prior z-score change.
- Batch runs of large test groups time out/hang; per-file focused gates are the reliable verification mode in this environment.

## One precise next task
Propose and test the smallest falsifiable alternative on the same triple (AAPL/MSFT/GOOGL) using committed fixtures only (per HANDOFF_SESSION38):
1. Define a specific hypothesis (explicit signal, universe, holding/exit, rank/threshold) with pre-registered falsification criteria (OOS Sharpe>0 and OOS total return>0) and explicit rejection if either fails. Do NOT tune parameters to force SUPPORT.
2. Enforce chronological disjoint train/validation/test splits (no lookahead), PIT correctness, and survivorship/lookahead controls.
3. Run elevated-cost sweep (2bp+1bp, 5bp+2.5bp, 10bp+5bp, 20bp+10bp) and report SUPPORTED/NOT SUPPORTED per level with evidence.
4. If it also fails, record exact limitations and the smallest reproducible next step without expanding to live data or infrastructure changes.
Reuse the existing `zscore_mean_reversion_hypothesis.py` (`run_elevated_cost_sweep`) convention and pinned-metrics pattern just added above.

Evidence/constraints:
- Committed fixtures: `assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv` only; no live network.
- Python env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 at `/home/runner/work/_temp/kilo-home/.local/` (`export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`).
- Do not modify framework source beyond the minimal new hypothesis test/example; keep changes small and reversible.

(End of file)
