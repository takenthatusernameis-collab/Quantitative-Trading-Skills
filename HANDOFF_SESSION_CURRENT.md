# Handoff — Next Session (2026-11-21): fat_tail_crash detector-tuning thread exhausted

## Baseline
- HEAD `ce256d6`, branch `main`; working tree clean except this session's uncommitted changes (see `git status`: crash trigger detector scripts, results JSON, handoff).
- Session 148 completed the crash-trigger detector experiment assigned by session 147. See `HANDOFF_SESSION_148.md` for full details.

## What changed this session (archive: HANDOFF_SESSION_148.md)
- `crash_trigger_detector.py`: crash-trigger detector with 5% threshold (no change, as expected with uniform target_vol).
- `crash_trigger_per_regime.py`: crash-trigger detector with per-regime target_vol (worse than default).
- `crash_only_detector.py`: crash-only detector (removes false positive bear_high at 325, adds bear_high at crash 366) with per-regime target_vol.
- `crash_only_results.json`, `crash_trigger_results.json`, `crash_trigger_per_regime_results.json`: committed results.

## Key findings (evidence in crash_only_results.json)
- **Crash-trigger detector with uniform target_vol (0.20)**: No difference from default (delta = -0.0533 SMA, -0.3701 EMA). Expected: all regimes get same target_vol.
- **Crash-only detector with per-regime target_vol (bear_high=0.10)**:
  - First bear_high at 366 (vs 325 for default) — correctly identifies the crash.
  - Delta = -0.1085 for SMA (vs -0.1684 default per-regime) — **BETTER by +0.0599**.
  - Delta = -0.3745 for EMA (vs -0.4190 default per-regime) — **BETTER by +0.0446**.
  - But still worse than uniform 0.20 (delta = -0.0533 and -0.3701).
- **Best strategy for fat_tail_crash**: Uniform target_vol 0.20 (no regime differentiation). The crash-only detector with per-regime target_vol improves over the default with per-regime, but neither can beat uniform target_vol 0.20.
- **Detector-tuning thread is EXHAUSTED**: Crash-trigger detector tuning (5% threshold, 3% threshold, 7% threshold, crash-only, hybrid) all fail to recover the degradation vs baseline at uniform tv=0.20. The best approach for fat_tail_crash is uniform target_vol without regime-based sizing.
- All results are point estimates on synthetic adversarial data (DSR p ≈ 1.0); no profitability claim.

## One precise next task
**Move to a different quant research methodology task.**

The fat_tail_crash detector-tuning thread is exhausted:
- Target_vol retuning (0.05-0.20): best is 0.20, still degrades (-0.0533 SMA, -0.3701 EMA).
- Vol-quantile/min-length tuning: no effect on first bear_high (325).
- Crash-trigger detector (5% threshold): no effect with uniform target_vol.
- Crash-only detector (removes false positive, adds bear_high at crash 366): better than default with per-regime, but worse than uniform 0.20.
- Crash-only detector with per-regime target_vol: better than default with per-regime (+0.0599 SMA, +0.0446 EMA), but worse than uniform 0.20.

Suggested next steps (pick ONE bounded task):
1. **HMM-based regime detection** on fat_tail_crash at uniform tv=0.20 (different detector family, may capture crash dynamics better than quantile-based).
2. **Returns-based regime detection** (detect bear_high from cumulative negative returns instead of volatility quantiles).
3. **Multi-asset regime detection** (test on correlation_breakdown or multi_asset_vol_clustering scenarios).
4. **Walk-forward with regime-aware parameter selection** (select parameters based on regime-specific performance, not just overall Sharpe).
5. **Different scenario**: test the regime-aware overlay on a new adversarial scenario (e.g., momentum_crash, illiquidity_spiral).

Constraints: no statistical-significance or profitability claims; synthetic adversarial data; reuse `detect_combined_regime` + `walk_forward_analysis`; do not commit unless asked; pytest is not installed in /tmp/venv.

### Evidence locations
- `skills/quantitative-backtesting/scripts/crash_trigger_detector.py` (crash-trigger detector with 5% threshold)
- `skills/quantitative-backtesting/scripts/crash_trigger_per_regime.py` (crash-trigger detector with per-regime target_vol)
- `skills/quantitative-backtesting/scripts/crash_only_detector.py` (crash-only detector with per-regime target_vol)
- `skills/quantitative-backtesting/examples/crash_only_results.json` (committed results)
- `skills/quantitative-backtesting/examples/crash_trigger_results.json` (committed results)
- `skills/quantitative-backtesting/examples/crash_trigger_per_regime_results.json` (committed results)
- Baseline: repo-root `adversarial_stress_test_results.json`
- Environment: `/tmp/venv` → `source /tmp/venv/bin/activate` (no pytest installed)

(End of file)