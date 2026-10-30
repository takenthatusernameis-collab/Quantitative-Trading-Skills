# Handoff — next task (real-market falsification: cross-sectional momentum added)

## What changed
Assigned real-market falsification task verified COMPLETE:
- The AAPL-pair zscore mean-reversion real-market experiment (and MSFT/GOOGL, AAPL/MSFT, MSFT/AAPL variants) is implemented and green: all 8 `test_zscore_*_real_*.py` tests pass. AAPL/GOOGL → genuine NOT SUPPORTED verdict (OOS Sharpe −0.4256, total return −3.10%, net of 3bps), with chronological/disjoint split, point-in-time validation = True, and book panel pricing. Falsification outcome, not a profitability claim.

Added a DIFFERENT STRATEGY FAMILY real-market falsification experiment (cross-sectional momentum vs z-score mean-reversion pairs) on committed MSFT/GOOGL fixtures, per the handoff's "different strategy family" option:
- New `skills/quantitative-backtesting/examples/cross_sectional_momentum_hypothesis.py` — run_backtest.py CLI test, `--strategy cross_sectional_momentum --multi-symbol --panel-pricing book --validate-point-in-time`, train/val/test 0.6/0.2/0.2, criteria `oos_sharpe_gt_zero` + `oos_total_return_positive` (net of 3bps), plus a 5-level ascending cost-sweep asserting the directional claim that higher costs never improve net performance. Offline, committed fixtures only; no profitability claim.
- New `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_hypothesis_real_msft_googl.py` — mirrors `test_zscore_hypothesis_real_msft_googl.py` (verdict/all_pass/criteria structure, chronological+disjoint+PIT controls, no profitability claim).

## What was actually verified
- `python3 examples/cross_sectional_momentum_hypothesis.py` → exit 0; verdict NOT SUPPORTED (Sharpe −0.5447, total return −6.28%); cost sweep Sharpe −0.3774→−1.2032, return −3.46%→−16.79% as costs 0→10bp (monotonic degradation, verdict stable NOT SUPPORTED); methodology controls green.
- `pytest tests/test_cross_sectional_momentum_hypothesis_real_msft_googl.py` → 1 passed (7.78s), re-run 1 passed (7.85s) → deterministic.
- `py_compile` on both new files → OK.
- No repo fixtures or tracked source modified; both new files write only to temp dirs (no repo writes).

## What remains unresolved
- None for this experiment. The slow framework regression gate was previously recorded green (303 passed, HANDOFF_NEXT_SESSION baseline) and is not affected by these additive new files.

## Approaches already tried / failed
- Simple momentum (`sma_crossover`) on multi-symbol real data: NOT a panel strategy (`--multi-symbol` help states it requires cross_sectional_momentum/dual_momentum); running it with `--multi-symbol` raises InvalidIndexError in `strategy_builder.py:89`. Rejected by design — sma_crossover is single-symbol only; switching to the panel strategy cross_sectional_momentum is the supported route (used here).
- Writing the combined panel CSV into `assets/example_data/` (repo write): rejected — reverted; the panel is now built in a temp dir so nothing tracked is mutated.

## One precise next task
Add an elevated-cost confirmation sweep to the cross-sectional momentum experiment, mirroring `test_zscore_elevated_cost_sensitivity_real_msft_googl.py` (ELEVATED_COST_SWEEP_LEVELS: advertised 3bps → 20bp+10bp), reporting per-criterion pass/fail and verdict flip at each level on committed MSFT/GOOGL, with no profitability claim. Then re-run the new momentum test + the full real-market zscore gate to confirm no regression. Files: extend `examples/cross_sectional_momentum_hypothesis.py` (add `run_elevated_cost_sweep`) + new `tests/test_cross_sectional_momentum_elevated_cost_real_msft_googl.py`.

## Constraints / evidence
- Offline, committed fixtures only (`assets/example_data/real_market_data/{MSFT,GOOGL,AAPL}.csv`); Yahoo fetch is HTTP 429 rate-limited — no live network.
- Verdicts are falsification outcomes, never profitability claims.
- Regression baseline: 303 passed in 787.44s (slow framework gate, prior session).
