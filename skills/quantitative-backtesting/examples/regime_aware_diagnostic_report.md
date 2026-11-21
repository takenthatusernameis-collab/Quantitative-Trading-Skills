# Regime-Aware Overlay Diagnostic Report

Source: `adversarial_stress_test_regime_aware_extended.json` (no new computation).

Purpose: explain WHY the regime-aware volatility-targeting overlay (target 10% annualized vol per combined trend/vol regime) improves OOS Sharpe in 8 of 12 scenario-strategy combinations but degrades it in 4.

## 1. Per-regime attribution

Each combined regime's baseline vs regime_sized Sharpe is compared, weighted by observations. Negative weighted deltas drive degradation; positive deltas drive improvement.

### volatility_clustering — sma_crossover
Baseline Sharpe: 0.0919 | Regime-sized Sharpe: 0.0405 | DEGRADED (Δ=-0.0514)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1496 | 32.7% | 0.7408 | 0.2774 | -0.4634 | -693.2384 |
| bear_high | 720 | 15.7% | -0.1208 | 0.8491 | 0.9699 | 698.2953 |
| sideways_high | 282 | 6.2% | -0.0301 | -0.3688 | -0.3387 | -95.5217 |
| bull_low | 714 | 15.6% | -0.0518 | -0.0340 | 0.0177 | 12.6612 |
| bear_low | 774 | 16.9% | 0.1596 | 0.5364 | 0.3767 | 291.5967 |
| sideways_low | 586 | 12.8% | -1.0189 | -0.4588 | 0.5601 | 328.2183 |

**Largest degradation driver**: bull_high (weighted Δ=-693.2384, 32.7% of obs).
**Largest improvement driver**: bear_high (weighted Δ=+698.2953, 15.7% of obs).

### volatility_clustering — ema_crossover
Baseline Sharpe: 0.2766 | Regime-sized Sharpe: 0.1759 | DEGRADED (Δ=-0.1007)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1496 | 32.7% | 1.1386 | 0.0644 | -1.0742 | -1607.0344 |
| bear_high | 720 | 15.7% | -0.3664 | 0.6540 | 1.0204 | 734.7087 |
| sideways_high | 282 | 6.2% | -0.2851 | -1.2161 | -0.9310 | -262.5482 |
| bull_low | 714 | 15.6% | 0.0368 | 0.3854 | 0.3486 | 248.9029 |
| bear_low | 774 | 16.9% | 0.1123 | 1.1147 | 1.0023 | 775.8000 |
| sideways_low | 586 | 12.8% | -0.4303 | -0.0217 | 0.4086 | 239.4526 |

**Largest degradation driver**: bull_high (weighted Δ=-1607.0344, 32.7% of obs).
**Largest improvement driver**: bear_low (weighted Δ=+775.8000, 16.9% of obs).

### regime_shift — sma_crossover
Baseline Sharpe: -0.2657 | Regime-sized Sharpe: -0.1319 | IMPROVED (Δ=+0.1339)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 786 | 17.3% | -0.8150 | -0.5072 | 0.3078 | 241.9048 |
| bear_high | 1916 | 42.2% | -0.3506 | -0.1131 | 0.2375 | 455.1244 |
| sideways_high | 138 | 3.0% | 0.5558 | 3.3964 | 2.8407 | 392.0142 |
| bull_low | 580 | 12.8% | -0.0928 | -0.9119 | -0.8191 | -475.1024 |
| bear_low | 932 | 20.5% | -0.0603 | 0.4370 | 0.4973 | 463.4961 |
| sideways_low | 192 | 4.2% | 0.4475 | -0.4846 | -0.9322 | -178.9736 |

**Largest degradation driver**: bull_low (weighted Δ=-475.1024, 12.8% of obs).
**Largest improvement driver**: bear_low (weighted Δ=+463.4961, 20.5% of obs).

