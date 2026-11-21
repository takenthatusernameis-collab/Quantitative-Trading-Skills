# Handoff — Session 146 (2026-11-21): Regime-aware overlay mechanism diagnosed

## Baseline
- HEAD `cc17836c` (session 145 regime-aware sweep committed), branch `main`, working tree clean except new untracked diagnostic script below.
- Session 145 result: regime-aware vol targeting (target_vol=10%) improved OOS Sharpe on 8/12 scenario-strategy combinations; NOT FALSIFIED. Conditional value confirmed but all DSR p-values ≈ 1.0 (test resolution ≈ 2.0 Sharpe) — point estimates only, no statistical or profitability claims.

## What changed
- **New file:** `skills/quantitative-backtesting/scripts/diagnose_regime_overlay.py`
  - Part A: per-regime attribution from `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json` (baseline vs regime-sized Sharpe per combined regime, all 12 variants) — no recomputation.
  - Part B: regime detection lag — regenerated all 6 scenarios (seed=42, periods=5000), ran `detect_combined_regime` with shipped `RegimeConfig`, compared detected changes to known truth transitions.

## What was actually verified

### Part A — where the overlay wins/loses (mean per-regime Sharpe delta, improving vs degrading scenarios)

| regime | improving (n=8) | degrading (n=4) |
|--------|-----------------|-----------------|
| sideways_high | +2.8290 | -0.6253 |
| sideways_low | +0.8931 | +0.9899 |
| bear_high | +0.2601 | +0.0393 |
| bear_low | -0.0188 | +0.1226 |
| bull_high | -0.0824 | -0.0908 |
| bull_low | -0.5391 | +0.0867 |

**Improving scenarios (trend_persistence, structural_break, liquidity_crisis, regime_shift):** gains concentrate in sideways regimes (+0.89/+2.83 — baseline over-trades chop, sizing down cuts losses) and bear_high (+0.26); cost is trimming bull_low trends (-0.54).

**Degrading scenarios (volatility_clustering, fat_tail_crash):**
- `volatility_clustering`: bull_high delta -0.46 (sma) / -1.07 (ema) while that regime's baseline Sharpe is +0.74/+1.14 — detector labels >50% of bars high_vol (2741/5000, 16 runs median 158 bars vs truth clusters ~20 bars at persistence 0.95), so slow exit from high_vol chops trending exposure after clusters end.
- `fat_tail_crash`: detection is trailing/inconsistent — crash-day regimes are already bear_high/bull_high with no consistent post-crash flip; bear_high delta -0.93/-0.90 (sizes down after the jump), bear_low -0.95 for ema (whipsaw re-entry), sideways_high -1.52.

### Part B — detection lag vs truth
- `regime_shift`: at truth transition start (bar 378) detector still said bull_high; bear_high first at bar 435 (vs truth bear start 441) — roughly on time, helped by transition vol spike.
- `structural_break`: at truth break (bar 2500) detector said bear_low — vol step 0.015→0.025 too small to flip the 63-bar quantile regime quickly (under-reaction).
- `liquidity_crisis`: at crisis start (bar 3000) detector said bull_low; bear_high only by crisis end (bar 3126) — slow ~63-bar vol-window entry, protection starts mid-crisis.
- `fat_tail_crash`: 23 crashes; no consistent detection at/after crash day (trailing).
- `trend_persistence`: single-truth-regime, yet 64 detected changes — detector is noisy even with no regime change.

### Mechanism summary
The overlay helps where regimes are persistent and choppy or post-break (sizing down in sideways/bear cuts losses), and hurts where high_vol labels coincide with trending exposure (volatility_clustering bull_high) or where detection lags a discontinuous jump (fat_tail_crash bear_high). Driver: **trailing 63-bar volatility quantile + min_regime_length=21 makes regime labels sticky and slow to flip**, plus **uniform 10% target vol** trims trend premium in high_vol trending regimes.

## Files created
- `skills/quantitative-backtesting/scripts/diagnose_regime_overlay.py` (untracked; run with `python3 skills/quantitative-backtesting/scripts/diagnose_regime_overlay.py` from repo root)
- Evidence: `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json` (per-variant `baseline.regime_analysis.combined_regime_performance` vs `regime_sized.regime_analysis.combined_regime_performance`)

## What remains unresolved
1. Does a less sticky detector (shorter vol_window, different quantiles) or different target_vol recover the degrading scenarios without losing the improving ones? (Unanswered — this is the next task.)
2. Do the results hold on other strategy classes (mean-reversion, momentum)? Untested.
3. Still no statistical significance — all p ≈ 1.0; synthetic data only.

## Approaches already tried / failed
- Session 144 single-scenario example: falsified on volatility_clustering/ema_crossover.
- Cost multipliers without sizing change: no effect (|Δ Sharpe| < 0.015).
- Full adversarial sweep (session 145): criterion passed, null does not generalize.

## One precise next task
**Target_vol × vol_window sweep on the degrading scenarios, with improving scenarios as controls.**

Extend `skills/quantitative-backtesting/examples/adversarial_stress_test.py` (REGIME-AWARE VARIANTS section, lines 556–743) or a standalone script reusing `RegimeAwareStrategy`:
- target_vol ∈ {0.05, 0.10, 0.15, 0.20}
- vol_window ∈ {21, 63, 126} (keep vol_quantiles 0.25/0.75, min_regime_length 21)
- Run on all 6 scenarios × SMA/EMA; compare OOS Sharpe delta vs baseline and re-run per-regime attribution (Part A above) to confirm where gains/losses shift.
- Success criterion: reduce volatility_clustering/fat_tail_crash delta below baseline (less negative) while keeping regime_shift/liquidity_crisis/structural_break/trend_persistence non-negative; report per-regime attribution, no statistical-significance claims.

## Constraint
- Do not claim statistical significance, profitability, or robustness — synthetic adversarial data, DSR p ≈ 1.0, test resolution ≈ 2.0 Sharpe.
- Preserve the pre-registered falsification discipline and the existing walk-forward/PIT controls; smallest reversible change to the sweep code only.

(End of file)
