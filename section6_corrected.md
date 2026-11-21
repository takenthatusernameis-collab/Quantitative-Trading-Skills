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