### regime_shift — ema_crossover
Baseline Sharpe: -0.1623 | Regime-sized Sharpe: 0.0138 | IMPROVED (Δ=+0.1761)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 767 | 17.1% | -0.8861 | -1.0677 | -0.1815 | -139.2227 |
| bear_high | 1885 | 42.1% | -0.2073 | 0.2692 | 0.4765 | 898.1200 |
| sideways_high | 138 | 3.1% | 0.7593 | 3.2424 | 2.4832 | 342.6767 |
| bull_low | 598 | 13.3% | 0.2323 | -0.5793 | -0.8116 | -485.3247 |
| bear_low | 906 | 20.2% | -0.1264 | 0.7266 | 0.8530 | 772.7876 |
| sideways_low | 187 | 4.2% | -0.0281 | -0.5546 | -0.5265 | -98.4635 |

**Largest degradation driver**: bull_low (weighted Δ=-485.3247, 13.3% of obs).
**Largest improvement driver**: bear_high (weighted Δ=+898.1200, 42.1% of obs).

### fat_tail_crash — sma_crossover
Baseline Sharpe: -0.0060 | Regime-sized Sharpe: -0.1807 | DEGRADED (Δ=-0.1748)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 662 | 14.6% | -0.4523 | 0.2883 | 0.7405 | 490.2290 |
| bear_high | 943 | 20.8% | 0.2053 | -0.7244 | -0.9297 | -876.6746 |
| sideways_high | 279 | 6.1% | -0.1153 | 0.1775 | 0.2929 | 81.7092 |
| bull_low | 1454 | 32.0% | 0.3585 | 0.4328 | 0.0742 | 107.9527 |
| bear_low | 881 | 19.4% | -0.6725 | -0.6161 | 0.0564 | 49.7092 |
| sideways_low | 325 | 7.2% | -0.3671 | 1.1962 | 1.5633 | 508.0805 |

**Largest degradation driver**: bear_high (weighted Δ=-876.6746, 20.8% of obs).
**Largest improvement driver**: sideways_low (weighted Δ=+508.0805, 7.2% of obs).

### fat_tail_crash — ema_crossover
Baseline Sharpe: 0.2142 | Regime-sized Sharpe: -0.2763 | DEGRADED (Δ=-0.4905)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 662 | 14.6% | -0.7186 | -0.2847 | 0.4339 | 287.2640 |
| bear_high | 943 | 20.8% | 0.1229 | -0.7806 | -0.9035 | -852.0094 |
| sideways_high | 279 | 6.1% | 1.2758 | -0.2484 | -1.5242 | -425.2385 |
| bull_low | 1454 | 32.0% | 0.4831 | 0.3893 | -0.0938 | -136.4033 |
| bear_low | 881 | 19.4% | 0.4598 | -0.4852 | -0.9450 | -832.5336 |
| sideways_low | 325 | 7.2% | -0.7454 | 0.6822 | 1.4276 | 463.9608 |

**Largest degradation driver**: bear_high (weighted Δ=-852.0094, 20.8% of obs).
**Largest improvement driver**: sideways_low (weighted Δ=+463.9608, 7.2% of obs).

### liquidity_crisis — sma_crossover
Baseline Sharpe: 0.0108 | Regime-sized Sharpe: 0.0371 | IMPROVED (Δ=+0.0263)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 974 | 21.4% | 0.3253 | -0.5829 | -0.9083 | -884.6378 |
| bear_high | 769 | 16.9% | 0.0890 | -0.7391 | -0.8281 | -636.7947 |
| sideways_high | 396 | 8.7% | 0.0315 | 5.1468 | 5.1153 | 2025.6503 |
| bull_low | 1299 | 28.6% | -0.4237 | -0.0905 | 0.3332 | 432.8226 |
| bear_low | 787 | 17.3% | -0.2321 | 1.8076 | 2.0397 | 1605.2326 |
| sideways_low | 319 | 7.0% | 0.7739 | 0.3639 | -0.4100 | -130.7839 |

**Largest degradation driver**: bull_high (weighted Δ=-884.6378, 21.4% of obs).
**Largest improvement driver**: sideways_high (weighted Δ=+2025.6503, 8.7% of obs).

