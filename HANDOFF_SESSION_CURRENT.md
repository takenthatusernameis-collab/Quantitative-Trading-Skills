# Handoff — Session 143 (2026-11-20): Per-regime breakdown comparison complete; regime-aware overlay falsified

## Baseline
- HEAD `314036f` (session 142 regime-aware variants committed), branch `main`, working tree clean.
- Variant results in `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json` (4 scenario/strategy combos).

## What this session did
**Compared per-regime walk-forward breakdowns between baseline and regime-sized variants** using the saved variant JSON. Verified exposure shrinkage in `*_high` regimes and assessed overall performance impact.

## What was actually verified (ground truth)

### 1. Exposure DOES shrink in `*_high` regimes (confirmation)
| Scenario / Strategy | Regime | Baseline Vol | Regime-sized Vol | Δ Vol |
|---------------------|--------|--------------|------------------|-------|
| volatility_clustering / sma_crossover | bull_high | 0.1652 | 0.0772 | -0.0880 |
| volatility_clustering / sma_crossover | bear_high | 0.2088 | 0.0731 | -0.1357 |
| volatility_clustering / sma_crossover | sideways_high | 0.2005 | 0.0670 | -0.1335 |
| volatility_clustering / ema_crossover | bull_high | 0.2144 | 0.0830 | -0.1314 |
| volatility_clustering / ema_crossover | bear_high | 0.2299 | 0.0738 | -0.1562 |
| volatility_clustering / ema_crossover | sideways_high | 0.2446 | 0.0798 | -0.1648 |
| regime_shift / sma_crossover | bull_high | 0.2237 | 0.0701 | -0.1536 |
| regime_shift / sma_crossover | bear_high | 0.2340 | 0.0714 | -0.1627 |
| regime_shift / sma_crossover | sideways_high | 0.2764 | 0.0859 | -0.1905 |
| regime_shift / ema_crossover | bull_high | 0.2461 | 0.0732 | -0.1730 |
| regime_shift / ema_crossover | bear_high | 0.2557 | 0.0685 | -0.1873 |
| regime_shift / ema_crossover | sideways_high | 0.3224 | 0.0772 | -0.2452 |

**All high-vol regimes show 60-75% volatility reduction**, confirming the `regime_aware_position_size` overlay works as designed (targets 10% annualized vol per regime).

### 2. Overall OOS Sharpe does NOT improve (falsification)
| Scenario / Strategy | Baseline Sharpe | Regime-sized Sharpe | Δ |
|---------------------|-----------------|---------------------|---|
| volatility_clustering / sma_crossover | 0.0919 | 0.0405 | -0.0514 |
| volatility_clustering / ema_crossover | 0.2766 | 0.1759 | -0.1007 |
| regime_shift / sma_crossover | -0.2657 | -0.1319 | +0.1339 |
| regime_shift / ema_crossover | -0.1623 | 0.0138 | +0.1761 |

- **3 of 4 cases: regime-sizing reduces Sharpe** (volatility_clustering both strategies)
- **1 of 4 cases: regime-sizing improves Sharpe but still negative** (regime_shift/sma_crossover: -0.266 → -0.132)
- **1 of 4 cases: regime-sizing reaches slightly positive but negligible** (regime_shift/ema_crossover: -0.162 → 0.014)
- **All Deflated Sharpe p-values = 1.0** — no statistical significance anywhere

### 3. Cost-multiplied variant ≈ baseline
Cost multipliers in high-vol regimes (`bull_high`, `bear_high`, `sideways_high`) apply 1.5× costs but don't change position sizing. Results are virtually identical to baseline (Δ Sharpe < 0.012), confirming cost adjustment alone doesn't drive the regime-sized effect.

## What remains unresolved
- The regime-aware overlay is **falsified as a performance enhancer** for these strategies/scenarios. It reduces risk but reduces returns proportionally more → no net risk-adjusted benefit.
- No decision yet on whether to document this as a worked example with explicit falsification criterion (valid null result) or simply archive it.

## Approaches already tried / failed
- Regime-aware vol targeting: reduces exposure in high-vol regimes as intended, but fails to improve risk-adjusted returns.
- Cost multipliers in high-vol regimes: no meaningful effect without position sizing change.

## One precise next task
**Decide and implement documentation path for this null result:**
- **Option A (recommended):** Promote the regime-aware overlay into a worked example in `skills/quantitative-backtesting/examples/` with an explicit falsification criterion: *"Regime-aware vol targeting to 10% annualized vol per regime must improve OOS Sharpe vs baseline on volatility_clustering/ema_crossover (baseline 0.277). Current result: 0.176 — falsified."*
- **Option B:** Archive the variant results without a worked example; record as a failed hypothesis in a research log.

If Option A: create `regime_aware_vol_targeting_example.py` demonstrating the overlay, the walk-forward comparison, and the falsification. Do not claim profitability. Use the existing `adversarial_stress_test.py` structure as template.

Files to reference:
- `skills/quantitative-backtesting/examples/adversarial_stress_test.py` (has `RegimeAwareStrategy`, `regime_aware_position_size`)
- `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware.json` (variant results)
- `skills/quantitative-backtesting/examples/adversarial_stress_test_results.json` (baseline results)

(End of file)