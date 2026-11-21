# Handoff — Session 146: Per-regime attribution computed

## What changed
- Added `skills/quantitative-backtesting/examples/regime_attribution_analysis.py` which loads `adversarial_stress_test_regime_aware_extended.json` and prints per-regime Sharpe deltas (baseline vs regime-sized overlay) across all 12 variants.

## What was verified
- Script runs successfully and produces attribution table. Key patterns:
  - Improving scenarios (regime_shift, trend_persistence-ish, liquidity_crisis, structural_break) show large per-regime Sharpe gains in high-vol/sideways regimes where sizing down reduces exposure.
  - Degrading scenarios (volatility_clustering, fat_tail_crash) show overlay trims exposure in bull_high regimes where baseline captures trend, explaining Sharpe loss.

## What remains unresolved
- Regime detection lag vs true transitions not yet measured.
- Target_vol sweep, regime config sweep, additional strategies not done.

## Next precise task
Measure regime detection lag: for each scenario, compute bars between true regime transition (from scenario generator metadata if available, else vol-spike thresholds) and detected combined regime change. Compare lag profiles across improving vs degrading scenarios. Use `detect_combined_regime` in `skills/quantitative-backtesting/`. Output a table + handoff.