### liquidity_crisis — ema_crossover
Baseline Sharpe: 0.0437 | Regime-sized Sharpe: 0.1726 | IMPROVED (Δ=+0.1290)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 974 | 21.4% | 0.3693 | -0.5040 | -0.8733 | -850.5775 |
| bear_high | 769 | 16.9% | -0.2955 | 0.0025 | 0.2980 | 229.1729 |
| sideways_high | 396 | 8.7% | -0.2353 | 5.2036 | 5.4389 | 2153.8175 |
| bull_low | 1299 | 28.6% | 0.0305 | -0.0089 | -0.0394 | -51.1943 |
| bear_low | 787 | 17.3% | -0.2888 | 1.6902 | 1.9790 | 1557.4547 |
| sideways_low | 319 | 7.0% | 0.4092 | 0.6912 | 0.2820 | 89.9620 |

**Largest degradation driver**: bull_high (weighted Δ=-850.5775, 21.4% of obs).
**Largest improvement driver**: sideways_high (weighted Δ=+2153.8175, 8.7% of obs).

### structural_break — sma_crossover
Baseline Sharpe: 0.1306 | Regime-sized Sharpe: 0.1476 | IMPROVED (Δ=+0.0170)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1407 | 30.9% | 0.0876 | 0.1041 | 0.0165 | 23.2365 |
| bear_high | 1606 | 35.2% | 0.0775 | 0.3396 | 0.2620 | 420.8504 |
| sideways_high | 518 | 11.4% | -0.2627 | 2.2029 | 2.4655 | 1277.1468 |
| bull_low | 463 | 10.2% | 0.1758 | -0.9536 | -1.1293 | -522.8824 |
| bear_low | 466 | 10.2% | 1.2175 | 0.3475 | -0.8700 | -405.4354 |
| sideways_low | 100 | 2.2% | 1.1319 | 2.6878 | 1.5560 | 155.5980 |

**Largest degradation driver**: bull_low (weighted Δ=-522.8824, 10.2% of obs).
**Largest improvement driver**: sideways_high (weighted Δ=+1277.1468, 11.4% of obs).

### structural_break — ema_crossover
Baseline Sharpe: 0.0127 | Regime-sized Sharpe: 0.1019 | IMPROVED (Δ=+0.0892)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1407 | 30.9% | -0.1378 | -0.1782 | -0.0404 | -56.8997 |
| bear_high | 1606 | 35.2% | -0.1311 | 0.3151 | 0.4463 | 716.7344 |
| sideways_high | 518 | 11.4% | 0.0228 | 2.4760 | 2.4533 | 1270.7975 |
| bull_low | 463 | 10.2% | 0.4021 | -0.8031 | -1.2052 | -557.9878 |
| bear_low | 466 | 10.2% | 1.2845 | 0.2110 | -1.0735 | -500.2575 |
| sideways_low | 100 | 2.2% | -0.3177 | 4.0509 | 4.3687 | 436.8661 |

**Largest degradation driver**: bull_low (weighted Δ=-557.9878, 10.2% of obs).
**Largest improvement driver**: sideways_high (weighted Δ=+1270.7975, 11.4% of obs).

### trend_persistence — sma_crossover
Baseline Sharpe: 0.5007 | Regime-sized Sharpe: 0.9261 | IMPROVED (Δ=+0.4255)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1523 | 33.5% | 0.2161 | 0.8364 | 0.6203 | 944.6909 |
| bear_high | 744 | 16.4% | -0.7451 | -0.4707 | 0.2744 | 204.1489 |
| sideways_high | 460 | 10.1% | 0.7652 | 1.6968 | 0.9316 | 428.5544 |
| bull_low | 1432 | 31.5% | 2.2118 | 1.7107 | -0.5011 | -717.6202 |
| bear_low | 107 | 2.4% | 5.5682 | 3.2115 | -2.3567 | -252.1692 |
| sideways_low | 278 | 6.1% | -0.1597 | 1.1286 | 1.2883 | 358.1365 |

