# Handoff — Session 142 (2026-11-20): Regime-aware variants added to adversarial stress test

## Baseline
- HEAD `314036f` (session 141 adversarial stress test results committed), branch `main`, working tree clean at session start.
- Previous full quant gate: 1535 passed, EXIT 0 with `-n 4`.

## What this session changed
**Extended `skills/quantitative-backtesting/examples/adversarial_stress_test.py`** (+171/-6 lines):
- `RegimeAwareStrategy(StrategyBase)` wrapper: rescales base strategy signals to a constant per-regime annualized vol target (0.10) via `regime_aware_position_size` (PIT-safe sizing overlay; direction preserved, size shrinks in high-vol regimes).
- `run_walk_forward_stress` now accepts an optional `strategy_factory` override and threads `regime_cost_multipliers` through to `walk_forward_analysis`.
- `main()` runs a variant section on `volatility_clustering` and `regime_shift` vs the committed baseline: (a) regime-sized variant, (b) `regime_cost_multipliers` x1.5 on `bull_high`/`bear_high`/`sideways_high` regimes. Variant results written to `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json`.

## What was actually verified (ground truth)
- Script runs end-to-end: walk_forward 16/16, CPCV 16/16, out_of_sample 16/16 successful; point-in-time validation passed on every run.
- Regenerated baseline is byte-identical to committed `adversarial_stress_test_results.json` (`git status` shows no change to it) — baseline reproducible.
- Regime-aware sizing took effect, e.g. regime_shift sma_crossover: OOS Sharpe -0.266 → -0.132 (return -0.734 → 0.099), periods 75→74; volatility_clustering ema_crossover: 0.277 → 0.176 (return 1.836 → 0.495).
- Cost-multiplier variant applied (1.5x on high-vol regimes) with small metric shifts; no crashes.
- Every reading statistically insignificant: Deflated Sharpe p = 1.0 across all variants — **no profitability or robustness claim is supported**.
- Offline tests: `test_regime_aware_position_sizing.py` + `test_regime_cost_multiplier.py` + `test_generate_adversarial_scenarios.py`: **51 passed** in ~1s.

## What remains unresolved
- Whether regime-aware sizing improves risk-adjusted OOS performance cannot be claimed (DSR p=1.0, small sample). The null result (regime-sized Sharpe below baseline in volatility_clustering: 0.176 < 0.277) is a valid, honest finding.
- Variant per-regime breakdowns (`regime_analysis` in variant summaries) not yet compared to baseline to confirm lower exposure in `*_high` regimes.
- Full 1535-test gate not re-run: change is confined to an example script outside gate coverage (`test_examples_coverage.py` does not cover `adversarial_stress_test.py`).
- HANDOFF_NEXT.md participation-rate cap task: stale — cap already implemented in tree (`walk_forward.py:628`, `run_backtest.py:86`, reporting-only); working tree was clean, nothing left to do.

## Approaches already tried / failed
- "Wire max-participation-rate through walk_forward.py CLI" (HANDOFF_NEXT.md): not applicable — already present and committed.
- Cost-multiplier label filter initially matched `"high_vol"`; actual `detect_combined_regime` labels are `bull_high`/`bear_high`/`sideways_high` — fixed to `"_high"` match; second run confirmed variant applies.

## One precise next task
Compare per-regime walk-forward performance breakdowns between baseline and regime-sized variants using `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json`, to confirm the overlay reduces exposure in `*_high` regimes. Then decide whether to promote the overlay into a worked example with an explicit falsification criterion (e.g., "regime-sized OOS Sharpe >= baseline in volatility_clustering" — currently falsified at 0.176 vs 0.277, which is a valid null result). Do not claim profitability anywhere. Re-running the full gate is optional (change outside gate coverage).

## Evidence
- Modified script: `skills/quantitative-backtesting/examples/adversarial_stress_test.py`
- Variant results: `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json`
- Baseline (unchanged, reproducible): `adversarial_stress_test_results.json`

(End of file)
