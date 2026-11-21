# Handoff — Session 146 (2026-11-21): Regime-aware overlay mechanism diagnosed

## Baseline
- HEAD `ce256d6`, branch `main`, working tree clean (this session added 2 files, uncommitted).
- Session 145 established: regime-aware vol targeting (10% annualized vol per regime) improves OOS Sharpe in 8/12 adversarial scenario-strategy combos, degrades 4/12; null result does NOT generalize (criterion passed). All DSR p-values ≈ 1.0, test resolution ≈ 2.0 Sharpe — no statistical significance; point-estimate mechanism diagnosis only.

## What this session did
Ran per-regime attribution + regime-detection lag analysis over the existing extended results (no new computation):
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic.py` (new)
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md` (new)

## What was actually verified (ground truth)

### Per-regime attribution (baseline vs regime_sized Sharpe, observation-weighted)
| Scenario | Strategy | Outcome | Base Sharpe | Sized Sharpe | Δ | Top degradation regime | Top improvement regime |
|----------|----------|---------|-------------|--------------|---|------------------------|------------------------|
| volatility_clustering | sma | Degraded | 0.0919 | 0.0405 | -0.051 | bull_high (-693) | bear_high (+698) |
| volatility_clustering | ema | Degraded | 0.2766 | 0.1759 | -0.101 | bull_high (-1607) | bear_low (+776) |
| regime_shift | sma | Improved | -0.2657 | -0.1319 | +0.134 | bull_low (-475) | bear_low (+463) |
| regime_shift | ema | Improved | -0.1623 | 0.0138 | +0.176 | bull_low (-485) | bear_high (+898) |
| fat_tail_crash | sma | Degraded | -0.0060 | -0.1807 | -0.175 | bear_high (-877) | sideways_low (+508) |
| fat_tail_crash | ema | Degraded | 0.2142 | -0.2763 | -0.490 | bear_high (-852) | sideways_low (+464) |
| liquidity_crisis | sma | Improved | 0.0108 | 0.0371 | +0.026 | bull_high (-885) | sideways_high (+2026) |
| liquidity_crisis | ema | Improved | 0.0437 | 0.1726 | +0.129 | bull_high (-851) | sideways_high (+2154) |
| structural_break | sma | Improved | 0.1306 | 0.1476 | +0.017 | bull_low (-523) | sideways_high (+1277) |
| structural_break | ema | Improved | 0.0127 | 0.1019 | +0.089 | bull_low (-558) | sideways_high (+1271) |
| trend_persistence | sma | Improved | 0.5007 | 0.9261 | +0.425 | bull_low (-718) | bull_high (+945) |
| trend_persistence | ema | Improved | 0.5936 | 1.1147 | +0.521 | bull_low (-201) | bear_high (+680) |

### Regime detection timing (lag proxy)
- fat_tail_crash both strategies: `bear_high` first starts 2016-05-16, AFTER the worst drawdown period (sma: 2016-04-06→05-13 bear_low -0.2712; ema: 2016-03-01→03-17 bull_high -0.3442). Lag = yes → trailing detection: sizes down too late to protect, too early to recover.
- regime_shift ema: lag = yes yet still improved (bear_high drives +898).
- volatility_clustering: no lag, yet degrades — detector over-reacts to transient vol spikes (bull_high Sharpe 0.7408 → 0.2774 for SMA).

### Mechanism conclusion
- **Improving** (trend_persistence, structural_break, liquidity_crisis, regime_shift): positive deltas from bear_low/bull_high — sizing down in high-vol bear regimes and up in low-vol bull regimes aligns exposure with the trend and cuts impact cost in crises.
- **Degrading** (volatility_clustering, fat_tail_crash): negative deltas in bull_high/bear_high — over-reaction to transient vol spikes or trailing crash detection.
- Pattern is **scenario- and regime-dependent, not uniform**: fixed 10% target vol + fixed windows (trend MA 50/200, vol window 63, quantiles 0.25/0.75) is not optimal across return-generating processes. Per-regime target_vol tuning or a faster/slower detector is the logical next experiment.

## Files Created/Updated
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic.py`
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md`

## What remains unresolved
1. Is a non-uniform target_vol per regime better than flat 10%? (target_vol sweep)
2. Regime detector config sensitivity (vol_window, quantiles, trend MA).
3. Other strategy classes (mean-reversion, momentum).
4. No statistical significance — all p-values ≈ 1.0 (expected on synthetic adversarial data).

## Approaches already tried / failed
- Session 144 single-scenario worked example: falsified on volatility_clustering/ema.
- Cost multipliers without sizing change: no effect.
- Session 145 full adversarial sweep: criterion passed (null not universal).
- This session: per-regime attribution + lag timing (succeeded — mechanism identified).

## One precise next task
**target_vol sweep: test target_vol ∈ {0.05, 0.10, 0.15, 0.20} on the 4 improving and 4 degrading scenario-strategy combinations** to determine whether the uniform 10% target is the problem and whether per-regime target_vol tuning can recover the degrading scenarios without losing the improving ones.

Concrete steps:
1. Extend `skills/quantitative-backtesting/examples/adversarial_stress_test.py` (variant sweep, lines 556–743) to loop target_vol over {0.05, 0.10, 0.15, 0.20} for the 8 relevant scenario-strategy pairs, recording OOS Sharpe for baseline vs regime_sized per level.
2. Produce a small table: for each pair, the target_vol that maximizes regime_sized Sharpe, and whether any single target_vol improves all 8 (or whether per-regime targets are required).
3. Update/extend `regime_aware_diagnostic_report.md` with the sweep findings.

Constraints:
- Do not claim statistical significance or profitability (synthetic adversarial data, p-values ≈ 1.0).
- Reuse the existing walk-forward + Deflated Sharpe controls already in the sweep.
- Preserve the falsification discipline; verdicts remain methodological, not performance claims.

### Evidence Locations
- Extended results: `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json`
- Sweep code: `skills/quantitative-backtesting/examples/adversarial_stress_test.py` (lines 556–743)
- This session's report: `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md`

(End of file)