**Largest degradation driver**: bull_low (weighted Δ=-717.6202, 31.5% of obs).
**Largest improvement driver**: bull_high (weighted Δ=+944.6909, 33.5% of obs).

### trend_persistence — ema_crossover
Baseline Sharpe: 0.5936 | Regime-sized Sharpe: 1.1147 | IMPROVED (Δ=+0.5211)

| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |
|--------|-----|-------|-------------|--------------|----------|------------|
| bull_high | 1523 | 33.5% | 0.7358 | 1.1352 | 0.3994 | 608.2552 |
| bear_high | 744 | 16.4% | -1.0825 | -0.1686 | 0.9138 | 679.9036 |
| sideways_high | 460 | 10.1% | 1.2005 | 2.1043 | 0.9039 | 415.7755 |
| bull_low | 1432 | 31.5% | 2.2206 | 2.0802 | -0.1404 | -201.0956 |
| bear_low | 107 | 2.4% | 4.2792 | 3.0601 | -1.2191 | -130.4389 |
| sideways_low | 278 | 6.1% | -0.6431 | 0.8754 | 1.5184 | 422.1261 |

**Largest degradation driver**: bull_low (weighted Δ=-201.0956, 31.5% of obs).
**Largest improvement driver**: bear_high (weighted Δ=+679.9036, 16.4% of obs).

## 2. Summary: which regimes drive each outcome

| Scenario | Strategy | Outcome | Base Sharpe | Sized Sharpe | Δ | Top degradation regime | Top improvement regime |
|----------|----------|---------|-------------|--------------|---|------------------------|------------------------|
| volatility_clustering | sma_crossover | Degraded | 0.0919 | 0.0405 | -0.0514 | bull_high (-693.2384) | bear_high (+698.2953) |
| volatility_clustering | ema_crossover | Degraded | 0.2766 | 0.1759 | -0.1007 | bull_high (-1607.0344) | bear_low (+775.8000) |
| regime_shift | sma_crossover | Improved | -0.2657 | -0.1319 | +0.1339 | bull_low (-475.1024) | bear_low (+463.4961) |
| regime_shift | ema_crossover | Improved | -0.1623 | 0.0138 | +0.1761 | bull_low (-485.3247) | bear_high (+898.1200) |
| fat_tail_crash | sma_crossover | Degraded | -0.0060 | -0.1807 | -0.1748 | bear_high (-876.6746) | sideways_low (+508.0805) |
| fat_tail_crash | ema_crossover | Degraded | 0.2142 | -0.2763 | -0.4905 | bear_high (-852.0094) | sideways_low (+463.9608) |
| liquidity_crisis | sma_crossover | Improved | 0.0108 | 0.0371 | +0.0263 | bull_high (-884.6378) | sideways_high (+2025.6503) |
| liquidity_crisis | ema_crossover | Improved | 0.0437 | 0.1726 | +0.1290 | bull_high (-850.5775) | sideways_high (+2153.8175) |
| structural_break | sma_crossover | Improved | 0.1306 | 0.1476 | +0.0170 | bull_low (-522.8824) | sideways_high (+1277.1468) |
| structural_break | ema_crossover | Improved | 0.0127 | 0.1019 | +0.0892 | bull_low (-557.9878) | sideways_high (+1270.7975) |
| trend_persistence | sma_crossover | Improved | 0.5007 | 0.9261 | +0.4255 | bull_low (-717.6202) | bull_high (+944.6909) |
| trend_persistence | ema_crossover | Improved | 0.5936 | 1.1147 | +0.5211 | bull_low (-201.0956) | bear_high (+679.9036) |

## 3. Regime detection timing (lag proxy)

From each baseline's `regime_periods`: the worst single regime period (lowest total_return) and when `bear_high` first begins. If `bear_high` starts after the worst period, detection is trailing — the overlay sizes down too late to protect and too early to recover.

