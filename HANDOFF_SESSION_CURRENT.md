# Handoff — Session 142 (2026-11-20): Regime-aware variants added to adversarial stress test

## Baseline
- HEAD `314036f` (session 141 adversarial stress test results committed), branch `main`, working tree clean at session start.
- Session 140 completed parallel quant gate execution (1535 passed, EXIT 0 with `-n 4`).

## What this session changed
**Extended `skills/quantitative-backtesting/examples/adversarial_stress_test.py`** with regime-aware variants:
1. `RegimeAwareStrategy(StrategyBase)` wrapper: rescales base strategy signals to a constant per-regime annualized vol target (0.10) via `regime_aware_position_size` (PIT-safe overlay).
2. `run_walk_forward_stress` accepts optional `strategy_factory` override and threads `regime_cost_multipliers` to `walk_forward_analysis`.
3. `main()` variant section on `volatility_clustering` and `regime_shift` vs committed baseline; results saved to `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json`.

### Files changed:
1. `skills/quantitative-backtesting/examples/adversarial_stress_test.py` (+171/-6)
2. `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json` (new, variant results)

## What was actually verified (ground truth)
- Script runs end-to-end: walk_forward 16/16, CPCV 16/16, out_of_sample 16/16 successful; PIT validation passed on all runs.
- Regenerated baseline byte-identical to committed `adversarial_stress_test_results.json` (reproducible; `git status` shows no change to it).
- Regime-aware sizing took effect: regime_shift sma_crossover OOS Sharpe -0.266 → -0.132 (return -0.734 → 0.099); volatility_clustering ema_crossover 0.277 → 0.176 (return 1.836 → 0.495).
- All readings statistically insignificant (Deflated Sharpe p = 1.0) — **no profitability claim supported**.
- Offline tests: `test_regime_aware_position_sizing.py`, `test_regime_cost_multiplier.py`, `test_generate_adversarial_scenarios.py`: **51 passed**.
- Core test `test_falsifiable_hypothesis_example_runs_end_to_end` still passes (example imports cleanly).

## What remains unresolved
- Variant per-regime breakdowns vs baseline not yet compared to confirm lower exposure in `*_high` regimes.
- Full 1535-test gate not re-run (change confined to an example outside gate coverage).
- 363 real-data tests still require live market data (pre-existing bottleneck).
- HANDOFF_NEXT.md participation-rate cap task: stale — already implemented in tree (`walk_forward.py:628`, `run_backtest.py:86`, reporting-only cap); nothing left to do.

## Approaches already tried / failed
- HANDOFF_NEXT.md cap wiring: not applicable, already committed.
- Cost-multiplier label filter matched `"high_vol"` but actual labels are `bull_high`/`bear_high`/`sideways_high` — fixed to `"_high"` match; confirmed working on second run.

## One precise next task
Compare per-regime walk-forward breakdowns between baseline and regime-sized variants using the saved variant json; confirm exposure shrinks in `*_high` regimes. Then decide whether to promote the overlay into a worked example with an explicit falsification criterion (currently falsified: regime-sized Sharpe 0.176 < baseline 0.277 in volatility_clustering — a valid null result). Do not claim profitability.

(End of file)