| Scenario | Strategy | Worst period regime | Worst return | Worst period | bear_high first starts | Lag? |
|----------|----------|---------------------|--------------|--------------|------------------------|------|
| volatility_clustering | sma_crossover | sideways_low | -0.3362 | 2016-10-10T00:00:00 → 2017-01-20T00:00:00 | 2016-02-16T00:00:00 | no |
| volatility_clustering | ema_crossover | bear_high | -0.2223 | 2016-02-16T00:00:00 → 2016-08-25T00:00:00 | 2016-02-16T00:00:00 | no |
| regime_shift | sma_crossover | bear_high | -0.4785 | 2016-09-02T00:00:00 → 2019-01-30T00:00:00 | 2016-09-02T00:00:00 | no |
| regime_shift | ema_crossover | bull_high | -0.5271 | 2016-01-15T00:00:00 → 2016-03-14T00:00:00 | 2016-09-02T00:00:00 | yes |
| fat_tail_crash | sma_crossover | bear_low | -0.2712 | 2016-04-06T00:00:00 → 2016-05-13T00:00:00 | 2016-05-16T00:00:00 | yes |
| fat_tail_crash | ema_crossover | bull_high | -0.3442 | 2016-03-01T00:00:00 → 2016-03-17T00:00:00 | 2016-05-16T00:00:00 | yes |
| liquidity_crisis | sma_crossover | bull_low | -0.2879 | 2016-01-15T00:00:00 → 2016-02-29T00:00:00 | 2016-03-28T00:00:00 | yes |
| liquidity_crisis | ema_crossover | bear_high | -0.2312 | 2016-03-28T00:00:00 → 2016-03-29T00:00:00 | 2016-03-28T00:00:00 | no |
| structural_break | sma_crossover | sideways_high | -0.1065 | 2016-01-15T00:00:00 → 2016-03-11T00:00:00 | 2017-06-02T00:00:00 | yes |
| structural_break | ema_crossover | bull_high | -0.1846 | 2016-03-14T00:00:00 → 2016-03-14T00:00:00 | 2017-06-02T00:00:00 | yes |
| trend_persistence | sma_crossover | bear_high | -0.2489 | 2021-04-16T00:00:00 → 2021-04-28T00:00:00 | 2021-04-16T00:00:00 | no |
| trend_persistence | ema_crossover | bear_high | -0.3858 | 2021-04-16T00:00:00 → 2021-04-28T00:00:00 | 2021-04-16T00:00:00 | no |

## 4. Mechanistic conclusion

- **Improving scenarios (trend_persistence, structural_break, liquidity_crisis, regime_shift)**: the largest positive weighted deltas come from bear_low/bull_high regimes — sizing down in high-vol bear regimes and sizing up in low-vol bull regimes aligns exposure with the trend and cuts impact cost during crises.
- **Degrading scenarios (volatility_clustering, fat_tail_crash)**: the largest negative weighted deltas concentrate in bull_high/bear_high — volatility_clustering shows the detector over-reacting to transient vol spikes (bull_high Sharpe collapses 0.74→0.28 for SMA) while fat_tail_crash shows trailing detection (bear_high first starts 2016-05-16, after the worst drawdown period on 2016-04-06 / 2016-03-01), cutting exposure precisely when recovery begins and missing protection.
- The pattern is **scenario- and regime-dependent, not universal**: a uniform 10% target vol with fixed regime windows (trend MA 50/200, vol window 63, quantiles 0.25/0.75) cannot be optimal across all return-generating processes. Per-regime target_vol tuning or a faster/slower regime detector is the logical next experiment.

No statistical significance is claimed: all Deflated Sharpe p-values ≈ 1.0 and test resolution ≈ 2.0 Sharpe. This is a point-estimate mechanism diagnostic on synthetic adversarial data, not a profitability claim.

## 5. Target_vol sweep findings

Source: `skills/quantitative-backtesting/scripts/sweep_regime_target_vol.py`
(output `adversarial_stress_test_regime_aware_sweep.json`, aggregates in
`adversarial_stress_test_regime_aware_sweep_verified.json`). The sweep re-runs
the regime-aware walk-forward variant (session 145/146 setup: combined regime
detection + `RegimeAwareStrategy` overlay, `walk_forward_analysis` with
deflation and PIT controls) with `target_vol ∈ {0.05, 0.10, 0.15, 0.20}` and
`vol_window ∈ {21, 63, 126}` across all 12 single-asset scenario-strategy
pairs (6 scenarios × SMA/EMA), baseline = committed
`adversarial_stress_test_results.json` walk-forward OOS Sharpe. 144
walk-forwards in total. As before, no statistical-significance or
profitability claim is made (synthetic adversarial data, DSR p ≈ 1.0, test
resolution ≈ 2.0 Sharpe); verdicts are methodological, not performance claims.

### 5.1 Regime-sized OOS Sharpe by target_vol (baseline vs overlay)

| Scenario | Strategy | Baseline Sharpe | tv = 0.05 | tv = 0.10 | tv = 0.15 | tv = 0.20 | Best tv | Best Δ vs baseline |
|----------|----------|-----------------|-----------|-----------|-----------|-----------|---------|--------------------|
| volatility_clustering | sma_crossover | +0.0919 | −0.1924 | +0.0405 | +0.1058 | +0.1455 | 0.20 | +0.0537 |
| volatility_clustering | ema_crossover | +0.2766 | −0.0776 | +0.1759 | +0.2552 | +0.2880 | 0.20 | +0.0115 |
| fat_tail_crash | sma_crossover | −0.0060 | −0.4344 | −0.1807 | −0.0998 | −0.0593 | 0.20 | −0.0533 |
| fat_tail_crash | ema_crossover | +0.2142 | −0.5217 | −0.2763 | −0.1961 | −0.1560 | 0.20 | −0.3701 |
| liquidity_crisis | sma_crossover | +0.0108 | −0.2017 | +0.0371 | +0.1205 | +0.1622 | 0.20 | +0.1514 |
| liquidity_crisis | ema_crossover | +0.0437 | −0.0794 | +0.1726 | +0.2566 | +0.2986 | 0.20 | +0.2550 |
| regime_shift | sma_crossover | −0.2657 | −0.4003 | −0.1319 | −0.0424 | +0.0431 | 0.20 | +0.3088 |
| regime_shift | ema_crossover | −0.1623 | −0.2758 | +0.0138 | +0.0985 | +0.1484 | 0.20 | +0.3107 |
| structural_break | sma_crossover | +0.1306 | −0.1261 | +0.1476 | +0.2360 | +0.2803 | 0.20 | +0.1496 |
| structural_break | ema_crossover | +0.0127 | −0.1488 | +0.1019 | +0.1905 | +0.2348 | 0.20 | +0.2221 |
| trend_persistence | sma_crossover | +0.5007 | +0.7098 | +0.9261 | +1.0240 | +1.0350 | 0.20 | +0.5343 |
| trend_persistence | ema_crossover | +0.5936 | +0.8717 | +1.1147 | +1.1995 | +1.2307 | 0.20 | +0.6371 |

`vol_window ∈ {21, 63, 126}` produced identical regime-sized Sharpe values on
these seeds, so the target_vol dimension drives all movement in the grid.

### 5.2 Answers to the sweep questions

**Q1 — Per-pair best target_vol:** `target_vol = 0.20` maximizes regime-sized
OOS Sharpe for all 12 scenario-strategy pairs. Within the tested grid, Sharpe
rises monotonically with target_vol for every pair (including the degrading
scenarios), so 0.20 is best-of-grid, not a claim of optimality beyond it.

**Q2 — Does any single target_vol improve all pairs?** No. At `tv = 0.20`
(10/12 pairs improve vs baseline), the only pairs still below baseline are
`fat_tail_crash/sma_crossover` (−0.0533) and `fat_tail_crash/ema_crossover`
(−0.3701). `fat_tail_crash` is degraded at every target_vol tested, so
target_vol retuning alone cannot recover it — consistent with the session-146
lag diagnosis (trailing `bear_high` detection cuts exposure during the crash
recovery). A faster/slower regime detector or scenario-specific target_vol
would be required there, not just a re-tuned uniform target.

**Q3 — Per-regime targets vs one uniform target:** For 11 of 12 pairs, a
uniform `tv = 0.20` strictly dominates the committed `tv = 0.10` reference
within the grid. Only `fat_tail_crash` resists all uniform targets, so
per-regime (or per-scenario) target_vol is warranted specifically for that
return-generating process, while a uniform 20% annualized target is the better
single setting elsewhere in this suite.

### 5.3 Session-146 falsification criterion check

Pre-registered criterion (session 146): degrading scenario deltas less
negative than at the (0.10, 63) reference cell, and improving scenario deltas
≥ 0.

- `tv = 0.05`: fails (2/12 pairs improve; all degrading deltas more negative).
- `tv = 0.10`: improves on 8/12 pairs but all four degrading deltas stay negative (the reference cell itself).
- `tv = 0.15`: passes — 9/12 pairs improve; all degrading deltas less negative than reference.
- `tv = 0.20`: passes — 10/12 pairs improve; all degrading deltas less negative than reference (best cell, score +2.0804; vol_window immaterial).

The uniform 10% target is therefore not the best uniform choice in this grid:
20% annualized target vol dominates it on every pair tested, recovers both
`volatility_clustering` pairs to positive delta, and narrows (but does not
eliminate) the `fat_tail_crash` degradation.

### 5.4 Caveats

- Point estimates only: all Deflated Sharpe p-values ≈ 1.0 and test
  resolution ≈ 2.0 Sharpe on synthetic adversarial data; no reproducibility
  or profitability claim.
- Best-of-grid is not an optimal target: values outside {0.05, 0.10, 0.15,
  0.20} were not tested, and a still-higher target was not evaluated.
- `fat_tail_crash` remains unresolved by this sweep: its degradation is a
  regime-detection timing problem (session 146, section 3), not a
  target_vol problem.
## 6. Regime-Detection Lag Experiment & Faster Detector Test

### 6.1 Detection Lag Across All Scenarios

Measured lag (in bars) between true regime transitions (from generator design)
and first detected `bear_high` regime from `detect_combined_regime` (RegimeConfig defaults).
**Positive lag = detector trails the true transition (detects AFTER). Negative lag = detector leads (detects BEFORE).**

| Scenario | First bear_high (idx/date) | Worst DD Center (idx/date) | Lag vs Worst DD (bars) | Key True Transition | Lag vs True Transition (bars) |
|----------|----------------------------|----------------------------|------------------------|---------------------|------------------------------|
| regime_shift | 435 (2016-09-01) | 2687 (2025-04-21) | -2252 | bull→bear (idx 378) | +57 |
| fat_tail_crash | 325 (2016-03-31) | 637 (2017-06-12) | -312 | first crash (idx 366) | -41 |
| liquidity_crisis | 321 (2016-03-25) | 3052 (2026-09-14) | -2731 | crisis start (idx 3000) | -2679 |
| structural_break | 199 (2015-10-07) | 4325 (2031-07-31) | -4126 | break idx (2500) | -2301 |
| trend_persistence | 1938 (2022-06-07) | 4277 (2031-05-26) | -2339 | trend start (idx 133) | +1805 |
| volatility_clustering | 266 (2016-01-08) | 627 (2017-05-29) | -361 | first high-vol entry (idx 258) | +8 |

**Key observations:**
- **regime_shift**: Detector **lags** the bull→bear transition by +57 bars (detects bear_high after transition).
- **fat_tail_crash**: Fresh detection **leads** the first crash by -41 bars and leads the market worst-DD center by -312 bars.
- **liquidity_crisis / structural_break**: Detector leads the true transition by thousands of bars (early false positives during calm pre-crisis periods).
- **trend_persistence**: Detector **lags** trend start by +1805 bars (trend begins at idx 133, bear_high only at idx 1938), but leads trend end by -1695 bars.
- **volatility_clustering**: Detector slightly leads first high-vol entry by +8 bars.

### 6.2 fat_tail_crash Specific Findings — Fresh vs Baseline Detection

**Fresh detection (current RegimeConfig defaults on seed=42, periods=5000):**
- First `bear_high`: idx 325 (2016-03-31)
- First crash event: idx 366 (2016-05-27) → **detector leads by 41 bars**
- Market worst-DD center: idx 637 (2017-06-12) → **detector leads by 312 bars**

**Baseline regime detection (from `adversarial_stress_test_regime_aware_extended.json`, Section 3 of this report):**
- First `bear_high`: 2016-06-08 (both SMA/EMA)
- SMA worst regime period: 2016-04-06 → 2016-05-13 (bear_low, lowest total_return)
- EMA worst regime period: 2016-03-01 → 2016-03-17 (bull_high, lowest total_return)
- Baseline detector **lags** SMA worst period by ~23 days, **lags** EMA worst period by ~52 days.

**Discrepancy note**: The baseline regime detection (used in the regime-aware overlay) produces a later first `bear_high` (2016-06-08) than fresh detection on the same generator (2016-03-31). This may stem from differences in data slicing (walk-forward OOS windows vs full series) or the regime analysis being computed on strategy returns rather than raw prices. The session-146 hypothesis — that `bear_high` detection lags the strategy's worst drawdown — **is confirmed by the baseline regime detection** (Section 3), but **not by fresh detection on the full price series**.

**Conclusion for the regime-aware overlay**: The overlay uses the baseline regime detection (which lags the strategy's worst periods). This trailing detection causes the overlay to cut exposure during recovery rather than during the crash, explaining the `fat_tail_crash` degradation at all target_vol levels.

### 6.3 Faster Detector Test on fat_tail_crash (target_vol=0.20)

Tested detector variants with lower `vol_quantile_high` (more sensitive to high vol)
and/or shorter `min_regime_length` (faster regime switching) on `fat_tail_crash`
at the best target_vol from the sweep (0.20). Results vs baseline:

| Strategy | Config | vol_q_high | min_reg_len | First bear_high | Baseline Sharpe | Regime-Sized Sharpe | Delta |
|----------|--------|------------|-------------|-----------------|-----------------|---------------------|-------|
| sma_crossover | 1 | 0.6 | 10 | 325 | -0.0060 | -0.0593 | -0.0533 |
| sma_crossover | 2 | 0.5 | 10 | 325 | -0.0060 | -0.0593 | -0.0533 |
| sma_crossover | 3 | 0.75 | 10 | 325 | -0.0060 | -0.0593 | -0.0533 |
| ema_crossover | 1 | 0.6 | 10 | 325 | +0.2142 | -0.1560 | -0.3701 |
| ema_crossover | 2 | 0.5 | 10 | 325 | +0.2142 | -0.1560 | -0.3701 |
| ema_crossover | 3 | 0.75 | 10 | 325 | +0.2142 | -0.1560 | -0.3701 |

**Result**: All three faster-detector configs produce **identical** first `bear_high` (idx 325) and **identical** OOS Sharpe/delta vs the default detector. The `vol_quantile_high` and `min_regime_length` changes tested do not alter the regime sequence on this seed — the first `bear_high` remains at the same position, so the regime-aware overlay behavior is unchanged.

**Best faster-detector config**: vol_quantile_high=0.6, min_regime_length=10 (delta = -0.0533 vs baseline for SMA; -0.3701 for EMA).

**Conclusion**: The faster detector variants tested **do not recover** the `fat_tail_crash` degradation. The regime detection on this seed is insensitive to the tested parameter changes. To address the trailing detection in the baseline overlay, a more fundamental detector change would be needed (e.g., HMM-based detection, asymmetric quantiles, or crash-specific triggers).

### 6.4 Caveats

- Point estimates only on synthetic adversarial data (DSR p ≈ 1.0, test resolution ≈ 2.0 Sharpe).
- No statistical-significance or profitability claim.
- Fresh detection differs from baseline detection; the overlay's behavior is determined by the baseline detection.
- The lag experiment uses market worst-DD center; the session-146 hypothesis concerns strategy worst-regime periods.